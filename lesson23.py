"""
Den 23: dbt Testing
Schema tests, generic tests, singular tests — 5+ тестов качества
"""

from pathlib import Path

print("=" * 70)
print(" " * 12 + "DEN 23: DBT TESTING")
print("=" * 70)

project_path = Path('dbt_analytics')

if not project_path.exists():
    print("Сначала запусти lesson17_dbt_basics.py!")
    exit(1)


# ========================================
# ЧАСТЬ 1: SCHEMA TESTS
# ========================================

print("\n" + "=" * 70)
print("ЧАСТЬ 1: Schema Tests — встроенные тесты")
print("=" * 70)

schema_yml = """
version: 2

sources:
  - name: raw_data
    description: "Сырые данные интернет-магазина"
    tables:
      - name: raw_users
        description: "Пользователи из CRM"
        columns:
          - name: user_id
            tests:
              - unique
              - not_null
          - name: email
            tests:
              - not_null

      - name: raw_orders
        description: "Заказы"
        columns:
          - name: order_id
            tests:
              - unique
              - not_null
          - name: status
            tests:
              - accepted_values:
                  values: ['completed', 'pending', 'cancelled']

models:
  - name: stg_users
    description: "Staging: очищенные пользователи"
    columns:
      - name: user_id
        description: "Уникальный ID пользователя"
        tests:
          - unique
          - not_null
      - name: email
        description: "Email пользователя"
        tests:
          - not_null

  - name: stg_orders
    description: "Staging: completed заказы"
    columns:
      - name: order_id
        description: "Уникальный ID заказа"
        tests:
          - unique
          - not_null
      - name: user_id
        description: "FK to stg_users"
        tests:
          - not_null
          - relationships:
              to: ref('stg_users')
              field: user_id
      - name: status
        tests:
          - accepted_values:
              values: ['completed']
      - name: amount
        tests:
          - not_null

  - name: fct_orders_enriched
    description: "Fact table с обогащёнными данными"
    columns:
      - name: order_id
        tests:
          - unique
          - not_null
      - name: revenue_tier
        tests:
          - accepted_values:
              values: ['zero', 'low', 'medium', 'high', 'vip']

  - name: dim_customers
    description: "Dimension: агрегация по клиентам"
    columns:
      - name: user_id
        tests:
          - unique
          - not_null
      - name: total_orders
        tests:
          - not_null
      - name: total_spent
        tests:
          - not_null
"""

with open(project_path / 'models' / 'schema.yml', 'w', encoding='utf-8') as f:
    f.write(schema_yml.strip())

print("Создан schema.yml с 4 встроенными тестами:")
print("  - unique          : нет дублей")
print("  - not_null        : нет NULL")
print("  - accepted_values : только из списка")
print("  - relationships   : FK существует в родительской таблице")


# ========================================
# ЧАСТЬ 2: SEVERITY
# ========================================

print("\n" + "=" * 70)
print("ЧАСТЬ 2: Severity — warn vs error")
print("=" * 70)

severity_schema = """
version: 2

models:
  - name: stg_orders
    columns:
      - name: amount
        tests:
          - not_null:
              severity: error

      - name: user_id
        tests:
          - relationships:
              to: ref('stg_users')
              field: user_id
              severity: warn
              config:
                warn_if: ">5"
                error_if: ">50"
"""

path = project_path / 'models' / 'staging' / 'schema_severity.yml'
with open(path, 'w', encoding='utf-8') as f:
    f.write(severity_schema.strip())

print("Создан schema_severity.yml:")
print("  severity: error  -> тест упал -> dbt остановится")
print("  severity: warn   -> тест упал -> dbt продолжает, выдаёт WARNING")
print("  warn_if / error_if -> пороговые значения нарушений")


# ========================================
# ЧАСТЬ 3: GENERIC TESTS
# ========================================

print("\n" + "=" * 70)
print("ЧАСТЬ 3: Generic Tests — переиспользуемые правила")
print("=" * 70)

(project_path / 'macros' / 'tests').mkdir(parents=True, exist_ok=True)

