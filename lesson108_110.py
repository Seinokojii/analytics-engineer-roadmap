#!/usr/bin/env python3
"""
lesson108_110.py — Days 108-110: Airbyte Advanced — custom connector

Запуск:
    python lesson108_110.py                # всё, включая сборку Docker-образа
    python lesson108_110.py --skip-docker  # без шага 10

Нужен отдельный venv с Python CDK (в общий venv ae его ставить нельзя:
airbyte-cdk откатывает pandas 3 -> 2.2 и isodate):
    uv venv --python 3.12 ~/.venvs/airbyte-cdk
    uv pip install --python ~/.venvs/airbyte-cdk/bin/python airbyte-cdk==7.33.0

Что построено:
  airbyte_setup/source-open-meteo/   custom source на Python CDK к Open-Meteo
                                     (публичный API погоды, ключ не нужен):
      cities         full refresh, geocoding: название -> координаты
      daily_weather  incremental по date, слайс = город x месяц,
                     state по городу, lookback window
  airbyte_setup/dbt_open_meteo/      dbt после sync: source с freshness,
                                     Silver с дедупликацией, Gold, тесты

Коннектор Airbyte — отдельная программа с четырьмя командами, которая
пишет JSON-строки в stdout. Платформа запускает её в контейнере и читает
поток. Здесь роль платформы и destination играет сам урок: запускает
коннектор, разбирает сообщения, кладёт RECORD в DuckDB, а STATE сохраняет
и возвращает коннектору при следующем запуске.

Что урок проверяет:
  1. Протокол: spec / check / discover, check на плохом конфиге
  2. Первый sync: сколько RECORD и STATE, что легло в Bronze
  3. Incremental: второй sync читает только новое + lookback
  4. Новый город в конфиге: история догружается только по нему
  5. Ретраи: 429 с Retry-After переживаем, 400 не ретраим
  6. Падение посреди sync и продолжение с последнего STATE
  7. Зачем lookback: источник пересчитывает последние дни
  8. dbt после sync: freshness gate -> build, дедупликация в Silver
  9. Мониторинг: журнал sync'ов и алерт на упавший
 10. Docker: тот же коннектор образом, как его запускает платформа

Шаги 1-4 и 10 ходят в настоящий API. Шаги 5-7 — в локальный mock-сервер:
настоящий API нельзя заставить ответить 500 или пересчитать прошлое.

Что здесь хуже оригинала — честно:
  Платформа Airbyte не поднималась. Коннектор не зарегистрирован в UI,
  расписания, ретраев на уровне job и UI-нотификаций здесь нет.
  Destination — 80 строк в этом файле, а не destination-snowflake:
  нет typing & deduping, нет _airbyte_meta, нет generation_id.
  «Airbyte dbt Transformations» из роадмапа не существует: custom
  transformations удалены из Airbyte OSS, вендор сам советует запускать
  dbt оркестратором. Шаг 8 — эта цепочка, без самого оркестратора.

Рабочую analytics.duckdb урок не трогает: своя база
airbyte_setup/open_meteo.duckdb, каждый запуск пересоздаётся.
"""

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import duckdb

PROJECT_ROOT = Path(__file__).parent
AIRBYTE_DIR = PROJECT_ROOT / "airbyte_setup"
CONNECTOR = AIRBYTE_DIR / "source-open-meteo"
DBT_DIR = AIRBYTE_DIR / "dbt_open_meteo"
DB_PATH = AIRBYTE_DIR / "open_meteo.duckdb"
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# Python из venv с airbyte-cdk. Коннектор живёт в своём окружении —
# в проде это отдельный Docker-образ со своими зависимостями.
CDK_PY = Path(os.environ.get(
    "AIRBYTE_CDK_PYTHON", Path.home() / ".venvs" / "airbyte-cdk" / "bin" / "python"))
# dbt Core из того же venv, что и python: в PATH может стоять dbt Fusion.
DBT = Path(sys.executable).parent / "dbt"
IMAGE = "local/source-open-meteo:0.1.0"

SEP = "=" * 62

REAL_CITIES = ["Bishkek", "Almaty", "Oslo"]
NEW_CITY = "Tashkent"
START = date(2026, 7, 1)
DAY_1 = date(2026, 9, 20)   # «сегодня» первого sync
DAY_2 = date(2026, 9, 30)   # «сегодня» второго: прошло 10 дней
LOOKBACK = 5

WEATHER_COLUMNS = ["city", "date", "temperature_max_c", "temperature_min_c",
                   "precipitation_mm", "wind_speed_max_kmh"]
CITY_COLUMNS = ["city", "geoname_id", "country_code", "country", "latitude",
                "longitude", "elevation_m", "timezone", "population"]


def banner(title):
    print("\n" + SEP)
    print(f"  {title}")
    print(SEP)


def expect(name, got, want):
    if got != want:
        raise SystemExit(f"  FAIL: {name}: получено {got!r}, ожидалось {want!r}")
    print(f"  OK   {name}: {got}")


def days(a, b):
    return (b - a).days + 1


def month_slices(a, b):
    """Сколько календарных месяцев задевает окно a..b — столько слайсов."""
    return 0 if a > b else (b.year - a.year) * 12 + b.month - a.month + 1


