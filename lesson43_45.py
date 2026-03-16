# lesson43_45.py — Дни 43-45: Exposures + Tags + Sources + Mini-Project
# Запуск: python lesson43_45.py

import subprocess, os, textwrap

print("=" * 70)
print("ДНИ 43-45: dbt Exposures + Tags + Sources + Mini-Project")
print("=" * 70)

DBT_PROJECT = "dbt_analytics"

os.makedirs(os.path.join(DBT_PROJECT, "models", "staging"), exist_ok=True)
os.makedirs(os.path.join(DBT_PROJECT, "models", "marts"),   exist_ok=True)

sources_yml = textwrap.dedent("""\
    version: 2
    sources:
      - name: raw
        description: "Сырые данные"
        schema: main
        freshness:
          warn_after:  {count: 12, period: hour}
          error_after: {count: 24, period: hour}
        loaded_at_field: created_at

        tables:
          - name: raw_orders
            description: "Сырые заказы"
            columns:
              - name: order_id
                data_tests:
                  - not_null
                  - unique
              - name: user_id
                data_tests:
                  - not_null
              - name: amount
                data_tests:
                  - not_null
                  - dbt_expectations.expect_column_values_to_be_between:
                      arguments:
                        min_value: 0
                        max_value: 10000000
""")

exposures_yml = textwrap.dedent("""\
    version: 2
    exposures:
      - name: sales_performance_dashboard
        type: dashboard
        maturity: high
        url: https://app.powerbi.com/reports/sales-performance
        description: Дашборд эффективности продаж.
        depends_on:
          - ref('fct_orders_enriched')
          - ref('monthly_channel_pivot')
          - ref('dim_date')
        owner:
          name: Analytics Team
          email: analytics@company.com

      - name: customer_retention_report
        type: analysis
        maturity: medium
        description: Еженедельный отчёт по retention и churn.
        depends_on:
          - ref('fct_orders_enriched')
          - ref('fct_orders_surrogate')
        owner:
          name: Growth Team
          email: growth@company.com

      - name: finance_monthly_close
        type: ml
        maturity: low
        description: Данные для финансового закрытия месяца.
        depends_on:
          - ref('fct_orders_enriched')
          - ref('monthly_channel_pivot')
        owner:
          name: Finance Team
          email: finance@company.com
""")

model_daily = textwrap.dedent("""\
    {{ config(materialized='incremental', unique_key='order_id', tags=['daily', 'finance', 'critical']) }}
    SELECT
        order_id,
        user_id                        AS customer_id,
        amount                         AS total_amount,
        created_at::DATE               AS order_date,
        status,
        {{ revenue_tier('amount') }}   AS revenue_tier,
        CURRENT_TIMESTAMP              AS loaded_at
    FROM {{ ref('stg_orders') }}

    {% if is_incremental() %}
    WHERE created_at::DATE > (SELECT MAX(order_date) FROM {{ this }})
    {% endif %}
""")

model_weekly = textwrap.dedent("""\
    {{ config(materialized='table', tags=['weekly', 'marketing']) }}
    SELECT
        DATE_TRUNC('week', created_at)       AS week_start,
        {{ revenue_tier('amount') }}         AS revenue_tier,
        COUNT(DISTINCT order_id)             AS order_count,
        SUM(amount)                          AS total_revenue,
        {{ safe_divide('SUM(amount)', 'COUNT(DISTINCT order_id)') }} AS avg_order_value
    FROM {{ ref('stg_orders') }}
    GROUP BY 1, 2
    ORDER BY 1
""")

files = {
    "models/staging/sources.yml":           sources_yml,
    "models/marts/exposures.yml":           exposures_yml,
    "models/marts/fct_orders_daily.sql":    model_daily,
    "models/marts/fct_orders_weekly.sql":   model_weekly,
}

print("\n📝 Создание файлов:")
for rel_path, content in files.items():
    full_path = os.path.join(DBT_PROJECT, rel_path)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ {rel_path}")

steps = [
    (["dbt", "deps"],                                    "deps"),
    (["dbt", "compile"],                                 "compile"),
    (["dbt", "run",  "--select", "tag:staging"],         "run staging"),
    (["dbt", "run",  "--select", "fct_orders_enriched", "fct_orders_surrogate", "dim_date", "monthly_channel_pivot", "fct_orders_daily", "fct_orders_weekly"],   "run marts"),
    (["dbt", "test", "--select", "fct_orders_enriched"], "test enriched"),
    (["dbt", "test", "--select", "dim_date"],            "test dim_date"),
]

for cmd, label in steps:
    r = subprocess.run(cmd, cwd=DBT_PROJECT, capture_output=True, text=True)
    status = "✅" if r.returncode == 0 else "⚠️ "
    print(f"  {status} dbt {label}")
    if r.returncode != 0:
        print(f"     {r.stdout[-400:]}")