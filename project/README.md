# E-Commerce Mini ETL + DW

Mesyachnyy proekt: polnyy ETL pipeline dlya e-commerce analitiki.

## Stack
- Python (pandas, numpy, duckdb)
- dbt-duckdb
- matplotlib, seaborn

## Arkhitektura
```
CSV (raw) в†’ ETL (Python OOP) в†’ DuckDB (Star Schema) в†’ dbt в†’ Dashboard
```

## Star Schema
- fct_orders (tsentral'naya tablitsa)
- dim_products, dim_customers, dim_date, dim_channels

## KPI
- GMV (Gross Merchandise Value)
- Active Users
- AOV (Average Order Value)
- Conversion Rate

## Zapusk
```bash
python monthly_project.py
cd project_dbt
dbt run
dbt test
```

## Rezultaty
- 5000 zakazov, 500 klientov, 100 tovarov
- 5 kategoriy tovarov
- dbt modeli + 7 testov kachestva
- Dashboard s 6 grafikami