def write_csv(name, header, rows):
    path = REPORTS_DIR / name
    # lineterminator: csv.writer по умолчанию пишет \r\n даже на Linux
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


# ─────────────────────────── платформа: запуск коннектора ───────────────────────────

def run_connector(command, workdir, config=None, catalog=None, state=None, runner="venv"):
    """Запустить коннектор и разобрать его stdout. Так делает платформа."""
    args = [command]
    for flag, payload in (("--config", config), ("--catalog", catalog), ("--state", state)):
        if payload is None:
            continue
        name = flag.lstrip("-") + ".json"
        (workdir / name).write_text(json.dumps(payload), encoding="utf-8")
        args += [flag, f"/data/{name}" if runner == "docker" else str(workdir / name)]

    if runner == "docker":
        cmd = ["docker", "run", "--rm", "-v", f"{workdir}:/data", IMAGE, *args]
    else:
        cmd = [str(CDK_PY), str(CONNECTOR / "main.py"), *args]

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    seconds = time.perf_counter() - t0
    messages = []
    for line in proc.stdout.splitlines():
        if line.startswith("{"):
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return messages, proc.returncode, seconds


def fetch_one(con, sql: str) -> tuple:
    """fetchone() в DuckDB типизирован как tuple | None. У агрегата без
    GROUP BY строка есть всегда, но Pylance этого не знает и подсвечивает
    [0] и распаковку. Проверка делает контракт явным."""
    row = con.execute(sql).fetchone()
    if row is None:
        raise RuntimeError(f"запрос не вернул строк: {sql[:60]}")
    return row


def of_type(messages, kind):
    return [m for m in messages if m["type"] == kind]


def configure_catalog(discovered):
    """Из CATALOG коннектора собрать ConfiguredAirbyteCatalog — это то,
    что пользователь накликивает в UI: какие стримы и в каком режиме."""
    streams = []
    for stream in discovered["streams"]:
        if stream["name"] == "daily_weather":
            streams.append({"stream": stream, "sync_mode": "incremental",
                            "cursor_field": ["date"], "destination_sync_mode": "append"})
        else:
            streams.append({"stream": stream, "sync_mode": "full_refresh",
                            "destination_sync_mode": "overwrite"})
    return {"streams": streams}


# ─────────────────────────── destination: 80 строк вместо destination-snowflake ───────────────────────────

def init_destination(con):
    con.execute("create schema if not exists bronze")
    con.execute("create schema if not exists airbyte_internal")
    con.execute("""
        create table if not exists bronze.daily_weather_raw (
            _airbyte_raw_id varchar, _airbyte_extracted_at timestamptz, _airbyte_sync_id integer,
            city varchar, "date" date, temperature_max_c double, temperature_min_c double,
            precipitation_mm double, wind_speed_max_kmh double)""")
    con.execute("""
        create table if not exists bronze.cities (
            city varchar, geoname_id bigint, country_code varchar, country varchar,
            latitude double, longitude double, elevation_m double, timezone varchar,
            population bigint)""")
    con.execute("""
        create table if not exists airbyte_internal.stream_state (
            stream varchar, state_json varchar, updated_at timestamptz)""")
    con.execute("""
        create table if not exists airbyte_internal.sync_log (
            sync_id integer, label varchar, started_at timestamptz, seconds double,
            status varchar, records_cities integer, records_weather integer,
            slices integer, committed_rows integer, error varchar)""")


def sync(con, workdir, config, catalog, label):
    """Один sync: вернуть коннектору сохранённый state, прочитать, положить."""
    started = datetime.now(timezone.utc)
    sync_id = fetch_one(
        con, "select coalesce(max(sync_id), 0) + 1 from airbyte_internal.sync_log")[0]
    saved = [json.loads(row[0]) for row in con.execute(
        "select state_json from airbyte_internal.stream_state").fetchall()]

    messages, code, seconds = run_connector("read", workdir, config, catalog, saved)

    weather_buffer, cities, committed, slices = [], [], 0, 0
    for message in messages:
        if message["type"] == "RECORD":
            record = message["record"]
            if record["stream"] == "daily_weather":
                weather_buffer.append(record["data"])
            else:
                cities.append(record["data"])
        elif message["type"] == "STATE":
            state = message["state"]
            # State сохраняем только у incremental-стрима. У full refresh CDK
            # тоже шлёт state («дочитано»), и если вернуть его в следующий
            # sync, стрим cities решит, что читать уже нечего, и отдаст 0 строк.
            if state["stream"]["stream_descriptor"]["name"] != "daily_weather":
                continue
            slices += 1
            # Записи и state — одной транзакцией. State без записей = дыра
            # в данных, записи без state = дубли. Второе лечится, первое нет.
            con.execute("begin")
            if weather_buffer:
                con.executemany(
                    "insert into bronze.daily_weather_raw values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [[str(uuid.uuid4()), started, sync_id, *[r.get(c) for c in WEATHER_COLUMNS]]
                     for r in weather_buffer])
            con.execute("delete from airbyte_internal.stream_state where stream = 'daily_weather'")
            con.execute("insert into airbyte_internal.stream_state values (?, ?, ?)",
                        ["daily_weather", json.dumps({k: v for k, v in state.items() if k != "sourceStats"}),
                         datetime.now(timezone.utc)])
            con.execute("commit")
            committed += len(weather_buffer)
            weather_buffer = []

    if code == 0 and cities:
        con.execute("begin")
        con.execute("delete from bronze.cities")
        con.executemany("insert into bronze.cities values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [[c.get(col) for col in CITY_COLUMNS] for c in cities])
        con.execute("commit")

    # На упавший стрим коннектор шлёт два TRACE ERROR: по стриму и итоговый
    # по всему sync. Тип сбоя верный только в первом — итоговый CDK всегда
    # помечает config_error, каким бы ни был исходный.
    error = failure_type = None
    for message in of_type(messages, "TRACE"):
        if message["trace"]["type"] == "ERROR" and error is None:
            err = message["trace"]["error"]
            failure_type = err.get("failure_type")
            error = f"[{failure_type}] {err.get('message')}"
    status = "succeeded" if code == 0 else "failed"
    weather_read = sum(1 for m in of_type(messages, "RECORD") if m["record"]["stream"] == "daily_weather")
    con.execute("insert into airbyte_internal.sync_log values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [sync_id, label, started, round(seconds, 2), status, len(cities),
                 weather_read, slices, committed, error])
    return {"sync_id": sync_id, "label": label, "status": status, "seconds": seconds,
            "cities": len(cities), "weather": weather_read, "slices": slices,
            "committed": committed, "discarded": len(weather_buffer), "error": error,
            "failure_type": failure_type,
            "started_at": started.isoformat(timespec="seconds")}


