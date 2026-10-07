"""
Source Open-Meteo — custom коннектор Airbyte на Python CDK.

Два стрима:
  cities         full refresh. Название города -> координаты (geocoding API)
  daily_weather  incremental по date. Дневная погода из архива,
                 слайс = город x календарный месяц

State у daily_weather — по городу: {"Bishkek": {"date": "2026-09-20"}}.
Один cursor на весь стрим сломал бы добавление города: у нового города
истории нет, а общий cursor уже стоит на вчерашнем дне.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple, Union

import requests
from airbyte_cdk.models import FailureType, SyncMode
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import IncrementalMixin, Stream
from airbyte_cdk.sources.streams.core import StreamData
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.error_handlers import BackoffStrategy
from airbyte_cdk.utils.traced_exception import AirbyteTracedException

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/"

CURSOR = "date"

# имя в API -> имя колонки в стриме
DAILY_FIELDS = {
    "temperature_2m_max": "temperature_max_c",
    "temperature_2m_min": "temperature_min_c",
    "precipitation_sum": "precipitation_mm",
    "wind_speed_10m_max": "wind_speed_max_kmh",
}


class RetryAfterBackoff(BackoffStrategy):
    """Ждём столько, сколько просит сервер; иначе экспонента с потолком."""

    def __init__(self, max_wait: float):
        self.max_wait = max_wait

    def backoff_time(
        self,
        response_or_exception: Optional[Union[requests.Response, requests.RequestException]],
        attempt_count: int,
    ) -> Optional[float]:
        wait = float(2 ** max(attempt_count - 1, 0))
        if isinstance(response_or_exception, requests.Response):
            retry_after = response_or_exception.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = float(retry_after)
        return min(wait, self.max_wait)


class OpenMeteoStream(HttpStream):
    def __init__(self, config: Mapping[str, Any]):
        # config — до super(): HttpStream.__init__ собирает HTTP-клиент
        # и уже в конструкторе зовёт get_backoff_strategy().
        self.config = config
        super().__init__()

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        # Пагинации в API нет: окно задаётся датами, его режут слайсы.
        return None

    def get_backoff_strategy(self) -> BackoffStrategy:
        return RetryAfterBackoff(float(self.config.get("max_retry_wait_seconds", 60)))


class Cities(OpenMeteoStream):
    @property
    def primary_key(self) -> Optional[Union[str, List[str], List[List[str]]]]:
        return "city"

    def resolved(self) -> Iterable[Mapping[str, Any]]:
        """Города конфига с координатами — для слайсов daily_weather и check."""
        for parent_slice in self.stream_slices(sync_mode=SyncMode.full_refresh):
            for record in self.read_records(sync_mode=SyncMode.full_refresh, stream_slice=parent_slice):
                # read_records по типу может вернуть и AirbyteMessage; здесь только записи
                if isinstance(record, Mapping):
                    yield record

    @property
    def url_base(self) -> str:
        return self.config.get("geocoding_base_url") or GEOCODING_URL

    def path(self, **kwargs: Any) -> str:
        return "search"

    def stream_slices(self, **kwargs: Any) -> Iterable[Optional[Mapping[str, Any]]]:
        for name in self.config["cities"]:
            yield {"city": name}

    def request_params(
        self,
        stream_state: Optional[Mapping[str, Any]],
        stream_slice: Optional[Mapping[str, Any]] = None,
        next_page_token: Optional[Mapping[str, Any]] = None,
    ) -> MutableMapping[str, Any]:
        city = (stream_slice or {})["city"]
        return {"name": city, "count": 1, "language": "en", "format": "json"}

    def parse_response(
        self,
        response: requests.Response,
        *,
        stream_slice: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> Iterable[Mapping[str, Any]]:
        name = (stream_slice or {})["city"]
        results = response.json().get("results") or []
        if not results:
            # Опечатка в названии — ошибка конфига, а не сбой системы:
            # платформа не будет ретраить и покажет текст пользователю.
            raise AirbyteTracedException(
                message=f"Город '{name}' не найден в geocoding API. Проверь название в конфиге.",
                failure_type=FailureType.config_error,
            )
        hit = results[0]
        yield {
            # ключ — название из конфига, а не из ответа: по нему живёт state
            "city": name,
            "geoname_id": hit.get("id"),
            "country_code": hit.get("country_code"),
            "country": hit.get("country"),
            "latitude": hit["latitude"],
            "longitude": hit["longitude"],
            "elevation_m": hit.get("elevation"),
            "timezone": hit.get("timezone"),
            "population": hit.get("population"),
        }


class DailyWeather(OpenMeteoStream, IncrementalMixin):
    @property
    def primary_key(self) -> Optional[Union[str, List[str], List[List[str]]]]:
        return ["city", "date"]

    @property
    def cursor_field(self) -> Union[str, List[str]]:
        return CURSOR

    @property
    def state_checkpoint_interval(self) -> Optional[int]:
        # State выдаётся после каждого слайса, а не каждые N записей:
        # слайс — один HTTP-ответ, внутри него чекпойнтить нечего.
        return None

    def __init__(self, config: Mapping[str, Any], cities: Cities):
        super().__init__(config)
        self.cities = cities
        self._state: MutableMapping[str, Any] = {}

    @property
    def url_base(self) -> str:
        return self.config.get("archive_base_url") or ARCHIVE_URL

    def path(self, **kwargs: Any) -> str:
        return "archive"

    @property
    def state(self) -> MutableMapping[str, Any]:
        return self._state

    @state.setter
    def state(self, value: MutableMapping[str, Any]) -> None:
        self._state = dict(value or {})

    def _end_date(self) -> date:
        if self.config.get("end_date"):
            return date.fromisoformat(self.config["end_date"])
        return datetime.now(timezone.utc).date() - timedelta(days=1)

    def stream_slices(
        self,
        *,
        sync_mode: SyncMode,
        cursor_field: Optional[List[str]] = None,
        stream_state: Optional[Mapping[str, Any]] = None,
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        config_start = date.fromisoformat(self.config["start_date"])
        end = self._end_date()
        lookback = timedelta(days=int(self.config.get("lookback_days", 5)))
        state = stream_state or {}

        for city in self.cities.resolved():
            start = config_start
            cursor = (state.get(city["city"]) or {}).get(CURSOR)
            if sync_mode == SyncMode.incremental and cursor:
                # Откатываемся на lookback: последние дни архив пересчитывает.
                start = max(config_start, date.fromisoformat(cursor) - lookback + timedelta(days=1))
            while start <= end:
                month_end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                stop = min(month_end, end)
                yield {
                    "city": city["city"],
                    "latitude": city["latitude"],
                    "longitude": city["longitude"],
                    "start_date": start.isoformat(),
                    "end_date": stop.isoformat(),
                }
                start = stop + timedelta(days=1)

    def request_params(
        self,
        stream_state: Optional[Mapping[str, Any]],
        stream_slice: Optional[Mapping[str, Any]] = None,
        next_page_token: Optional[Mapping[str, Any]] = None,
    ) -> MutableMapping[str, Any]:
        window = stream_slice or {}
        return {
            "latitude": window["latitude"],
            "longitude": window["longitude"],
            "start_date": window["start_date"],
            "end_date": window["end_date"],
            "daily": ",".join(DAILY_FIELDS),
            "timezone": "UTC",
        }

    def parse_response(
        self,
        response: requests.Response,
        *,
        stream_slice: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> Iterable[Mapping[str, Any]]:
        daily = response.json().get("daily") or {}
        for i, day in enumerate(daily.get("time") or []):
            values = {column: (daily.get(api_name) or [None])[i] for api_name, column in DAILY_FIELDS.items()}
            if all(v is None for v in values.values()):
                # Архив ещё не досчитал этот день. Пропускаем и cursor
                # за него не двигаем — день придёт в следующий sync.
                continue
            yield {"city": (stream_slice or {})["city"], "date": day, **values}

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: Optional[List[str]] = None,
        stream_slice: Optional[Mapping[str, Any]] = None,
        stream_state: Optional[Mapping[str, Any]] = None,
    ) -> Iterable[StreamData]:
        latest = None
        for record in super().read_records(sync_mode, cursor_field, stream_slice, stream_state):
            if isinstance(record, Mapping):
                latest = record["date"] if latest is None else max(latest, record["date"])
            yield record
        # Cursor двигается только когда слайс дочитан целиком. Упадёт запрос —
        # state останется на прошлом слайсе, и этот слайс перечитается.
        if latest:
            city = (stream_slice or {})["city"]
            previous = (self._state.get(city) or {}).get(CURSOR)
            self._state[city] = {CURSOR: max(latest, previous) if previous else latest}


class SourceOpenMeteo(AbstractSource):
    def check_connection(self, logger: logging.Logger, config: Mapping[str, Any]) -> Tuple[bool, Optional[Any]]:
        try:
            start = date.fromisoformat(config["start_date"])
            if config.get("end_date") and date.fromisoformat(config["end_date"]) < start:
                return False, "end_date раньше start_date"
            cities = Cities(config)
            found = list(cities.resolved())
            # Один день по первому городу: проверяем, что и архив отвечает.
            weather = DailyWeather(config, cities)
            probe = {
                "city": found[0]["city"],
                "latitude": found[0]["latitude"],
                "longitude": found[0]["longitude"],
                "start_date": start.isoformat(),
                "end_date": start.isoformat(),
            }
            next(iter(weather.read_records(sync_mode=SyncMode.full_refresh, stream_slice=probe)), None)
            return True, None
        except AirbyteTracedException as error:
            return False, error.message
        except Exception as error:  # check обязан вернуть FAILED, а не трейсбек
            return False, f"{type(error).__name__}: {error}"

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        cities = Cities(config)
        return [cities, DailyWeather(config, cities)]
