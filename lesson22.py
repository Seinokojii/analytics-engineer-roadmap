"""
День 22: dbt — Jinja, Macros, Incremental Models
Продвинутые возможности dbt для production-ready проектов
"""

from pathlib import Path

print("=" * 70)
print(" " * 8 + "🔧 ДЕНЬ 22: DBT JINJA, MACROS, INCREMENTAL")
print("=" * 70)

project_path = Path('dbt_analytics')

if not project_path.exists():
    print("❌ Сначала запусти lesson17_dbt_basics.py!")
    exit(1)


# ========================================
# ЧАСТЬ 1: JINJA — ПЕРЕМЕННЫЕ И УСЛОВИЯ
# ========================================

print("\n" + "=" * 70)
print("1️⃣  ЧАСТЬ 1: Jinja — переменные и условия")
print("=" * 70)

stg_orders_jinja = """
-- models/staging/stg_orders_v2.sql
-- Jinja-переменные для гибкой настройки

{{ config(materialized='view') }}

{% set completed_status = 'completed' %}
{% set min_amount = 0 %}

SELECT
    order_id,
    user_id,
    amount,
    status,
    created_at::TIMESTAMP AS created_at,

    -- Jinja if/else прямо в SQL
    CASE
        WHEN status = '{{ completed_status }}' THEN true
        ELSE false
    END AS is_completed,

    -- Метка окружения
    '{{ env_var("DBT_ENV", "dev") }}' AS env_label

FROM {{ ref('raw_orders') }}
WHERE amount > {{ min_amount }}
  AND order_id IS NOT NULL
"""

path = project_path / 'models' / 'staging' / 'stg_orders_v2.sql'
with open(path, 'w') as f:
    f.write(stg_orders_jinja.strip())

print("✅ Создана модель с Jinja-переменными: stg_orders_v2.sql")


# ========================================
# ЧАСТЬ 2: JINJA FOR-LOOP
# ========================================

print("\n" + "=" * 70)
print("2️⃣  ЧАСТЬ 2: Jinja for-loop — динамические колонки")
print("=" * 70)

monthly_pivot = """
-- models/marts/monthly_revenue_pivot.sql
-- Jinja for-loop: генерирует 12 колонок автоматически
-- Вместо ручного написания 12 одинаковых CASE WHEN

{{ config(materialized='table') }}

{% set months = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] %}

SELECT
    user_id,

    {% for month in months %}
    SUM(CASE
        WHEN EXTRACT(MONTH FROM created_at) = {{ month }}
        THEN amount
        ELSE 0
    END) AS revenue_month_{{ month }}
    {% if not loop.last %},{% endif %}
    {% endfor %}

FROM {{ ref('stg_orders') }}
WHERE status = 'completed'
GROUP BY user_id
ORDER BY user_id
"""

(project_path / 'models' / 'marts').mkdir(parents=True, exist_ok=True)
path = project_path / 'models' / 'marts' / 'monthly_revenue_pivot.sql'
with open(path, 'w') as f:
    f.write(monthly_pivot.strip())

print("✅ Создана pivot-модель: monthly_revenue_pivot.sql")
print("   dbt сгенерирует 12 колонок: revenue_month_1 ... revenue_month_12")
print("   Добавить месяц — изменить список в ОДНОМ месте")


# ========================================
# ЧАСТЬ 3: MACROS
# ========================================

print("\n" + "=" * 70)
print("3️⃣  ЧАСТЬ 3: Macros — переиспользуемые функции")
print("=" * 70)

(project_path / 'macros').mkdir(exist_ok=True)

# Macro 1: Классификация тиров
revenue_tier_macro = """
-- macros/revenue_tier.sql

-- Классифицирует сумму по уровням
{% macro classify_revenue_tier(column_name) %}
    CASE
        WHEN {{ column_name }} = 0        THEN 'zero'
        WHEN {{ column_name }} < 1000     THEN 'low'
        WHEN {{ column_name }} < 5000     THEN 'medium'
        WHEN {{ column_name }} < 20000    THEN 'high'
        ELSE                                   'vip'
    END
{% endmacro %}


-- Безопасное деление (без ZeroDivisionError)
{% macro safe_divide(numerator, denominator) %}
    CASE
        WHEN {{ denominator }} = 0 OR {{ denominator }} IS NULL THEN NULL
        ELSE ROUND(CAST({{ numerator }} AS FLOAT) / {{ denominator }}, 2)
    END
{% endmacro %}


-- Стандартизация статусов
{% macro normalize_status(column_name) %}
    CASE UPPER(TRIM({{ column_name }}))
        WHEN 'COMPLETED' THEN 'completed'
        WHEN 'CANCELLED' THEN 'cancelled'
        WHEN 'PENDING'   THEN 'pending'
        ELSE                  'unknown'
    END
{% endmacro %}
"""

with open(project_path / 'macros' / 'revenue_tier.sql', 'w') as f:
    f.write(revenue_tier_macro.strip())

print("✅ Созданы macros в macros/revenue_tier.sql:")
print("   - classify_revenue_tier(column)  → 'zero'/'low'/'medium'/'high'/'vip'")
print("   - safe_divide(numerator, denom)  → NULL вместо ZeroDivisionError")
print("   - normalize_status(column)       → стандартизация строк")