def raw_stats(con):
    total, distinct = fetch_one(
        con, 'select count(*), count(distinct city || cast("date" as varchar)) '
        "from bronze.daily_weather_raw")
    return total, distinct


def saved_cursors(con):
    row = con.execute("select state_json from airbyte_internal.stream_state").fetchone()
    if not row:
        return {}
    stream_state = json.loads(row[0])["stream"]["stream_state"]
    return {city: value["date"] for city, value in stream_state.items()}


# ─────────────────────────── mock API для сбоев ───────────────────────────

def mock_weather(city, day, revised):
    n = day.toordinal()
    tmax = round(18 + 8 * math.sin(n / 11) + len(city) % 5 + (2.0 if (city, day) in revised else 0), 1)
    return {
        "temperature_2m_max": tmax,
        "temperature_2m_min": round(tmax - 9.5, 1),
        "precipitation_sum": round(max(0.0, 6 * math.sin(n / 3)), 1),
        "wind_speed_10m_max": round(10 + 5 * math.cos(n / 5), 1),
    }


class MockApi:
    """Локальный двойник geocoding + archive с управляемыми сбоями."""

    def __init__(self):
        self.requests = []   # (endpoint, city, start_date, status)
        self.rules = []      # {"city", "start_date", "status", "times", "retry_after"}
        self.revised = set() # (city, day): значения «пересчитаны» источником
        self._by_lat = {}
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _send(self, status, body, headers=None):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                if url.path.endswith("/search"):
                    name = query["name"]
                    lat = round(35 + sum(map(ord, name)) % 2000 / 100, 2)
                    api._by_lat[lat] = name
                    api.requests.append(("search", name, None, 200))
                    self._send(200, {"results": [{"id": 1, "name": name, "latitude": lat,
                                                  "longitude": 70.0, "country_code": "ZZ"}]})
                    return
                city = api._by_lat[float(query["latitude"])]
                start, end = date.fromisoformat(query["start_date"]), date.fromisoformat(query["end_date"])
                for rule in api.rules:
                    if rule["city"] == city and rule["start_date"] == query["start_date"] and rule["times"] != 0:
                        if rule["times"] is not None:
                            rule["times"] -= 1
                        api.requests.append(("archive", city, query["start_date"], rule["status"]))
                        headers = {"Retry-After": str(rule["retry_after"])} if rule.get("retry_after") else None
                        self._send(rule["status"], {"error": True, "reason": rule.get("reason", "mock failure")}, headers)
                        return
                api.requests.append(("archive", city, query["start_date"], 200))
                span = [start + timedelta(days=i) for i in range(days(start, end))]
                daily: dict[str, list] = {"time": [d.isoformat() for d in span]}
                for d in span:
                    for key, value in mock_weather(city, d, api.revised).items():
                        daily.setdefault(key, []).append(value)
                self._send(200, {"daily": daily})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def reset(self):
        self.requests.clear()
        self.rules.clear()
        self.revised.clear()

    def archive_calls(self, city=None, start_date=None):
        return [r for r in self.requests if r[0] == "archive"
                and (city is None or r[1] == city) and (start_date is None or r[2] == start_date)]

    def config(self, cities, start, end, lookback=LOOKBACK):
        return {"cities": cities, "start_date": start.isoformat(), "end_date": end.isoformat(),
                "lookback_days": lookback, "max_retry_wait_seconds": 1,
                "archive_base_url": self.url, "geocoding_base_url": self.url}

    def stop(self):
        self._server.shutdown()


def memory_destination():
    con = duckdb.connect(":memory:")
    init_destination(con)
    return con


# ─────────────────────────── шаги ───────────────────────────

def real_config(cities, end):
    return {"cities": cities, "start_date": START.isoformat(),
            "end_date": end.isoformat(), "lookback_days": LOOKBACK}


