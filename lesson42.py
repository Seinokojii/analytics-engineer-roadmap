# lesson42.py — День 42: dbt Packages (dbt-utils, dbt-expectations)
# Запуск: python lesson42.py

import subprocess, os, textwrap

print("=" * 70)
print("ДЕНЬ 42: dbt Packages — dbt-utils и dbt-expectations")
print("=" * 70)

DBT_PROJECT = "dbt_analytics"
os.makedirs(os.path.join(DBT_PROJECT, "models", "marts"), exist_ok=True)

packages_yml = textwrap.dedent("""\
    packages:
      - package: dbt-labs/dbt_utils
        version: [">=1.0.0", "<2.0.0"]
      - package: metaplane/dbt_expectations
        version: [">=0.10.0", "<1.0.0"]
""")

with open(os.path.join(DBT_PROJECT, "packages.yml"), "w", encoding="utf-8") as f:
    f.write(packages_yml)
print("✅ packages.yml создан")

print("\n📦 dbt deps — установка пакетов...")
r = subprocess.run(["dbt", "deps"], cwd=DBT_PROJECT, capture_output=True, text=True)
if r.returncode == 0:
    print("  ✅ dbt deps OK")
else:
    print(f"  ⚠️\n{r.stdout}\n{r.stderr}")

model_surrogate = textwrap.dedent("""\
    {{ config(materialized='table') }}
    SELECT
        {{ dbt_utils.generate_surrogate_key(['order_id', 'user_id']) }} AS order_sk,
        order_id,
        user_id     AS customer_id,
        amount      AS total_amount,
        created_at  AS order_date,
        status
    FROM {{ ref('stg_orders') }}
""")

model_star = textwrap.dedent("""\
    {{ config(materialized='view') }}
    SELECT
        {{ dbt_utils.star(
            from=ref('fct_orders_enriched'),
            except=['activity_status', 'days_since_order']
        ) }}
    FROM {{ ref('fct_orders_enriched') }}
    WHERE revenue_tier IN ('high', 'vip')
""")

model_dim_date = textwrap.dedent("""\
    {{ config(materialized='table') }}
    WITH date_spine AS (
        {{ dbt_utils.date_spine(
            datepart='day',
            start_date="cast('2023-01-01' as date)",
            end_date="cast('2025-12-31' as date)"
        ) }}
    )
    SELECT
        date_day                                            AS date_id,
        date_day,
        EXTRACT(YEAR    FROM date_day)::INT                 AS year,
        EXTRACT(MONTH   FROM date_day)::INT                 AS month,
        EXTRACT(DAY     FROM date_day)::INT                 AS day,
        EXTRACT(QUARTER FROM date_day)::INT                 AS quarter,
        DAYOFWEEK(date_day)                                 AS day_of_week,
        DAYNAME(date_day)                                   AS day_name,
        MONTHNAME(date_day)                                 AS month_name,
        CASE WHEN DAYOFWEEK(date_day) IN (1, 7)
             THEN TRUE ELSE FALSE END                       AS is_weekend,
        STRFTIME(date_day, '%Y-%m')                         AS year_month,
        STRFTIME(date_day, '%Y') || '-Q' ||
            CAST(EXTRACT(QUARTER FROM date_day) AS VARCHAR) AS year_quarter
    FROM date_spine
    ORDER BY date_day
""")

schema_yml = textwrap.dedent("""\
    version: 2
    models:
      - name: fct_orders_enriched
        description: "Обогащённые заказы с тирами и статусами"
        columns:
          - name: order_id
            data_tests:
              - not_null
              - unique
          - name: total_amount
            data_tests:
              - not_null
              - dbt_expectations.expect_column_values_to_be_between:
                  arguments:
                    min_value: 0
                    max_value: 1000000
          - name: revenue_tier
            data_tests:
              - not_null
              - accepted_values:
                  arguments:
                    values: ['zero', 'low', 'medium', 'high', 'vip']

      - name: fct_orders_surrogate
        description: "Заказы с суррогатным ключом"
        columns:
          - name: order_sk
            data_tests:
              - not_null
              - unique

      - name: dim_date
        description: "Таблица дат 2023-2025"
        data_tests:
          - dbt_expectations.expect_table_row_count_to_be_between:
              arguments:
                min_value: 700
                max_value: 1200
        columns:
          - name: date_id
            data_tests:
              - not_null
              - unique
""")

files = {
    "models/marts/fct_orders_surrogate.sql": model_surrogate,
    "models/marts/fct_orders_star.sql":      model_star,
    "models/marts/dim_date.sql":             model_dim_date,
    "models/marts/schema.yml":               schema_yml,
}

print("\n📝 Создание моделей:")
for rel_path, content in files.items():
    full_path = os.path.join(DBT_PROJECT, rel_path)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ {rel_path}")

print("\n🔧 dbt compile...")
r = subprocess.run(["dbt", "compile", "--select", "fct_orders_surrogate", "dim_date", "fct_orders_star"], cwd=DBT_PROJECT, capture_output=True, text=True)
print("  ✅ compile OK" if r.returncode == 0 else f"  ⚠️\n{r.stdout[-800:]}")

print("\n🧪 dbt test...")
r = subprocess.run(["dbt", "test", "--select", "fct_orders_enriched", "dim_date"], cwd=DBT_PROJECT, capture_output=True, text=True)
print("  ✅ тесты прошли" if r.returncode == 0 else f"  ⚠️\n{r.stdout[-800:]}")