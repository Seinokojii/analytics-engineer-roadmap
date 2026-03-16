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