def step1_protocol(tmp):
    banner("STEP 1: протокол — spec / check / discover")
    rows = []
    config = real_config(REAL_CITIES, DAY_1)

    messages, code, seconds = run_connector("spec", tmp)
    spec = of_type(messages, "SPEC")[0]["spec"]["connectionSpecification"]
    hidden = [k for k, v in spec["properties"].items() if v.get("airbyte_hidden")]
    print(f"  spec      {seconds:.1f} с  обязательные поля: {spec['required']}, "
          f"скрытых от UI: {len(hidden)}")
    rows.append(["spec", code, "SPEC", f"required={spec['required']}"])

    messages, code, seconds = run_connector("check", tmp, config)
    status = of_type(messages, "CONNECTION_STATUS")[0]["connectionStatus"]
    print(f"  check     {seconds:.1f} с  {status['status']}")
    expect("check на рабочем конфиге", status["status"], "SUCCEEDED")
    rows.append(["check", code, status["status"], ""])

    bad = dict(config, cities=["Bishkek", "Zzzqqxx"])
    messages, code, seconds = run_connector("check", tmp, bad)
    status = of_type(messages, "CONNECTION_STATUS")[0]["connectionStatus"]
    print(f"  check     {seconds:.1f} с  {status['status']}: {status['message']}")
    expect("check на опечатке в городе", status["status"], "FAILED")
    # Плохой конфиг — это ответ FAILED с кодом выхода 0, а не падение.
    # Упавший check платформа показала бы как «коннектор сломан».
    expect("код выхода при FAILED", code, 0)
    rows.append(["check (плохой конфиг)", code, status["status"], status["message"]])

    messages, code, seconds = run_connector("discover", tmp, config)
    catalog = of_type(messages, "CATALOG")[0]["catalog"]
    print(f"  discover  {seconds:.1f} с")
    for stream in catalog["streams"]:
        print(f"    {stream['name']:<14} режимы={stream['supported_sync_modes']} "
              f"cursor={stream.get('default_cursor_field')} pk={stream.get('source_defined_primary_key')}")
        rows.append(["discover", code, stream["name"],
                     f"modes={stream['supported_sync_modes']} cursor={stream.get('default_cursor_field')} "
                     f"pk={stream.get('source_defined_primary_key')}"])
    expect("стримов в каталоге", len(catalog["streams"]), 2)

    write_csv("day108_110_protocol.csv", ["command", "exit_code", "result", "details"], rows)
    return configure_catalog(catalog)


def step2_first_sync(con, tmp, catalog):
    banner("STEP 2: первый sync — state пустой, читаем всю историю")
    result = sync(con, tmp, real_config(REAL_CITIES, DAY_1), catalog, "first sync")
    if result["status"] != "succeeded":
        raise SystemExit(f"  FAIL: sync упал: {result['error']}")
    want_rows = days(START, DAY_1) * len(REAL_CITIES)
    want_slices = month_slices(START, DAY_1) * len(REAL_CITIES)
    print(f"  {result['seconds']:.1f} с, окно {START} .. {DAY_1}")
    expect("RECORD cities", result["cities"], len(REAL_CITIES))
    expect("RECORD daily_weather", result["weather"], want_rows)
    # STATE после каждого слайса: слайс = город x месяц
    expect("STATE (слайсов)", result["slices"], want_slices)
    total, distinct = raw_stats(con)
    expect("строк в bronze.daily_weather_raw", total, want_rows)
    expect("из них уникальных city + date", distinct, want_rows)
    print(f"  state по городам: {saved_cursors(con)}")
    return result


def step3_incremental(con, tmp, catalog):
    banner("STEP 3: incremental — прошло 10 дней, читаем только хвост")
    first_total, _ = raw_stats(con)

    result = sync(con, tmp, real_config(REAL_CITIES, DAY_2), catalog, "incremental")
    window_start = DAY_1 - timedelta(days=LOOKBACK - 1)
    want = days(window_start, DAY_2) * len(REAL_CITIES)
    reread = LOOKBACK * len(REAL_CITIES)
    print(f"  {result['seconds']:.1f} с, окно {window_start} .. {DAY_2} "
          f"(cursor {DAY_1} минус lookback {LOOKBACK})")
    expect("RECORD daily_weather", result["weather"], want)
    expect("STATE (слайсов)", result["slices"], len(REAL_CITIES))
    total, distinct = raw_stats(con)
    expect("строк в Bronze", total, first_total + want)
    expect("уникальных city + date", distinct, days(START, DAY_2) * len(REAL_CITIES))
    expect("дублей от lookback", total - distinct, reread)
    print(f"  прочитано {want} вместо {days(START, DAY_2) * len(REAL_CITIES)} при полном чтении")

    noop = sync(con, tmp, real_config(REAL_CITIES, DAY_2), catalog, "no new data")
    print(f"\n  третий sync, новых дней нет: {noop['seconds']:.1f} с")
    # Новых данных ноль, но lookback всё равно перечитывает свои 5 дней.
    # Это цена: sync «без изменений» не бесплатный.
    expect("RECORD при пустом приросте", noop["weather"], reread)
    return result, noop


