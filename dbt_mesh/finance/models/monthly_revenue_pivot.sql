-- Days 105-107: v monolite eta vitrina chitala stg_orders (Silver) napryamuyu.
-- Pri razreze eto rebro okazalos cherez granitsu proektov na private-model,
-- i ego prishlos perevesti na publichnyy fct_orders:
--   created_at -> order_date (fct_orders pereimenovyvaet kolonku)
--   WHERE status = 'completed' ubran: fct_orders uzhe tolko completed,
--   kolonki status v publichnom kontrakte net.
-- Ravenstvo s monolitom proveryaet lesson105_107.py, shag 7.

{% set months = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] %}

SELECT
    user_id,

    {% for month in months %}
    SUM(CASE
        WHEN EXTRACT(MONTH FROM order_date) = {{ month }}
        THEN amount
        ELSE 0
    END) AS revenue_month_{{ month }}
    {% if not loop.last %},{% endif %}
    {% endfor %}

FROM {{ ref('platform', 'fct_orders') }}
GROUP BY user_id
ORDER BY user_id
