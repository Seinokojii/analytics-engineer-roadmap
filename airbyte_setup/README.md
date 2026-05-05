# Airbyte Self-Hosted — Days 79-80

## Quick Install
```bash
git clone https://github.com/airbytehq/airbyte.git --depth 1
cd airbyte && ./run-ab-platform.sh
# Open http://localhost:8000
```

## 3 Connectors

### 1. Faker (start here — no credentials)
Sources -> New Source -> Faker -> Count: 1000, Seed: 42

### 2. GitHub API
Sources -> New Source -> GitHub
Personal Access Token: github.com -> Settings -> Developer Settings -> PAT

### 3. PostgreSQL
Sources -> New Source -> PostgreSQL -> CDC replication

## Destination: Snowflake
See connectors/04_snowflake_destination.json

## After sync
```sql
SHOW TABLES IN SCHEMA analytics_db.raw;
SELECT * FROM analytics_db.raw._airbyte_raw_orders LIMIT 10;
```
