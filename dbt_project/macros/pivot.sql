{# macros/pivot.sql — динамическая генерация PIVOT-колонок #}

{#
Генерирует SUM(CASE WHEN channel = X THEN amount END) для каждого значения.

Использование в модели:
    {{ pivot_sum(
        values=['web', 'mobile', 'email'],
        column='channel',
        agg_column='total_amount',
        prefix='revenue_'
    ) }}
#}
{% macro pivot_sum(values, column, agg_column, prefix='') %}
    {% for val in values %}
    SUM(CASE WHEN {{ column }} = '{{ val }}'
             THEN {{ agg_column }} ELSE 0
        END) AS {{ prefix }}{{ val }}
    {%- if not loop.last %},{% endif %}
    {% endfor %}
{% endmacro %}


{#
Генерирует COUNT(DISTINCT id) FILTER (WHERE column = X) для каждого значения.
#}
{% macro count_by_value(values, filter_column, count_column, prefix='cnt_') %}
    {% for val in values %}
    COUNT(DISTINCT CASE WHEN {{ filter_column }} = '{{ val }}'
                        THEN {{ count_column }} END) AS {{ prefix }}{{ val }}
    {%- if not loop.last %},{% endif %}
    {% endfor %}
{% endmacro %}