generic_tests = """
-- macros/tests/generic_tests.sql
-- Переиспользуемые тесты (вызываются из schema.yml)


-- TEST 5: Значения должны быть > 0
{% test positive_values(model, column_name) %}

    SELECT {{ column_name }}
    FROM {{ model }}
    WHERE {{ column_name }} <= 0
      AND {{ column_name }} IS NOT NULL

{% endtest %}


-- Тест: нет пробелов в начале/конце строки
{% test no_whitespace(model, column_name) %}

    SELECT {{ column_name }}
    FROM {{ model }}
    WHERE {{ column_name }} != TRIM({{ column_name }})
      AND {{ column_name }} IS NOT NULL

{% endtest %}


-- Тест: дата не в будущем
{% test not_in_future(model, column_name) %}

    SELECT {{ column_name }}
    FROM {{ model }}
    WHERE {{ column_name }} > CURRENT_DATE

{% endtest %}


-- Тест: значение в заданном диапазоне
{% test in_range(model, column_name, min_value, max_value) %}

    SELECT {{ column_name }}
    FROM {{ model }}
    WHERE {{ column_name }} < {{ min_value }}
       OR {{ column_name }} > {{ max_value }}

{% endtest %}
"""

with open(project_path / 'macros' / 'tests' / 'generic_tests.sql', 'w', encoding='utf-8') as f:
    f.write(generic_tests.strip())

print("Созданы generic tests в macros/tests/generic_tests.sql:")
print("  - positive_values(column)      : значения > 0")
print("  - no_whitespace(column)        : нет пробелов")
print("  - not_in_future(column)        : дата не в будущем")
print("  - in_range(column, min, max)   : значение в диапазоне")

generic_usage_schema = """
version: 2

models:
  - name: stg_orders
    columns:
      - name: amount
        tests:
          - positive_values
          - in_range:
              min_value: 1
              max_value: 100000

      - name: created_at
        tests:
          - not_in_future

  - name: stg_users
    columns:
      - name: user_name
        tests:
          - no_whitespace
"""

path = project_path / 'models' / 'staging' / 'schema_generic.yml'
with open(path, 'w', encoding='utf-8') as f:
    f.write(generic_usage_schema.strip())

print("Создан schema_generic.yml — применение generic tests")


# ========================================
# ЧАСТЬ 4: SINGULAR TESTS
# ========================================

print("\n" + "=" * 70)
print("ЧАСТЬ 4: Singular Tests — бизнес-правила")
print("=" * 70)

(project_path / 'tests').mkdir(exist_ok=True)

no_orphans_test = """
-- tests/test_no_orphan_orders.sql
-- Бизнес-правило: каждый заказ должен иметь существующего пользователя
-- Orphan = заказ без клиента

SELECT
    o.order_id,
    o.user_id
FROM {{ ref('stg_orders') }} o
LEFT JOIN {{ ref('stg_users') }} u ON o.user_id = u.user_id
WHERE u.user_id IS NULL
"""

with open(project_path / 'tests' / 'test_no_orphan_orders.sql', 'w', encoding='utf-8') as f:
    f.write(no_orphans_test.strip())

revenue_consistency_test = """
-- tests/test_revenue_consistency.sql
-- Бизнес-правило: dim_customers.total_spent >= 0 всегда
-- Отрицательный LTV — признак ошибки в данных

SELECT
    user_id,
    total_spent
FROM {{ ref('dim_customers') }}
WHERE total_spent < 0
"""

with open(project_path / 'tests' / 'test_revenue_consistency.sql', 'w', encoding='utf-8') as f:
    f.write(revenue_consistency_test.strip())

no_future_orders_test = """
-- tests/test_no_future_orders.sql
-- Бизнес-правило: заказы не могут быть в будущем
-- Если есть — ошибка в ETL или тестовые данные попали в prod

SELECT
    order_id,
    created_at
FROM {{ ref('stg_orders') }}
WHERE created_at::DATE > CURRENT_DATE
"""

with open(project_path / 'tests' / 'test_no_future_orders.sql', 'w', encoding='utf-8') as f:
    f.write(no_future_orders_test.strip())

