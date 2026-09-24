-- Days 101-104: Silver-obertka nad snapshot klientov.
--
-- Snapshot - eto Bronze: istoriya syrykh zapisey, kotoruyu nelzya
-- vosstanovit iz istochnika (raw_customers khranit tolko tekushchee
-- sostoyanie). Do perestroyki dim_customers i dim_customers_history
-- chitali snapshot napryamuyu - Gold smotrel v Bronze mimo Silver.
-- Teper dbt-kolonki pereimenovyvayutsya odin raz zdes, a Gold
-- chitaet uzhe chistyy kontrakt.

SELECT
    customer_id,
    email,
    plan,
    status,
    dbt_valid_from                AS valid_from,
    dbt_valid_to                  AS valid_to,
    dbt_updated_at                AS last_updated,
    dbt_valid_to IS NULL          AS is_current
FROM {{ ref('snap_customers') }}
