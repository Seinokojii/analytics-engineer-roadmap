-- Gold: погода по городу и месяцу. Зерно — city + month.
select
    w.city,
    c.country_code,
    date_trunc('month', w.weather_date)::date  as month,
    count(*)                                   as days_loaded,
    round(avg(w.temperature_max_c), 1)         as avg_temperature_max_c,
    round(avg(w.temperature_min_c), 1)         as avg_temperature_min_c,
    round(sum(w.precipitation_mm), 1)          as precipitation_mm,
    count(*) filter (where w.precipitation_mm >= 1)  as rainy_days
from {{ ref('stg_open_meteo__daily_weather') }} w
left join {{ ref('stg_open_meteo__cities') }} c using (city)
group by 1, 2, 3