# Модель, использующая все macros
fct_orders_enriched = """
-- models/marts/fct_orders_enriched.sql
-- Использует все macros — чистый, переиспользуемый код

{{ config(materialized='table') }}

SELECT
    o.order_id,
    o.user_id,
    u.user_name,
    u.city,
    o.amount,
    o.created_at AS order_date,

    -- Вызов macro вместо копирования CASE WHEN
    {{ classify_revenue_tier('o.amount') }}    AS revenue_tier,
    {{ normalize_status('o.status') }}         AS normalized_status,
    {{ safe_divide('o.amount', '100') }}       AS amount_hundreds,

    EXTRACT(MONTH   FROM o.created_at)         AS order_month,
    EXTRACT(QUARTER FROM o.created_at)         AS order_quarter,
    EXTRACT(YEAR    FROM o.created_at)         AS order_year

FROM {{ ref('stg_orders') }} o
LEFT JOIN {{ ref('stg_users') }} u ON o.user_id = u.user_id
"""

path = project_path / 'models' / 'marts' / 'fct_orders_enriched.sql'
with open(path, 'w') as f:
    f.write(fct_orders_enriched.strip())

print("✅ Создана модель с macros: fct_orders_enriched.sql")


# ========================================
# ЧАСТЬ 4: INCREMENTAL MODELS
# ========================================

print("\n" + "=" * 70)
print("4️⃣  ЧАСТЬ 4: Incremental Models")
print("=" * 70)

fct_incremental = """
-- models/marts/fct_orders_incremental.sql
-- Incremental: при повторных запусках добавляет ТОЛЬКО новые строки

{{
    config(
        materialized    = 'incremental',
        unique_key      = 'order_id',
        on_schema_change = 'sync_all_columns'
    )
}}

SELECT
    order_id,
    user_id,
    amount,
    status,
    {{ classify_revenue_tier('amount') }} AS revenue_tier,
    created_at,
    CURRENT_TIMESTAMP                     AS loaded_at

FROM {{ ref('stg_orders') }}

{% if is_incremental() %}
    -- Этот блок добавляется ТОЛЬКО при incremental-запуске (не при первом)
    -- {{ this }} = текущая таблица в БД
    WHERE created_at > (
        SELECT MAX(created_at)
        FROM {{ this }}
    )
{% endif %}
"""

path = project_path / 'models' / 'marts' / 'fct_orders_incremental.sql'
with open(path, 'w') as f:
    f.write(fct_incremental.strip())

print("✅ Создана incremental модель: fct_orders_incremental.sql")
print("""
   💡 Как работает:
   1й запуск:         SELECT все строки (500 строк, ~3 сек)
   2й запуск:         SELECT WHERE created_at > MAX → только новые
   --full-refresh:    Пересчитать всё с нуля (принудительно)
   unique_key:        При дублях — обновляет строку, не добавляет новую
""")


# ========================================
# ЧАСТЬ 5: dbt_project.yml — ГЛОБАЛЬНЫЙ КОНФИГ
# ========================================

print("\n" + "=" * 70)
print("5️⃣  ЧАСТЬ 5: dbt_project.yml — глобальная конфигурация")
print("=" * 70)

dbt_project_yml = """
name: 'analytics_project'
version: '1.0.0'
config-version: 2

profile: 'analytics'

model-paths:  ["models"]
macro-paths:  ["macros"]
seed-paths:   ["data"]
test-paths:   ["tests"]

models:
  analytics_project:

    # Все staging-модели = view (быстро, не занимает место)
    staging:
      +materialized: view
      +schema: staging

    # Все marts-модели = table (быстрые запросы)
    marts:
      +materialized: table
      +schema: marts

      # Исключение: incremental для facts
      fct_orders_incremental:
        +materialized: incremental
"""

with open(project_path / 'dbt_project.yml', 'w') as f:
    f.write(dbt_project_yml.strip())

print("✅ Обновлён dbt_project.yml:")
print("   staging/* → materialized: view")
print("   marts/*   → materialized: table")
print("   fct_orders_incremental → materialized: incremental")


# ========================================
# ЧАСТЬ 6: КОМАНДЫ ЗАПУСКА
# ========================================

print("\n" + "=" * 70)
print("6️⃣  ЧАСТЬ 6: Команды для запуска")
print("=" * 70)

print("""
📝 Последовательность команд:

1. Перейди в папку проекта:
   cd dbt_analytics

2. Загрузи seed данные:
   dbt seed

3. Запусти все модели:
   dbt run

4. Запусти ТОЛЬКО incremental модель:
   dbt run --select fct_orders_incremental

5. Принудительный пересчёт incremental с нуля:
   dbt run --select fct_orders_incremental --full-refresh

6. Запусти тесты:
   dbt test

7. Просмотри граф зависимостей:
   dbt docs generate
   dbt docs serve

🔍 Полезные команды:
   dbt run --select +fct_orders_enriched   # модель + все upstream
   dbt run --select staging.*              # только staging папка
   dbt run --select tag:daily              # модели с тегом daily
   dbt compile                             # показать итоговый SQL без запуска
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 22 ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Ты создал:
1. ✅ Jinja-переменные и условия (stg_orders_v2.sql)
2. ✅ Jinja for-loop → 12 колонок из 3 строк (monthly_revenue_pivot.sql)
3. ✅ Macros: classify_revenue_tier, safe_divide, normalize_status
4. ✅ Модель с macros (fct_orders_enriched.sql)
5. ✅ Incremental model с unique_key (fct_orders_incremental.sql)
6. ✅ Глобальный dbt_project.yml

Проект: {project_path.absolute()}

СЛЕДУЮЩИЙ ШАГ:
cd dbt_analytics && dbt seed && dbt run && dbt test

Следующий день: День 23 — dbt Testing (schema tests, custom tests)
""")