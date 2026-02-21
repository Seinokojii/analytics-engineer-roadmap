-- macros/revenue_tier.sql

-- �������������� ����� �� �������
{% macro classify_revenue_tier(column_name) %}
    CASE
        WHEN {{ column_name }} = 0        THEN 'zero'
        WHEN {{ column_name }} < 1000     THEN 'low'
        WHEN {{ column_name }} < 5000     THEN 'medium'
        WHEN {{ column_name }} < 20000    THEN 'high'
        ELSE                                   'vip'
    END
{% endmacro %}


-- ���������� ������� (��� ZeroDivisionError)
{% macro safe_divide(numerator, denominator) %}
    CASE
        WHEN {{ denominator }} = 0 OR {{ denominator }} IS NULL THEN NULL
        ELSE ROUND(CAST({{ numerator }} AS FLOAT) / {{ denominator }}, 2)
    END
{% endmacro %}


-- �������������� ��������
{% macro normalize_status(column_name) %}
    CASE UPPER(TRIM({{ column_name }}))
        WHEN 'COMPLETED' THEN 'completed'
        WHEN 'CANCELLED' THEN 'cancelled'
        WHEN 'PENDING'   THEN 'pending'
        ELSE                  'unknown'
    END
{% endmacro %}