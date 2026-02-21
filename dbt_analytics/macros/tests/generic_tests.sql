-- macros/tests/generic_tests.sql
-- Pereispolzuyemyye testy (vyzyvayutsya iz schema.yml)


-- TEST 5: Znacheniya dolzhny byt > 0
{% test positive_values(model, column_name) %}

    SELECT {{ column_name }}
    FROM {{ model }}
    WHERE {{ column_name }} <= 0
      AND {{ column_name }} IS NOT NULL

{% endtest %}


-- Test: net probelov v nachale/kontse stroki
{% test no_whitespace(model, column_name) %}

    SELECT {{ column_name }}
    FROM {{ model }}
    WHERE {{ column_name }} != TRIM({{ column_name }})
      AND {{ column_name }} IS NOT NULL

{% endtest %}


-- Test: data ne v budushchem
{% test not_in_future(model, column_name) %}

    SELECT {{ column_name }}
    FROM {{ model }}
    WHERE {{ column_name }} > CURRENT_DATE

{% endtest %}


-- Test: znacheniye v zadannom diapazone
{% test in_range(model, column_name, min_value, max_value) %}

    SELECT {{ column_name }}
    FROM {{ model }}
    WHERE {{ column_name }} < {{ min_value }}
       OR {{ column_name }} > {{ max_value }}

{% endtest %}