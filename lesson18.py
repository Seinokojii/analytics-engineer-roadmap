"""
День 18: dbt Advanced
Макросы, инкрементальные модели, документация
"""

from pathlib import Path

print("=" * 70)
print(" " * 12 + "🔧 ДЕНЬ 18: DBT ADVANCED")
print("=" * 70)

project_path = Path('dbt_analytics')

if not project_path.exists():
    print("❌ Сначала запусти lesson17_dbt_basics.py!")
    exit(1)

# ========================================
# ЧАСТЬ 1: MACROS (ПЕРЕИСПОЛЬЗУЕМЫЙ КОД)
# ========================================

print("\n" + "=" * 70)
print("🔧 ЧАСТЬ 1: Macros (функции SQL)")
print("=" * 70)

(project_path / 'macros').mkdir(exist_ok=True)

# Макрос: Безопасное деление
safe_divide_macro = """
{% macro safe_divide(numerator, denominator) %}
    CASE 
        WHEN {{ denominator }} = 0 THEN 0
        ELSE {{ numerator }} / {{ denominator }}
    END
{% endmacro %}
"""

with open(project_path / 'macros' / 'safe_divide.sql', 'w', encoding='utf-8') as f:
    f.write(safe_divide_macro.strip())

# Макрос: Генерация дат
generate_date_spine_macro = """
{% macro generate_date_spine(start_date, end_date) %}
WITH RECURSIVE date_spine AS (
    SELECT '{{ start_date }}'::DATE AS date
    UNION ALL
    SELECT date + INTERVAL '1 day'
    FROM date_spine
    WHERE date < '{{ end_date }}'::DATE
)
SELECT date FROM date_spine
{% endmacro %}
"""

with open(project_path / 'macros' / 'generate_date_spine.sql', 'w', encoding='utf-8') as f:
    f.write(generate_date_spine_macro.strip())

print("✅ Созданы macros:")
print("  - safe_divide.sql (безопасное деление)")
print("  - generate_date_spine.sql (генерация дат)")

# Использование макроса
metrics_model = """
-- Использование макроса safe_divide
SELECT 
    user_id,
    total_orders,
    total_spent,
    {{ safe_divide('total_spent', 'total_orders') }} AS avg_order_value
FROM {{ ref('dim_customers') }}
"""

with open(project_path / 'models' / 'marts' / 'metrics_customers.sql', 'w', encoding='utf-8') as f:
    f.write(metrics_model.strip())

print("✅ Создана модель с макросом: metrics_customers.sql")


# ========================================
# ЧАСТЬ 2: INCREMENTAL MODELS
# ========================================

print("\n" + "=" * 70)
print("📈 ЧАСТЬ 2: Incremental Models (обновление данных)")
print("=" * 70)

incremental_orders = """
{{
    config(
        materialized='incremental',
        unique_key='order_id'
    )
}}

SELECT 
    order_id,
    user_id,
    amount,
    created_at
FROM {{ ref('stg_orders') }}

{% if is_incremental() %}
    -- Только новые записи с момента последнего запуска
    WHERE created_at > (SELECT MAX(created_at) FROM {{ this }})
{% endif %}
"""

with open(project_path / 'models' / 'marts' / 'fct_orders_incremental.sql', 'w', encoding='utf-8') as f:
    f.write(incremental_orders.strip())

print("✅ Создана incremental модель: fct_orders_incremental.sql")
print("""
💡 Как работает:
1. Первый запуск: загружает ВСЕ данные
2. Следующие запуски: только новые записи (WHERE created_at > MAX)
3. Экономия времени: ~10x быстрее на больших таблицах
""")


# ========================================
# ЧАСТЬ 3: DOCUMENTATION
# ========================================

print("\n" + "=" * 70)
print("📚 ЧАСТЬ 3: Документация")
print("=" * 70)

