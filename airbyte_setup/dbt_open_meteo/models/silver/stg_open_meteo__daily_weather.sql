-- Silver: одна строка на city + date — последняя прочитанная версия.
-- Airbyte в режиме append_dedup делает то же самое сам; здесь режим append,
-- и дедупликация явная, чтобы было видно, откуда берутся дубли.
select
    city || '|' || cast("date" as varchar)  as weather_key,
    city,
    cast("date" as date)                    as weather_date,
    temperature_max_c,
    temperature_min_c,
    precipitation_mm,
    wind_speed_max_kmh,
    _airbyte_extracted_at                   as extracted_at
from {{ source('bronze', 'daily_weather_raw') }}
qualify row_number() over (
    partition by city, "date"
    order by _airbyte_extracted_at desc, _airbyte_raw_id desc
) = 1
