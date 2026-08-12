{#
    macros/duckdb_elementary_shims.sql
    Day 86-88.

    Elementary dispatchit edr_multi_value_in i imeet realizatsii dlya
    default / bigquery / redshift / fabric / sqlserver. duckdb__ net,
    poetomu on padaet v default__, kotoryy generiruet tuple IN:

        (a, b) in (select x, y from t)

    DuckDB tak ne umeet:
        Binder Error: Subquery returns 2 columns - expected 1

    Chinim tem zhe priyomom, chto Elementary primenil dlya T-SQL -
    korrelirovannyy EXISTS. On ne trebuet CONCAT i ne lomaetsya na NULL,
    v otlichie ot bigquery/redshift varianta.

    Chtoby dbt vzyal etot makros vmesto paketnogo, v dbt_project.yml
    propisan dispatch: search_order ['analytics_project', 'elementary'].
#}

{%- macro duckdb__edr_multi_value_in(source_cols, target_cols, target_table) -%}
    exists (
        select 1
        from {{ target_table }} as __edr_mvi
        where
            {%- for i in range(source_cols | length) %}
                __edr_mvi.{{ target_cols[i] }} = {{ source_cols[i] }}
                {%- if not loop.last %} and {% endif %}
            {%- endfor %}
    )
{%- endmacro -%}