# Обновленный schema.yml с описаниями (БЕЗ символа рубля!)
detailed_schema = """
version: 2

models:
  - name: dim_customers
    description: |
      # Customer Dimension Table
      
      Агрегированная информация о клиентах.
      
      ## Business Rules:
      - Один клиент = одна строка
      - total_orders = количество COMPLETED заказов
      - total_spent считается только по completed
      
      ## Обновление:
      Запускается каждый день в 2:00 UTC
      
      ## SLA:
      Данные свежие на момент T-1 (вчерашний день)
      
    columns:
      - name: user_id
        description: "Уникальный ID клиента из системы"
        tests:
          - unique
          - not_null
      
      - name: user_name
        description: "Имя пользователя (lowercase)"
      
      - name: total_orders
        description: |
          **Общее количество заказов**
          
          Считаются только completed заказы.
          Cancelled и pending НЕ учитываются.
        tests:
          - not_null
      
      - name: total_spent
        description: |
          **Общая сумма покупок (руб)**
          
          LTV (Lifetime Value) клиента.
          Используется для сегментации.
        tests:
          - not_null
      
      - name: avg_order_value
        description: "Средний чек = total_spent / total_orders"
      
      - name: last_order_date
        description: |
          **Дата последнего заказа**
          
          Используется для расчета Recency в RFM анализе.

  - name: fct_orders
    description: "Fact table со всеми completed заказами"
    columns:
      - name: order_id
        description: "PK таблицы"
        tests:
          - unique
          - not_null
      - name: user_id
        description: "FK к dim_customers"
        tests:
          - not_null

sources:
  - name: raw
    description: "Сырые данные из operational БД"
    tables:
      - name: raw_users
        description: "Snapshot пользователей"
      - name: raw_orders
        description: "Все заказы (любой статус)"
"""

with open(project_path / 'models' / 'schema_detailed.yml', 'w', encoding='utf-8') as f:
    f.write(detailed_schema.strip())

print("✅ Создана расширенная документация: schema_detailed.yml")


# ========================================
# ЧАСТЬ 4: PRE/POST HOOKS
# ========================================

print("\n" + "=" * 70)
print("🪝 ЧАСТЬ 4: Hooks (действия до/после модели)")
print("=" * 70)

model_with_hooks = """
{{
    config(
        materialized='table',
        pre_hook=[
            "CREATE TABLE IF NOT EXISTS audit_log (model_name TEXT, run_at TIMESTAMP)",
            "INSERT INTO audit_log VALUES ('{{ this.name }}', CURRENT_TIMESTAMP)"
        ],
        post_hook=[
            "ANALYZE {{ this }}",
            "CREATE INDEX IF NOT EXISTS idx_{{ this.name }}_user_id ON {{ this }} (user_id)"
        ]
    )
}}

SELECT 
    user_id,
    COUNT(*) AS order_count,
    SUM(amount) AS total_revenue
FROM {{ ref('fct_orders') }}
GROUP BY user_id
"""

with open(project_path / 'models' / 'marts' / 'agg_users.sql', 'w', encoding='utf-8') as f:
    f.write(model_with_hooks.strip())

print("✅ Создана модель с hooks: agg_users.sql")
print("""
💡 Hooks позволяют:
- pre_hook: Логирование, создание temp таблиц
- post_hook: Создание индексов, ANALYZE, GRANT permissions
""")


# ========================================
# ЧАСТЬ 5: CUSTOM TESTS
# ========================================

print("\n" + "=" * 70)
print("🧪 ЧАСТЬ 5: Custom Tests")
print("=" * 70)

(project_path / 'tests').mkdir(exist_ok=True)

# Кастомный тест: все заказы в будущем
future_orders_test = """
-- tests/no_future_orders.sql
-- Проверка: НЕТ заказов в будущем

SELECT *
FROM {{ ref('fct_orders') }}
WHERE order_date > CURRENT_DATE
"""

