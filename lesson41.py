# lesson41.py — День 41: dbt Macros (продвинутый уровень)
# Запуск: python lesson41.py

import subprocess, os, textwrap

print("=" * 70)
print("ДЕНЬ 41: dbt Macros — продвинутый уровень")
print("=" * 70)

DBT_PROJECT = "dbt_analytics"

os.makedirs(os.path.join(DBT_PROJECT, "macros"), exist_ok=True)
os.makedirs(os.path.join(DBT_PROJECT, "models", "marts"), exist_ok=True)
os.makedirs(os.path.join(DBT_PROJECT, "models", "staging"), exist_ok=True)

macro_classify = textwrap.dedent("""\
    {% macro revenue_tier(column_name) %}
        CASE
            WHEN {{ column_name }} = 0      THEN 'zero'
            WHEN {{ column_name }} < 1000   THEN 'low'
            WHEN {{ column_name }} < 5000   THEN 'medium'
            WHEN {{ column_name }} < 20000  THEN 'high'
            ELSE                                 'vip'
        END
    {% endmacro %}

    {% macro customer_activity_status(days_since_last_order) %}
        CASE
            WHEN {{ days_since_last_order }} IS NULL THEN 'never_ordered'
            WHEN {{ days_since_last_order }} <= 30   THEN 'active'
            WHEN {{ days_since_last_order }} <= 90   THEN 'at_risk'
            WHEN {{ days_since_last_order }} <= 180  THEN 'churned'
            ELSE                                          'lost'
        END
    {% endmacro %}

    {% macro safe_divide(numerator, denominator, default=0) %}
        CASE
            WHEN {{ denominator }} = 0 OR {{ denominator }} IS NULL
            THEN {{ default }}
            ELSE {{ numerator }} / {{ denominator }}
        END
    {% endmacro %}
""")

macro_dates = textwrap.dedent("""\
    {% macro date_trunc_safe(period, column) %}
        DATE_TRUNC('{{ period }}', {{ column }})
    {% endmacro %}

    {% macro period_label(period, date_column) %}
        {% if period == 'month' %}
            STRFTIME({{ date_column }}, '%Y-%m')
        {% elif period == 'quarter' %}
            STRFTIME({{ date_column }}, '%Y') || '-Q' ||
            CAST(EXTRACT(QUARTER FROM {{ date_column }}) AS VARCHAR)
        {% elif period == 'year' %}
            STRFTIME({{ date_column }}, '%Y')
        {% else %}
            STRFTIME({{ date_column }}, '%Y-%W')
        {% endif %}
    {% endmacro %}

    {% macro days_since(date_column) %}
        DATEDIFF('day', {{ date_column }}, CURRENT_DATE)
    {% endmacro %}
""")

macro_pivot = textwrap.dedent("""\
    {% macro pivot_sum(values, column, agg_column, prefix='') %}
        {% for val in values %}
        SUM(CASE WHEN {{ column }} = '{{ val }}'
                 THEN {{ agg_column }} ELSE 0
            END) AS {{ prefix }}{{ val }}
        {%- if not loop.last %},{% endif %}
        {% endfor %}
    {% endmacro %}

    {% macro count_by_value(values, filter_column, count_column, prefix='cnt_') %}
        {% for val in values %}
        COUNT(DISTINCT CASE WHEN {{ filter_column }} = '{{ val }}'
                            THEN {{ count_column }} END) AS {{ prefix }}{{ val }}
        {%- if not loop.last %},{% endif %}
        {% endfor %}
    {% endmacro %}
""")

model_enriched = textwrap.dedent("""\
    {{ config(materialized='table') }}
    SELECT
        order_id,
        user_id                                             AS customer_id,
        amount                                              AS total_amount,
        created_at::DATE                                    AS order_date,
        {{ revenue_tier('amount') }}                        AS revenue_tier,
        {{ days_since('created_at') }}                      AS days_since_order,
        {{ customer_activity_status(days_since('created_at')) }} AS activity_status,
        {{ safe_divide('amount', '1', 0) }}                 AS unit_price_safe
    FROM {{ ref('stg_orders') }}
""")

model_pivot = textwrap.dedent("""\
    {{ config(materialized='table') }}
    SELECT
        DATE_TRUNC('month', created_at) AS order_month,
        {{ pivot_sum(
            values=['completed', 'pending', 'cancelled', 'refunded'],
            column='status',
            agg_column='amount',
            prefix='revenue_'
        ) }},
        {{ count_by_value(
            values=['completed', 'pending', 'cancelled', 'refunded'],
            filter_column='status',
            count_column='order_id',
            prefix='orders_'
        ) }}
    FROM {{ ref('stg_orders') }}
    GROUP BY 1
    ORDER BY 1
""")

files = {
    "macros/classify.sql":               macro_classify,
    "macros/date_utils.sql":             macro_dates,
    "macros/pivot.sql":                  macro_pivot,
    "models/marts/fct_orders_enriched.sql":     model_enriched,
    "models/marts/monthly_channel_pivot.sql":   model_pivot,
}

print("\n📝 Создание файлов:")
for rel_path, content in files.items():
    full_path = os.path.join(DBT_PROJECT, rel_path)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ {rel_path}")

print("\n🔧 dbt compile...")
r = subprocess.run(
    ["dbt", "compile", "--select", "fct_orders_enriched", "monthly_channel_pivot"],
    cwd=DBT_PROJECT, capture_output=True, text=True
)
print("  ✅ compile OK" if r.returncode == 0 else f"  ⚠️\n{r.stdout[-800:]}")