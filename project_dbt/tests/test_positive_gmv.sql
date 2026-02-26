SELECT month, gmv
FROM {{ ref('monthly_summary') }}
WHERE gmv <= 0
