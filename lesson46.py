# lesson46.py — День 46: dbt Snapshots (SCD Type 2)
# Запуск: python lesson46.py

import subprocess, os, textwrap
import duckdb

print("=" * 70)
print("ДЕНЬ 46: dbt Snapshots — SCD Type 2")
print("=" * 70)

DBT_PROJECT = "dbt_analytics"

# ── Создаём папку snapshots ───────────────────────────────────────────────
os.makedirs(os.path.join(DBT_PROJECT, "snapshots"), exist_ok=True)

# ══════════════════════════════════════════════════════════════════════
# ЧАСТЬ 1: Подготовка данных — customers с историей изменений
# ══════════════════════════════════════════════════════════════════════
print("\n" + "─" * 50)
print("ЧАСТЬ 1: Подготовка raw данных")
print("─" * 50)

db_path = os.path.join(DBT_PROJECT, "analytics.duckdb")
con = duckdb.connect(db_path)

# Создаём raw_customers если нет
con.execute("""
    CREATE TABLE IF NOT EXISTS raw_customers (
        customer_id   INTEGER PRIMARY KEY,
        email         VARCHAR,
        plan          VARCHAR,
        status        VARCHAR,
        updated_at    TIMESTAMP
    )
""")

# Начальные данные
con.execute("DELETE FROM raw_customers")
con.execute("""
    INSERT INTO raw_customers VALUES
    (1, 'alice@test.com',   'free',    'active',   '2024-01-01 00:00:00'),
    (2, 'bob@test.com',     'premium', 'active',   '2024-01-01 00:00:00'),
    (3, 'charlie@test.com', 'free',    'active',   '2024-01-01 00:00:00'),
    (4, 'diana@test.com',   'basic',   'active',   '2024-02-01 00:00:00'),
    (5, 'eve@test.com',     'premium', 'inactive', '2024-03-01 00:00:00')
""")

count = con.execute("SELECT COUNT(*) FROM raw_customers").fetchone()[0]
print(f"  ✅ raw_customers создана: {count} строк")
con.close()

# ══════════════════════════════════════════════════════════════════════
# ЧАСТЬ 2: Snapshot файлы
# ══════════════════════════════════════════════════════════════════════
print("\n" + "─" * 50)
print("ЧАСТЬ 2: Создание snapshot файлов")
print("─" * 50)

# Snapshot 1: timestamp стратегия (лучший вариант — есть updated_at)
snap_customers = textwrap.dedent("""\
    {% snapshot snap_customers %}

    {{
        config(
            target_schema='snapshots',
            unique_key='customer_id',
            strategy='timestamp',
            updated_at='updated_at',
        )
    }}

    -- Snapshot клиентов: отслеживаем изменения plan и status
    SELECT
        customer_id,
        email,
        plan,
        status,
        updated_at
    FROM {{ source('raw', 'raw_customers') }}

    {% endsnapshot %}
""")

# Snapshot 2: check стратегия (нет updated_at — сравниваем колонки)
snap_orders_status = textwrap.dedent("""\
    {% snapshot snap_orders_status %}

    {{
        config(
            target_schema='snapshots',
            unique_key='order_id',
            strategy='check',
            check_cols=['status'],
        )
    }}

    -- Snapshot статусов заказов: отслеживаем переходы completed/cancelled
    SELECT
        order_id,
        user_id,
        amount,
        status,
        created_at
    FROM {{ source('raw', 'raw_orders') }}

    {% endsnapshot %}
""")

# ── sources.yml — добавляем customers ────────────────────────────────────
sources_updated = textwrap.dedent("""\
    version: 2

    sources:
      - name: raw
        description: "Сырые данные из операционной БД"
        schema: main

        tables:
          - name: raw_orders
            identifier: raw_orders
            description: "Сырые заказы из CRM"
            columns:
              - name: order_id
                data_tests: [not_null, unique]
              - name: user_id
                data_tests: [not_null]
              - name: amount
                data_tests: [not_null]

          - name: raw_customers
            identifier: raw_customers
            description: "Справочник клиентов"
            columns:
              - name: customer_id
                data_tests: [not_null, unique]
              - name: updated_at
                data_tests: [not_null]
""")

# ── dim_customers из snapshot — витрина с историей ────────────────────────
model_dim_customers = textwrap.dedent("""\
    {{ config(materialized='table') }}

    -- Текущее состояние клиентов (только актуальные записи)
    SELECT
        customer_id,
        email,
        plan,
        status,
        dbt_valid_from  AS valid_from,
        dbt_updated_at  AS last_updated

    FROM {{ ref('snap_customers') }}
    WHERE dbt_valid_to IS NULL
""")

