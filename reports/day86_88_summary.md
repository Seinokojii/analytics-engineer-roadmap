# Days 86-88 - Testing + Monitoring

Sgenerirovano: 2026-08-12T19:40:53

- dbt build (tag:production_pipeline): `PASS=35 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=35`
- Elementary: 0.25.1, shema `main_elementary`
- Tablits Elementary: 30
- CI: `.github/workflows/dbt_ci.yml`
- Docker: `Dockerfile`, `docker-compose.yml`

## Perehod na Snowflake

1. profiles.yml: target `prod` type snowflake
2. GitHub Secrets: SNOWFLAKE_ACCOUNT / USER / PASSWORD / ROLE /
   WAREHOUSE / DATABASE
3. Raskommentirovat job `dbt-snowflake` v dbt_ci.yml
4. Udalit macros/duckdb_elementary_shims.sql - na Snowflake
   default__ dispatch rabotaet
