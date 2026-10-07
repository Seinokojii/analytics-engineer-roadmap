-- Минимум дня не может быть выше максимума. Падает на перепутанных колонках
-- в маппинге коннектора — такую ошибку not_null и unique не видят.
select *
from {{ ref('stg_open_meteo__daily_weather') }}
where temperature_min_c > temperature_max_c