with open(project_path / 'tests' / 'no_future_orders.sql', 'w', encoding='utf-8') as f:
    f.write(future_orders_test.strip())

# Кастомный тест: total_spent >= 0
assert_positive_spent = """
-- tests/assert_positive_total_spent.sql
-- Проверка: total_spent не может быть отрицательным

SELECT *
FROM {{ ref('dim_customers') }}
WHERE total_spent < 0
"""

with open(project_path / 'tests' / 'assert_positive_total_spent.sql', 'w', encoding='utf-8') as f:
    f.write(assert_positive_spent.strip())

print("✅ Созданы custom tests:")
print("  - no_future_orders.sql")
print("  - assert_positive_total_spent.sql")


# ========================================
# ЧАСТЬ 6: SOURCES
# ========================================

print("\n" + "=" * 70)
print("📥 ЧАСТЬ 6: Sources (внешние таблицы)")
print("=" * 70)

sources_yml = """
version: 2

sources:
  - name: raw_data
    description: "Сырые данные из operational database"
    database: analytics
    schema: main
    
    tables:
      - name: raw_users
        description: "Таблица пользователей"
        freshness:
          warn_after: {count: 12, period: hour}
          error_after: {count: 24, period: hour}
        loaded_at_field: created_at
        
        columns:
          - name: user_id
            description: "Primary key"
            tests:
              - unique
              - not_null
      
      - name: raw_orders
        description: "Таблица заказов"
        freshness:
          warn_after: {count: 6, period: hour}
        loaded_at_field: created_at
"""

with open(project_path / 'models' / 'sources.yml', 'w', encoding='utf-8') as f:
    f.write(sources_yml.strip())

print("✅ Создан sources.yml")
print("""
💡 Sources позволяют:
- Отслеживать freshness данных
- Тестировать сырые данные
- Документировать external tables
""")


# ========================================
# ЧАСТЬ 7: ANALYSIS (AD-HOC QUERIES)
# ========================================

print("\n" + "=" * 70)
print("📊 ЧАСТЬ 7: Analysis (ad-hoc запросы)")
print("=" * 70)

(project_path / 'analyses').mkdir(exist_ok=True)

top_customers_analysis = """
-- analyses/top_customers_2024.sql
-- Топ-10 клиентов за 2024 год

WITH orders_2024 AS (
    SELECT 
        user_id,
        SUM(amount) AS revenue_2024
    FROM {{ ref('fct_orders') }}
    WHERE EXTRACT(YEAR FROM order_date) = 2024
    GROUP BY user_id
)
SELECT 
    c.user_name,
    c.city,
    o.revenue_2024,
    c.total_orders
FROM orders_2024 o
JOIN {{ ref('dim_customers') }} c ON o.user_id = c.user_id
ORDER BY o.revenue_2024 DESC
LIMIT 10
"""

with open(project_path / 'analyses' / 'top_customers_2024.sql', 'w', encoding='utf-8') as f:
    f.write(top_customers_analysis.strip())

print("✅ Создан analysis: top_customers_2024.sql")
print("""
💡 Analysis vs Models:
- Analysis: Не материализуется, только для SQL IDE
- Models: Материализуется как таблица/view
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 18 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил dbt advanced:
1. ✅ Macros - переиспользуемый SQL код
2. ✅ Incremental models - обновление данных (10x быстрее)
3. ✅ Документация - описания моделей/колонок
4. ✅ Hooks - pre/post обработка
5. ✅ Custom tests - бизнес-правила
6. ✅ Sources - external tables с freshness
7. ✅ Analysis - ad-hoc запросы

КОМАНДЫ ДЛЯ ЗАПУСКА:
cd dbt_analytics
dbt run              # Запустить все модели
dbt test             # Все тесты
dbt docs generate    # Сгенерировать документацию
dbt docs serve       # Открыть в браузере (localhost:8080)

Следующий день: День 19 - Automation & Scheduling
""")