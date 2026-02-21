"""
Den 23: dbt Testing
Schema tests, generic tests, singular tests - 5+ testov kachestva
"""

from pathlib import Path

print("=" * 70)
print(" " * 12 + "DEN 23: DBT TESTING")
print("=" * 70)

project_path = Path('dbt_analytics')

if not project_path.exists():
    print("Snachala zapusti lesson17_dbt_basics.py!")
    exit(1)


# ========================================
# CHAST 1: SCHEMA TESTS
# ========================================

print("\n" + "=" * 70)
print("CHAST 1: Schema Tests - vstroennye testy")
print("=" * 70)

schema_yml = """
version: 2

sources:
  - name: raw_data
    description: "Syryye dannyye internet-magazina"
    tables:
      - name: raw_users
        description: "Polzovateli iz CRM"
        columns:
          - name: user_id
            tests:
              - unique
              - not_null
          - name: email
            tests:
              - not_null

      - name: raw_orders
        description: "Zakazy"
        columns:
          - name: order_id
            tests:
              - unique
              - not_null
          - name: status
            tests:
              - accepted_values:
                  values: ['completed', 'pending', 'cancelled']

models:
  - name: stg_users
    description: "Staging: ochishchennyye polzovateli"
    columns:
      - name: user_id
        description: "Unikalnyy ID polzovatelya"
        tests:
          - unique
          - not_null
      - name: email
        description: "Email polzovatelya"
        tests:
          - not_null

  - name: stg_orders
    description: "Staging: completed zakazy"
    columns:
      - name: order_id
        description: "Unikalnyy ID zakaza"
        tests:
          - unique
          - not_null
      - name: user_id
        description: "FK to stg_users"
        tests:
          - not_null
          - relationships:
              to: ref('stg_users')
              field: user_id
      - name: status
        tests:
          - accepted_values:
              values: ['completed']
      - name: amount
        tests:
          - not_null

  - name: fct_orders_enriched
    description: "Fact table s obogashchennymi dannymi"
    columns:
      - name: order_id
        tests:
          - unique
          - not_null
      - name: revenue_tier
        tests:
          - accepted_values:
              values: ['zero', 'low', 'medium', 'high', 'vip']

  - name: dim_customers
    description: "Dimension: agregatsiya po klientam"
    columns:
      - name: user_id
        tests:
          - unique
          - not_null
      - name: total_orders
        tests:
          - not_null
      - name: total_spent
        tests:
          - not_null
"""

with open(project_path / 'models' / 'schema.yml', 'w', encoding='utf-8') as f:
    f.write(schema_yml.strip())

print("Sozdan schema.yml s 4 vstroennymi testami:")
print("  - unique          : net dubley")
print("  - not_null        : net NULL")
print("  - accepted_values : tolko iz spiska")
print("  - relationships   : FK sushchestvuyet v roditelskoy tablitse")


# ========================================
# CHAST 2: SEVERITY
# ========================================

print("\n" + "=" * 70)
print("CHAST 2: Severity - warn vs error")
print("=" * 70)

severity_schema = """
version: 2

models:
  - name: stg_orders
    columns:
      - name: amount
        tests:
          - not_null:
              severity: error

      - name: user_id
        tests:
          - relationships:
              to: ref('stg_users')
              field: user_id
              severity: warn
              config:
                warn_if: ">5"
                error_if: ">50"
"""

path = project_path / 'models' / 'staging' / 'schema_severity.yml'
with open(path, 'w', encoding='utf-8') as f:
    f.write(severity_schema.strip())

print("Sozdan schema_severity.yml:")
print("  severity: error  -> test upavl -> dbt ostanovitsya")
print("  severity: warn   -> test upal -> dbt prodolzhayet, vydayet WARNING")
print("  warn_if / error_if -> porogovyye znacheniya narusheniy")


# ========================================
# CHAST 3: GENERIC TESTS
# ========================================

