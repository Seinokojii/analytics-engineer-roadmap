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
