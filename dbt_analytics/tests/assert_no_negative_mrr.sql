-- MRR ne mozhet byt otricatelnym
SELECT subscription_id, mrr
FROM {{ ref('fct_subscriptions') }}
WHERE mrr < 0
