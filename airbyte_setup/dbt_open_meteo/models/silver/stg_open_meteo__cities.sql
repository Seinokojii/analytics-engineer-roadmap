select
    city,
    country_code,
    country,
    latitude,
    longitude,
    elevation_m,
    timezone,
    population
from {{ source('bronze', 'cities') }}