def step4_new_city(con, tmp, catalog):
    banner(f"STEP 4: в конфиг добавлен город {NEW_CITY}")
    before_total, before_distinct = raw_stats(con)
    result = sync(con, tmp, real_config(REAL_CITIES + [NEW_CITY], DAY_2), catalog, "new city")
    history = days(START, DAY_2)
    reread = LOOKBACK * len(REAL_CITIES)
    print(f"  {result['seconds']:.1f} с")
    # У нового города state нет — он читается с start_date. Старые города
    # читают только lookback. С одним cursor на стрим новый город начал бы
    # с 30 сентября и остался без истории.
    expect("RECORD daily_weather", result["weather"], history + reread)
    by_city = dict(con.execute(
        "select city, count(*) from bronze.daily_weather_raw where _airbyte_sync_id = ? group by 1",
        [result["sync_id"]]).fetchall())
    expect(f"из них {NEW_CITY}", by_city[NEW_CITY], history)
    expect("на каждый старый город", by_city["Bishkek"], LOOKBACK)
    _, distinct = raw_stats(con)
    expect("уникальных city + date", distinct, before_distinct + history)
    expect("городов в bronze.cities",
           fetch_one(con, "select count(*) from bronze.cities")[0], len(REAL_CITIES) + 1)
    return result


def step5_retries(mock, tmp, catalog):
    banner("STEP 5: ретраи — что повторяем, а что нет (mock API)")
    cities, start, end = ["Alpha", "Beta", "Gamma"], date(2026, 6, 1), date(2026, 8, 31)
    full = days(start, end) * len(cities)
    rows = []

    mock.reset()
    mock.rules.append({"city": "Alpha", "start_date": "2026-07-01", "status": 429,
                       "times": 2, "retry_after": 1})
    result = sync(memory_destination(), tmp, mock.config(cities, start, end), catalog, "429 x2")
    calls = mock.archive_calls("Alpha", "2026-07-01")
    print(f"  429 дважды, Retry-After: 1 -> {result['status']}, {result['seconds']:.1f} с")
    expect("sync пережил 429", result["status"], "succeeded")
    expect("запросов к этому слайсу", [c[3] for c in calls], [429, 429, 200])
    expect("записей", result["weather"], full)
    rows.append(["429 x2 + Retry-After", result["status"], len(calls), result["weather"], ""])

    mock.reset()
    mock.rules.append({"city": "Alpha", "start_date": "2026-06-01", "status": 400,
                       "times": None, "reason": "Parameter 'daily' is invalid"})
    result = sync(memory_destination(), tmp, mock.config(cities, start, end), catalog, "400")
    calls = mock.archive_calls("Alpha", "2026-06-01")
    print(f"  400 -> {result['status']}, {result['seconds']:.1f} с")
    print(f"    {result['error']}")
    expect("sync на 400", result["status"], "failed")
    expect("тип сбоя", result["failure_type"], "system_error")
    # 400 — запрос неверный, повтор вернёт то же самое. Ретраить его —
    # жечь лимит API и откладывать алерт.
    expect("запросов к этому слайсу (без повторов)", len(calls), 1)
    rows.append(["400", result["status"], len(calls), result["weather"], result["error"]])

    write_csv("day108_110_retries.csv",
              ["scenario", "sync_status", "requests_to_slice", "records", "error"], rows)


def step6_crash_and_resume(mock, tmp, catalog):
    banner("STEP 6: падение посреди sync и продолжение со state (mock API)")
    cities, start, end = ["Alpha", "Beta", "Gamma"], date(2026, 6, 1), date(2026, 8, 31)
    config = mock.config(cities, start, end)
    full = days(start, end) * len(cities)
    con = memory_destination()

    mock.reset()
    mock.rules.append({"city": "Beta", "start_date": "2026-07-01", "status": 500, "times": None})
    crashed = sync(con, tmp, config, catalog, "crash")
    attempts = len(mock.archive_calls("Beta", "2026-07-01"))
    done = days(start, end) + days(date(2026, 6, 1), date(2026, 6, 30))  # Alpha целиком + июнь Beta
    print(f"  Beta / июль отвечает 500 -> {crashed['status']}, {crashed['seconds']:.1f} с")
    print(f"    {crashed['error']}")
    expect("sync", crashed["status"], "failed")
    expect("попыток на упавший слайс (1 + 5 повторов)", attempts, 6)
    # transient_error: платформа сама перезапустит job. system_error и
    # config_error она не ретраит — нужен человек.
    expect("тип сбоя", crashed["failure_type"], "transient_error")
    expect("строк закоммичено до падения", crashed["committed"], done)
    expect("state на момент падения", saved_cursors(con), {"Alpha": "2026-08-31", "Beta": "2026-06-30"})

    mock.reset()
    resumed = sync(con, tmp, config, catalog, "resume")
    total, distinct = raw_stats(con)
    # Alpha: только lookback. Beta: lookback от 30 июня + июль + август. Gamma: всё.
    want = LOOKBACK + (LOOKBACK + days(date(2026, 7, 1), end)) + days(start, end)
    print(f"\n  API починили, тот же sync ещё раз: {resumed['status']}, {resumed['seconds']:.1f} с")
    expect("sync", resumed["status"], "succeeded")
    expect("RECORD при продолжении", resumed["weather"], want)
    expect("уникальных city + date в итоге", distinct, full)
    expect("дублей", total - distinct, 2 * LOOKBACK)
    print(f"  продолжение прочитало {want} записей, sync с нуля прочитал бы {full} "
          f"и дал бы {done} дублей")

    write_csv("day108_110_crash_resume.csv",
              ["run", "status", "records_read", "rows_committed", "state_after", "error"],
              [["crash", crashed["status"], crashed["weather"], crashed["committed"],
                "Alpha=2026-08-31 Beta=2026-06-30", crashed["error"]],
               ["resume", resumed["status"], resumed["weather"], resumed["committed"],
                json.dumps(saved_cursors(con)), ""]])
    return crashed