print("\n" + "=" * 70)
print("CHAST 3: Generic Tests - pereispolzuyemyye pravila")
print("=" * 70)

(project_path / 'macros' / 'tests').mkdir(parents=True, exist_ok=True)

generic_tests = """
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
"""

with open(project_path / 'macros' / 'tests' / 'generic_tests.sql', 'w', encoding='utf-8') as f:
    f.write(generic_tests.strip())

print("Sozdany generic tests v macros/tests/generic_tests.sql:")
print("  - positive_values(column)      : znacheniya > 0")
print("  - no_whitespace(column)        : net probelov")
print("  - not_in_future(column)        : data ne v budushchem")
print("  - in_range(column, min, max)   : znacheniye v diapazone")

generic_usage_schema = """
version: 2

models:
  - name: stg_orders
    columns:
      - name: amount
        tests:
          - positive_values
          - in_range:
              min_value: 1
              max_value: 100000

      - name: created_at
        tests:
          - not_in_future

  - name: stg_users
    columns:
      - name: user_name
        tests:
          - no_whitespace
"""

path = project_path / 'models' / 'staging' / 'schema_generic.yml'
with open(path, 'w', encoding='utf-8') as f:
    f.write(generic_usage_schema.strip())

print("Sozdan schema_generic.yml - primeneniye generic tests")


# ========================================
# CHAST 4: SINGULAR TESTS
# ========================================

print("\n" + "=" * 70)
print("CHAST 4: Singular Tests - biznes-pravila")
print("=" * 70)

(project_path / 'tests').mkdir(exist_ok=True)

no_orphans_test = """
-- tests/test_no_orphan_orders.sql
-- Biznes-pravilo: kazhdyy zakaz dolzhen imet sushchestvuyushchego polzovatelya
-- Orphan = zakaz bez klienta

SELECT
    o.order_id,
    o.user_id
FROM {{ ref('stg_orders') }} o
LEFT JOIN {{ ref('stg_users') }} u ON o.user_id = u.user_id
WHERE u.user_id IS NULL
"""

with open(project_path / 'tests' / 'test_no_orphan_orders.sql', 'w', encoding='utf-8') as f:
    f.write(no_orphans_test.strip())

revenue_consistency_test = """
-- tests/test_revenue_consistency.sql
-- Biznes-pravilo: dim_customers.total_spent >= 0 vsegda
-- Otritsatelnyy LTV - priznak oshibki v dannykh

SELECT
    user_id,
    total_spent
FROM {{ ref('dim_customers') }}
WHERE total_spent < 0
"""

with open(project_path / 'tests' / 'test_revenue_consistency.sql', 'w', encoding='utf-8') as f:
    f.write(revenue_consistency_test.strip())

no_future_orders_test = """
-- tests/test_no_future_orders.sql
-- Biznes-pravilo: zakazy ne mogut byt v budushchem
-- Yesli yest - oshibka v ETL ili testovyye dannyye popali v prod

SELECT
    order_id,
    created_at
FROM {{ ref('stg_orders') }}
WHERE created_at::DATE > CURRENT_DATE
"""

with open(project_path / 'tests' / 'test_no_future_orders.sql', 'w', encoding='utf-8') as f:
    f.write(no_future_orders_test.strip())

tier_logic_test = """
-- tests/test_tier_logic_consistency.sql
-- Biznes-pravilo: revenue_tier dolzhen sootvetstvovat amount
-- VIP zakazy ne mogut imet amount < 20000

SELECT
    order_id,
    amount,
    revenue_tier
FROM {{ ref('fct_orders_enriched') }}
WHERE (revenue_tier = 'vip' AND amount < 20000)
   OR (revenue_tier = 'low' AND amount >= 5000)
"""

with open(project_path / 'tests' / 'test_tier_logic_consistency.sql', 'w', encoding='utf-8') as f:
    f.write(tier_logic_test.strip())

