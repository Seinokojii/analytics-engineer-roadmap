{% macro safe_divide(numerator, denominator) %}
    CASE 
        WHEN {{ denominator }} = 0 THEN 0
        ELSE {{ numerator }} / {{ denominator }}
    END
{% endmacro %}