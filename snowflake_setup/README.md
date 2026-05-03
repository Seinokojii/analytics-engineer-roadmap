# Snowflake Setup — Days 71-73

Generated: 2026-05-03

## Steps

1. Register: https://signup.snowflake.com
2. Run 01_setup_database.sql in Worksheet
3. Run 02_roles_rbac.sql
4. Run 03_create_tables.sql
5. Run 04_first_queries.sql

## Architecture

```
analytics_db/
  raw/      <- Bronze: COPY INTO from Stage
  staging/  <- Silver: cleaned data
  marts/    <- Gold:   business models
```

## Warehouse config

- Size: XSMALL (dev), SMALL (prod)
- Auto-suspend: 60s (save credits)
- Auto-resume: TRUE (transparent to users)