print("Sozdany singular tests v tests/:")
print("  - test_no_orphan_orders.sql       : zakazy bez klientov")
print("  - test_revenue_consistency.sql    : total_spent >= 0")
print("  - test_no_future_orders.sql       : net dat v budushchem")
print("  - test_tier_logic_consistency.sql : tier sootvetstvuyet amount")


# ========================================
# CHAST 5: ITOG
# ========================================

print("\n" + "=" * 70)
print("CHAST 5: Itog - 10 testov kachestva dannykh")
print("=" * 70)

print("""
POLNYY SPISOK TESTOV:

Schema Tests (iz schema.yml):
  TEST 1: unique          : stg_orders.order_id
  TEST 2: not_null        : stg_orders.user_id, amount
  TEST 3: accepted_values : stg_orders.status = ['completed']
  TEST 4: relationships   : stg_orders.user_id -> stg_users.user_id

Generic Tests (iz macros/tests/):
  TEST 5: positive_values : stg_orders.amount > 0
  TEST 6: not_in_future   : stg_orders.created_at <= CURRENT_DATE
  TEST 7: no_whitespace   : stg_users.user_name

Singular Tests (iz tests/):
  TEST 8:  test_no_orphan_orders
  TEST 9:  test_revenue_consistency
  TEST 10: test_tier_logic_consistency

ITOGO: 10 testov (trebuvalos 5) OK
""")


# ========================================
# CHAST 6: KOMANDY
# ========================================

print("\n" + "=" * 70)
print("CHAST 6: Komandy dlya zapuska testov")
print("=" * 70)

print("""
Komandy dbt test:

Zapustit VSE testy:
   dbt test

Testy tolko odnoy modeli:
   dbt test --select stg_orders

Testy istochnikov (sources):
   dbt test --select source:raw_data

Sokhranit provalivshiyesya stroki v BD:
   dbt test --store-failures

Zapustit modeli + testy za odin raz:
   dbt build

Ozhidayemyy rezultat:
   Running 10 tests...
   PASS unique_stg_orders_order_id ............. [PASS in 0.08s]
   PASS not_null_stg_orders_user_id ............ [PASS in 0.06s]
   PASS relationships_stg_orders_user_id ....... [PASS in 0.12s]
   PASS accepted_values_stg_orders_status ...... [PASS in 0.07s]
   PASS positive_values_stg_orders_amount ...... [PASS in 0.09s]
   PASS not_in_future_stg_orders_created_at .... [PASS in 0.07s]
   PASS no_whitespace_stg_users_user_name ...... [PASS in 0.08s]
   PASS test_no_orphan_orders .................. [PASS in 0.11s]
   PASS test_revenue_consistency ............... [PASS in 0.09s]
   PASS test_tier_logic_consistency ............ [PASS in 0.10s]
   Finished running 10 tests. 10 passed, 0 failed.

Yesli test upal:
   dbt test --select stg_orders --store-failures
   -> smotri tablitsu failures v BD: kakiye stroki narushayut pravilo
""")


# ========================================
# ITOGI
# ========================================

print("\n" + "=" * 70)
print("DEN 23 ZAVERSHEN!")
print("=" * 70)
print(f"""
Ty sozdal sistemu testirovaniya dannykh:
1. Schema tests      : unique, not_null, accepted_values, relationships
2. Severity          : error (kritichno) vs warn (preduprezhdeniye)
3. Generic tests     : positive_values, not_in_future, no_whitespace, in_range
4. Singular tests    : 4 biznes-pravila v tests/
5. 10 testov         : polnoye pokrytiye proyekta

Proyekt: {project_path.absolute()}

KOMANDY:
cd dbt_analytics
dbt build          # run + test za odin shag
dbt docs serve     # Posmotri graf testov v brauzere

Sleduyushchiy den: Den 24 - BI osnovy (Power BI / Tableau)
""")