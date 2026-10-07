-- В закрытом месяце дней должно быть столько, сколько в календаре.
-- Текущий (последний загруженный) месяц города пропускаем: он ещё идёт.
select m.city, m.month, m.days_loaded
from {{ ref('mart_weather_monthly') }} m
join (
    select city, min(month) as first_month, max(month) as last_month
    from {{ ref('mart_weather_monthly') }}
    group by 1
) b using (city)
where m.month > b.first_month
  and m.month < b.last_month
  and m.days_loaded <> date_diff('day', m.month, m.month + interval 1 month)