def step7_lookback(mock, tmp, catalog):
    banner("STEP 7: зачем lookback — источник пересчитывает прошлое (mock API)")
    cities, start = ["Alpha", "Beta"], date(2026, 8, 1)
    day_1, day_2 = date(2026, 8, 20), date(2026, 8, 25)
    revised_days = [date(2026, 8, 18), date(2026, 8, 19), date(2026, 8, 20)]
    rows = []
    for lookback in (0, LOOKBACK):
        mock.reset()
        con = memory_destination()
        sync(con, tmp, mock.config(cities, start, day_1, lookback), catalog, "day 1")
        # Между sync'ами источник досчитал последние три дня: значения изменились.
        mock.revised.update((c, d) for c in cities for d in revised_days)
        second = sync(con, tmp, mock.config(cities, start, day_2, lookback), catalog, "day 2")

        latest = con.execute("""
            select city, "date", temperature_max_c from bronze.daily_weather_raw
            qualify row_number() over (partition by city, "date"
                                       order by _airbyte_sync_id desc) = 1""").fetchall()
        stale = sum(1 for city, day, tmax in latest
                    if tmax != mock_weather(city, day, mock.revised)["temperature_2m_max"])
        print(f"  lookback_days={lookback}: второй sync прочитал {second['weather']:>2} записей, "
              f"устаревших строк в витрине: {stale} из {len(latest)}")
        rows.append([lookback, second["weather"], len(latest), stale])

    expect("устаревших строк без lookback", rows[0][3], len(revised_days) * len(cities))
    expect("устаревших строк с lookback 5", rows[1][3], 0)
    # Cursor по дате отвечает на вопрос «что нового», а не «что изменилось».
    # Lookback — плата за то, что у источника нет updated_at.
    write_csv("day108_110_lookback.csv",
              ["lookback_days", "records_read_second_sync", "rows_in_mart", "stale_rows"], rows)
    return rows