# ── dim_customers_history — полная история ────────────────────────────────
model_dim_customers_hist = textwrap.dedent("""\
    {{ config(materialized='table') }}

    -- Полная история изменений клиентов (SCD Type 2)
    SELECT
        customer_id,
        email,
        plan,
        status,
        dbt_valid_from                          AS valid_from,
        COALESCE(dbt_valid_to,
                 '9999-12-31'::TIMESTAMP)       AS valid_to,
        CASE WHEN dbt_valid_to IS NULL
             THEN TRUE ELSE FALSE END           AS is_current,
        DATEDIFF('day',
                 dbt_valid_from,
                 COALESCE(dbt_valid_to,
                          CURRENT_TIMESTAMP))   AS days_in_state

    FROM {{ ref('snap_customers') }}
    ORDER BY customer_id, valid_from
""")

# ── Запись файлов ─────────────────────────────────────────────────────────
files = {
    "snapshots/snap_customers.sql":             snap_customers,
    "snapshots/snap_orders_status.sql":         snap_orders_status,
    "models/staging/sources.yml":               sources_updated,
    "models/marts/dim_customers.sql":           model_dim_customers,
    "models/marts/dim_customers_history.sql":   model_dim_customers_hist,
}

for rel_path, content in files.items():
    full_path = os.path.join(DBT_PROJECT, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ {rel_path}")

# ── Запуск: первый snapshot ───────────────────────────────────────────────
print("\n🔧 dbt snapshot (первый запуск — создаёт историю)...")
r = subprocess.run(["dbt", "snapshot"], cwd=DBT_PROJECT,
                   capture_output=True, text=True)
print("  ✅ snapshot OK" if r.returncode == 0 else f"  ⚠️\n{r.stdout[-600:]}")

# ── Имитируем изменение данных ────────────────────────────────────────────
print("\n⚡ Имитируем изменение: alice free → premium, charlie → inactive...")
con = duckdb.connect(db_path)
con.execute("""
    UPDATE raw_customers
    SET plan='premium', updated_at='2024-06-15 10:00:00'
    WHERE customer_id = 1
""")
con.execute("""
    UPDATE raw_customers
    SET status='inactive', updated_at='2024-06-15 10:00:00'
    WHERE customer_id = 3
""")
con.close()
print("  ✅ Данные обновлены")

# ── Второй snapshot — фиксирует изменения ────────────────────────────────
print("\n🔧 dbt snapshot (второй запуск — фиксирует изменения)...")
r = subprocess.run(["dbt", "snapshot"], cwd=DBT_PROJECT,
                   capture_output=True, text=True)
print("  ✅ snapshot OK" if r.returncode == 0 else f"  ⚠️\n{r.stdout[-600:]}")

# ── Запуск моделей и проверка результата ─────────────────────────────────
print("\n🔧 dbt run dim_customers...")
r = subprocess.run(
    ["dbt", "run", "--select", "dim_customers", "dim_customers_history"],
    cwd=DBT_PROJECT, capture_output=True, text=True
)
print("  ✅ run OK" if r.returncode == 0 else f"  ⚠️\n{r.stdout[-600:]}")

# ── Показываем историю ────────────────────────────────────────────────────
print("\n📊 История изменений клиентов (SCD Type 2):")
con = duckdb.connect(db_path)
try:
    history = con.execute("""
        SELECT customer_id, email, plan, status,
               valid_from, valid_to, is_current, days_in_state
        FROM main.dim_customers_history
        ORDER BY customer_id, valid_from
    """).fetchdf()
    print(history.to_string(index=False))
except Exception as e:
    print(f"  ⚠️ {e}")
con.close()

print("""
📋 ШПАРГАЛКА snapshots:

  Файл: snapshots/snap_xxx.sql
  {% snapshot snap_name %}
  {{ config(
      target_schema='snapshots',
      unique_key='id',
      strategy='timestamp',   -- или 'check'
      updated_at='updated_at' -- для timestamp
      check_cols=['col1']     -- для check
  ) }}
  SELECT ... FROM {{ source(...) }}
  {% endsnapshot %}

  Запуск:
    dbt snapshot              -- зафиксировать текущее состояние
    dbt snapshot --full-refresh -- пересоздать с нуля

  Служебные колонки:
    dbt_scd_id       -- суррогатный ключ строки
    dbt_valid_from   -- с какого момента актуальна
    dbt_valid_to     -- до какого (NULL = текущая)
    dbt_is_current   -- TRUE если текущая запись
    dbt_updated_at   -- когда snapshot сработал
""")