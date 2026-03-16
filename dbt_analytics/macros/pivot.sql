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