def run_dbt(args, db_path, target_path=None):
    cmd = [str(DBT), *args, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    if target_path:
        cmd += ["--target-path", str(target_path)]
    env = dict(os.environ, OPEN_METEO_DB=str(db_path))
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def freshness_gate(db_path, target_path):
    """Вернуть (статус source, возраст в часах). Статус error = не строим."""
    proc = run_dbt(["source", "freshness"], db_path, target_path)
    report = json.loads((target_path / "sources.json").read_text(encoding="utf-8"))
    result = next(r for r in report["results"] if r["unique_id"].endswith("daily_weather_raw"))
    return result["status"], result["max_loaded_at_time_ago_in_s"] / 3600, proc.returncode


def step8_dbt_after_sync(tmp):
    banner("STEP 8: dbt после sync — freshness gate -> build")
    if not DBT.exists():
        raise SystemExit(f"  Нет {DBT} — урок запускается из venv ae")
    target = DBT_DIR / "target"

    status, age, _ = freshness_gate(DB_PATH, target)
    print(f"  freshness bronze.daily_weather_raw: {status}, данным {age * 60:.0f} мин")
    expect("gate после свежего sync", status, "pass")

    t0 = time.perf_counter()
    proc = run_dbt(["build"], DB_PATH)
    seconds = time.perf_counter() - t0
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        raise SystemExit("  FAIL: dbt build упал")
    results = json.loads((target / "run_results.json").read_text(encoding="utf-8"))["results"]
    statuses = [r["status"] for r in results]
    print(f"  dbt build {seconds:.1f} с: узлов {len(results)}, "
          f"success/pass {sum(s in ('success', 'pass') for s in statuses)}, "
          f"остальных {sum(s not in ('success', 'pass') for s in statuses)}")
    expect("упавших узлов", sum(s not in ("success", "pass") for s in statuses), 0)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    raw, silver, gold = (fetch_one(con, f"select count(*) from {t}")[0] for t in (
        "bronze.daily_weather_raw", "main_silver.stg_open_meteo__daily_weather",
        "main_gold.mart_weather_monthly"))
    mart = con.execute("""
        select city, month, days_loaded, avg_temperature_max_c, precipitation_mm, rainy_days
        from main_gold.mart_weather_monthly order by city, month""").fetchall()
    con.close()
    print(f"  Bronze {raw} строк -> Silver {silver} (дублей lookback снято: {raw - silver}) -> Gold {gold}")
    expect("Silver = уникальные city + date", silver, days(START, DAY_2) * (len(REAL_CITIES) + 1))
    for row in mart[:3]:
        print(f"    {row[0]:<8} {row[1]}  дней {row[2]:>2}  t_max {row[3]:>5}  осадки {row[4]:>6} мм")
    write_csv("day108_110_mart_weather_monthly.csv",
              ["city", "month", "days_loaded", "avg_temperature_max_c", "precipitation_mm", "rainy_days"], mart)

    # Тихий сбой: sync три дня «успешен», но ничего не привозит. Job зелёный,
    # алерта нет. Ловит это только возраст данных.
    stale_db = tmp / "stale.duckdb"
    shutil.copy(DB_PATH, stale_db)
    con = duckdb.connect(str(stale_db))
    con.execute("update bronze.daily_weather_raw "
                "set _airbyte_extracted_at = _airbyte_extracted_at - interval 3 day")
    con.close()
    status, age, code = freshness_gate(stale_db, tmp / "stale_target")
    print(f"\n  та же база, sync'ов не было 3 дня: freshness {status}, данным {age:.0f} ч, "
          f"код выхода dbt {code}")
    expect("gate на протухшем источнике", status, "error")
    expect("dbt build после этого", "не запускается" if code != 0 else "запустился бы", "не запускается")
    return {"raw": raw, "silver": silver, "gold": gold, "nodes": len(results), "seconds": seconds}


def step9_monitoring(con, crashed):
    banner("STEP 9: мониторинг — журнал sync'ов и алерт")
    log = con.execute("""
        select sync_id, label, strftime(started_at, '%Y-%m-%d %H:%M:%S'), seconds, status,
               records_weather, slices, committed_rows, coalesce(error, '')
        from airbyte_internal.sync_log order by sync_id""").fetchall()
    for row in log:
        print(f"  #{row[0]} {row[1]:<12} {row[4]:<9} {row[3]:>5.1f} с  записей {row[5]:>3}  слайсов {row[6]}")
    write_csv("day108_110_sync_log.csv",
              ["sync_id", "label", "started_at", "seconds", "status", "records_weather",
               "slices", "committed_rows", "error"], log)

    # Алерт собираем из упавшего sync шага 6. В Airbyte это Settings ->
    # Notifications -> Failed syncs -> webhook; тело запроса похожее.
    payload = {
        "text": f":red_circle: Airbyte sync failed: open-meteo -> bronze ({crashed['label']})",
        "connection": "open-meteo -> duckdb.bronze",
        "started_at": crashed["started_at"],
        "duration_seconds": round(crashed["seconds"], 1),
        "records_committed": crashed["committed"],
        "error": crashed["error"],
        "action": "state сохранён, повторный запуск продолжит с упавшего слайса",
    }
    print("\n  алерт на упавший sync:")
    print("    " + json.dumps(payload, ensure_ascii=False, indent=2).replace("\n", "\n    "))
    webhook = os.environ.get("ALERT_WEBHOOK_URL")
    if webhook:
        request = urllib.request.Request(webhook, data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            print(f"  отправлено на ALERT_WEBHOOK_URL: HTTP {response.status}")
    else:
        print("  ALERT_WEBHOOK_URL не задан — алерт только напечатан, никуда не ушёл")
    print("""
  Три сигнала, и каждый ловит своё:
    job failed            коннектор упал              -> webhook платформы
    job succeeded, 0 строк  API отдал пусто, cursor стоит -> проверка числа записей
    данные старше порога  sync не запускался вообще   -> dbt source freshness""")
    return log


def step10_docker(tmp, catalog, skip):
    banner("STEP 10: Docker — коннектор так, как его запускает платформа")
    if skip:
        print("  пропущено: --skip-docker")
        return None
    if not shutil.which("docker") or subprocess.run(
            ["docker", "info"], capture_output=True).returncode != 0:
        print("  пропущено: Docker недоступен (нет бинарника или демон не запущен)")
        return None

    t0 = time.perf_counter()
    build = subprocess.run(["docker", "build", "-q", "-t", IMAGE, str(CONNECTOR)],
                           capture_output=True, text=True)
    if build.returncode != 0:
        print(build.stderr[-2000:])
        raise SystemExit("  FAIL: образ не собрался")
    size = subprocess.run(["docker", "image", "inspect", IMAGE, "--format", "{{.Size}}"],
                          capture_output=True, text=True).stdout.strip()
    print(f"  образ {IMAGE} собран за {time.perf_counter() - t0:.0f} с, {int(size) / 1e6:.0f} МБ")

    workdir = tmp / "docker"
    workdir.mkdir()
    workdir.chmod(0o755)
    config = {"cities": ["Bishkek"], "start_date": "2026-09-01",
              "end_date": DAY_1.isoformat(), "lookback_days": LOOKBACK}

    messages, code, seconds = run_connector("spec", workdir, runner="docker")
    expect("docker run ... spec", (code, len(of_type(messages, "SPEC"))), (0, 1))

    in_docker, code, docker_seconds = run_connector("read", workdir, config, catalog, runner="docker")
    expect("docker run ... read, код выхода", code, 0)
    in_venv, _, venv_seconds = run_connector("read", workdir, config, catalog)

    def records(messages):
        return sorted(json.dumps(m["record"]["data"], sort_keys=True) for m in of_type(messages, "RECORD"))

    print(f"  read: контейнер {docker_seconds:.1f} с, venv {venv_seconds:.1f} с")
    expect("RECORD из контейнера", len(records(in_docker)), 1 + days(date(2026, 9, 1), DAY_1))
    expect("записи контейнера и venv совпадают", records(in_docker) == records(in_venv), True)
    return {"size_mb": int(size) / 1e6, "docker_seconds": docker_seconds, "venv_seconds": venv_seconds}


def step11_summary(first, incremental, noop, new_city, lookback_rows, dbt_stats, docker):
    banner("STEP 11: сводка")
    full_second = days(START, DAY_2) * len(REAL_CITIES)
    rows = [
        ["first_sync_records", first["weather"]],
        ["first_sync_slices", first["slices"]],
        ["incremental_records", incremental["weather"]],
        ["full_refresh_would_read", full_second],
        ["noop_sync_records", noop["weather"]],
        ["new_city_sync_records", new_city["weather"]],
        ["lookback0_stale_rows", lookback_rows[0][3]],
        ["lookback5_stale_rows", lookback_rows[1][3]],
        ["bronze_rows", dbt_stats["raw"]],
        ["silver_rows", dbt_stats["silver"]],
        ["duplicates_removed", dbt_stats["raw"] - dbt_stats["silver"]],
        ["gold_rows", dbt_stats["gold"]],
        ["dbt_nodes", dbt_stats["nodes"]],
        ["docker_image_mb", round(docker["size_mb"]) if docker else "skipped"],
    ]
    path = write_csv("day108_110_summary.csv", ["metric", "value"], rows)
    for metric, value in rows:
        print(f"  {metric:<28} {value}")
    return path


def main():
    parser = argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0])
    parser.add_argument("--skip-docker", action="store_true", help="не собирать образ (шаг 10)")
    args = parser.parse_args()

    t0 = time.perf_counter()
    if not CDK_PY.exists():
        raise SystemExit(
            f"Нет {CDK_PY}\n"
            "  uv venv --python 3.12 ~/.venvs/airbyte-cdk\n"
            "  uv pip install --python ~/.venvs/airbyte-cdk/bin/python airbyte-cdk==7.33.0")

    # База урока своя и пересоздаётся: повторный запуск даёт те же цифры.
    for leftover in (DB_PATH, DB_PATH.with_suffix(".duckdb.wal")):
        leftover.unlink(missing_ok=True)

    mock = MockApi()
    with tempfile.TemporaryDirectory(prefix="airbyte_") as tmp_str:
        tmp = Path(tmp_str)
        catalog = step1_protocol(tmp)

        con = duckdb.connect(str(DB_PATH))
        init_destination(con)
        first = step2_first_sync(con, tmp, catalog)
        incremental, noop = step3_incremental(con, tmp, catalog)
        new_city = step4_new_city(con, tmp, catalog)
        con.close()  # dbt в шаге 8 открывает файл сам; два писателя DuckDB не пускает

        step5_retries(mock, tmp, catalog)
        crashed = step6_crash_and_resume(mock, tmp, catalog)
        lookback_rows = step7_lookback(mock, tmp, catalog)
        mock.stop()

        dbt_stats = step8_dbt_after_sync(tmp)
        con = duckdb.connect(str(DB_PATH), read_only=True)
        step9_monitoring(con, crashed)
        con.close()
        docker = step10_docker(tmp, catalog, args.skip_docker)
        summary_path = step11_summary(first, incremental, noop, new_city,
                                      lookback_rows, dbt_stats, docker)

    print("\n" + SEP)
    print(f"  ALL DONE  ({time.perf_counter() - t0:.0f} с)")
    print(SEP)
    print(f"""
Артефакты:
  airbyte_setup/source-open-meteo/   коннектор + Dockerfile
  airbyte_setup/dbt_open_meteo/      dbt-проект поверх Bronze
  airbyte_setup/open_meteo.duckdb    bronze / main_silver / main_gold / airbyte_internal
  reports/day108_110_protocol.csv
  reports/day108_110_retries.csv
  reports/day108_110_crash_resume.csv
  reports/day108_110_lookback.csv
  reports/day108_110_mart_weather_monthly.csv
  reports/day108_110_sync_log.csv
  {summary_path.relative_to(PROJECT_ROOT)}

Что осталось несделанным честно:
  Платформа Airbyte не поднималась: коннектор не зарегистрирован в UI
  (Settings -> Sources -> New connector -> Docker image), sync по
  расписанию и webhook-нотификации платформы не проверены.
  Destination — самописный, в DuckDB. В Snowflake коннектор не писал.
  Sync и dbt связаны кодом урока, а не Dagster-ассетами.

Next steps:
  1. Поиграть руками, без урока:
       cd airbyte_setup/source-open-meteo
       ~/.venvs/airbyte-cdk/bin/python main.py spec
       ~/.venvs/airbyte-cdk/bin/python main.py read \\
           --config sample_files/config.json --catalog sample_files/configured_catalog.json | head
  2. Days 111-113 — MetricFlow Deep Dive
  3. Концепты в базу: /ae-concept Airbyte CDK, Incremental Sync, Lookback Window

Git:
  git add lesson108_110.py airbyte_setup/source-open-meteo airbyte_setup/dbt_open_meteo \\
          reports/day108_110_* .gitignore
  git commit -m "feat: Days 108-110 Airbyte Advanced — custom connector на Python CDK"
""")


if __name__ == "__main__":
    main()