tier_logic_test = """
-- tests/test_tier_logic_consistency.sql
-- Бизнес-правило: revenue_tier должен соответствовать amount
-- VIP заказы не могут иметь amount < 20000

SELECT
    order_id,
    amount,
    revenue_tier
FROM {{ ref('fct_orders_enriched') }}
WHERE (revenue_tier = 'vip' AND amount < 20000)
   OR (revenue_tier = 'low' AND amount >= 5000)
"""

with open(project_path / 'tests' / 'test_tier_logic_consistency.sql', 'w', encoding='utf-8') as f:
    f.write(tier_logic_test.strip())

print("Созданы singular tests в tests/:")
print("  - test_no_orphan_orders.sql       : заказы без клиентов")
print("  - test_revenue_consistency.sql    : total_spent >= 0")
print("  - test_no_future_orders.sql       : нет дат в будущем")
print("  - test_tier_logic_consistency.sql : tier sootvetstvuyet amount")


# ========================================
# ЧАСТЬ 5: ИТОГ
# ========================================

print("\n" + "=" * 70)
print("ЧАСТЬ 5: Итог — 10 тестов качества данных")
print("=" * 70)

print("""
ПОЛНЫЙ СПИСОК ТЕСТОВ:

Schema Tests (из schema.yml):
  TEST 1: unique          : stg_orders.order_id
  TEST 2: not_null        : stg_orders.user_id, amount
  TEST 3: accepted_values : stg_orders.status = ['completed']
  TEST 4: relationships   : stg_orders.user_id -> stg_users.user_id

Generic Tests (из macros/tests/):
  TEST 5: positive_values : stg_orders.amount > 0
  TEST 6: not_in_future   : stg_orders.created_at <= CURRENT_DATE
  TEST 7: no_whitespace   : stg_users.user_name

Singular Tests (из tests/):
  TEST 8:  test_no_orphan_orders
  TEST 9:  test_revenue_consistency
  TEST 10: test_tier_logic_consistency

ИТОГО: 10 тестов (требовалось 5) OK
""")


# ========================================
# ЧАСТЬ 6: КОМАНДЫ
# ========================================

print("\n" + "=" * 70)
print("ЧАСТЬ 6: Команды для запуска тестов")
print("=" * 70)

print("""
Komandy dbt test:

Запустить ВСЕ тесты:
   dbt test

Тесты только одной модели:
   dbt test --select stg_orders

Тесты источников (sources):
   dbt test --select source:raw_data

Сохранить провалившиеся строки в БД:
   dbt test --store-failures

Запустить модели + тесты за один раз:
   dbt build

Ожидаемый результат:
   Running 10 tests...
   PASS unique_stg_orders_order_id ............. [PASS in 0.08s]
   PASS not_null_stg_orders_user_id ............ [PASS in 0.06s]
   PASS relationships_stg_orders_user_id ....... [PASS in 0.12s]
   PASS accepted_values_stg_orders_status ...... [PASS in 0.07s]
   PASS positive_values_stg_orders_amount ...... [PASS in 0.09s]
   PASS not_in_future_stg_orders_created_at .... [PASS in 0.07s]
   PASS no_whitespace_stg_users_user_name ...... [PASS in 0.08s]
   PASS test_no_orphan_orders .................. [PASS in 0.11s]
   PASS test_revenue_consistency ............... [PASS in 0.09s]
   PASS test_tier_logic_consistency ............ [PASS in 0.10s]
   Finished running 10 tests. 10 passed, 0 failed.

Если тест упал:
   dbt test --select stg_orders --store-failures
   -> смотри таблицу failures в БД: какие строки нарушают правило
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("ДЕНЬ 23 ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Ты создал систему тестирования данных:
1. Schema tests      : unique, not_null, accepted_values, relationships
2. Severity          : error (критично) vs warn (предупреждение)
3. Generic tests     : positive_values, not_in_future, no_whitespace, in_range
4. Singular tests    : 4 biznes-pravila v tests/
5. 10 testov         : polnoye pokrytiye proyekta

Proyekt: {project_path.absolute()}

KOMANDY:
cd dbt_analytics
dbt build          # run + test за один шаг
dbt docs serve     # Posmotri graf testov v brauzere

Следующий день: День 24 — BI основы (Power BI / Tableau)
""")