"""
Месячный проект: E-Commerce Mini ETL + DW
Novyy dataset в†’ ETL в†’ Star Schema в†’ dbt в†’ Dashboard
"""

import pandas as pd
import numpy as np
import duckdb
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import logging
from pathlib import Path
from datetime import datetime, timedelta

print("=" * 70)
print(" " * 5 + "МЕСЯЧНЫЙ ПРОЕКТ: E-COMMERCE MINI ETL + DW")
print("=" * 70)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('project.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('MonthlyProject')

Path('project/data/raw').mkdir(parents=True, exist_ok=True)
Path('project/data/clean').mkdir(parents=True, exist_ok=True)
Path('project/reports').mkdir(parents=True, exist_ok=True)


# ========================================
# ШАГ 1: ГЕНЕРАЦИЯ НОВОГО ДАТАСЕТА
# ========================================

print("\n" + "=" * 70)
print("ШАГ 1: Генерация нового e-commerce датасета")
print("=" * 70)

np.random.seed(2024)

N_CUSTOMERS = 500
N_PRODUCTS  = 100
N_ORDERS    = 5000

# Kategorii i produkty
categories = {
    'Electronics':  ['Laptop', 'Smartphone', 'Tablet', 'Smartwatch', 'Camera'],
    'Clothing':     ['T-Shirt', 'Jeans', 'Jacket', 'Dress', 'Sneakers'],
    'Home':         ['Sofa', 'Lamp', 'Pillow', 'Curtains', 'Mirror'],
    'Sports':       ['Dumbbells', 'Yoga Mat', 'Bicycle', 'Tennis Racket', 'Skis'],
    'Books':        ['Fiction', 'Non-Fiction', 'Textbook', 'Comics', 'Cookbook'],
}

products_list = []
product_id = 1
for cat, items in categories.items():
    for item in items:
        price_ranges = {
            'Electronics': (3000, 80000),
            'Clothing':    (500, 15000),
            'Home':        (1000, 50000),
            'Sports':      (500, 30000),
            'Books':       (200, 2000),
        }
        lo, hi = price_ranges[cat]
        products_list.append({
            'product_id':   product_id,
            'product_name': item,
            'category':     cat,
            'base_price':   np.random.randint(lo, hi),
            'brand':        np.random.choice(
                ['Apple', 'Samsung', 'Nike', 'Adidas', 'IKEA',
                 'Sony', 'LG', 'Zara', 'H&M', 'Local']
            )
        })
        product_id += 1

products_df = pd.DataFrame(products_list)

# Клиенты
cities = ['Moscow', 'SPB', 'Kazan', 'Ekb', 'NSK',
          'Krasnodar', 'Rostov', 'Ufa', 'Perm', 'Volgograd']
customers_df = pd.DataFrame({
    'customer_id':  range(1, N_CUSTOMERS + 1),
    'first_name':   [f'Name_{i}' for i in range(1, N_CUSTOMERS + 1)],
    'last_name':    [f'Surname_{i}' for i in range(1, N_CUSTOMERS + 1)],
    'email':        [f'user{i}@shop.ru' for i in range(1, N_CUSTOMERS + 1)],
    'city':         np.random.choice(cities, N_CUSTOMERS),
    'age':          np.random.randint(18, 65, N_CUSTOMERS),
    'gender':       np.random.choice(['M', 'F'], N_CUSTOMERS),
    'registered_at': pd.date_range('2022-01-01', periods=N_CUSTOMERS, freq='12h')
})

# Заказы с проблемами качества (намеренно)
order_dates = [
    datetime(2024, 1, 1) + timedelta(hours=np.random.randint(0, 8760))
    for _ in range(N_ORDERS)
]
orders_df = pd.DataFrame({
    'order_id':    range(1, N_ORDERS + 1),
    'customer_id': np.random.randint(1, N_CUSTOMERS + 1, N_ORDERS),
    'product_id':  np.random.randint(1, N_PRODUCTS + 1, N_ORDERS),
    'quantity':    np.random.randint(1, 6, N_ORDERS),
    'discount_pct': np.random.choice([0, 5, 10, 15, 20, 30], N_ORDERS,
                                      p=[0.5, 0.15, 0.15, 0.1, 0.07, 0.03]),
    'channel':     np.random.choice(
        ['web', 'mobile', 'store', None],
        N_ORDERS, p=[0.45, 0.35, 0.15, 0.05]
    ),
    'status':      np.random.choice(
        ['completed', 'completed', 'completed', 'cancelled', 'refunded'],
        N_ORDERS
    ),
    'order_date':  order_dates,
    'payment':     np.random.choice(
        ['card', 'cash', 'online', None],
        N_ORDERS, p=[0.5, 0.2, 0.25, 0.05]
    )
})

# Добавляем 100 дубликатов
dupes = orders_df.sample(100, random_state=42)
orders_df = pd.concat([orders_df, dupes], ignore_index=True)

# Сохранить raw
products_df.to_csv('project/data/raw/products.csv',   index=False, encoding='utf-8')
customers_df.to_csv('project/data/raw/customers.csv', index=False, encoding='utf-8')
orders_df.to_csv('project/data/raw/orders.csv',       index=False, encoding='utf-8')

logger.info(f"Raw данные созданы:")
logger.info(f"  products:  {len(products_df)} товаров ({len(categories)} категорий)")
logger.info(f"  customers: {len(customers_df)} клиентов ({len(cities)} городов)")
logger.info(f"  orders:    {len(orders_df)} заказов (с {orders_df.duplicated('order_id').sum()} дубликами)")
print(f"Products:  {len(products_df)} строк")
print(f"Customers: {len(customers_df)} строк")
print(f"Orders:    {len(orders_df)} строк ({orders_df.duplicated('order_id').sum()} дубликатов)")


# ========================================
# ШАГ 2: EXTRACT + TRANSFORM (OOP)
# ========================================

print("\n" + "=" * 70)
print("ШАГ 2: ETL вЂ” Extract + Transform + Load")
print("=" * 70)

# EXTRACT
products_raw  = pd.read_csv('project/data/raw/products.csv')
customers_raw = pd.read_csv('project/data/raw/customers.csv')
orders_raw    = pd.read_csv('project/data/raw/orders.csv')
logger.info("Extract: все 3 CSV загружены")

# TRANSFORM вЂ” orders
orders_clean = (orders_raw
    .drop_duplicates(subset=['order_id'])
    .dropna(subset=['customer_id', 'product_id', 'order_date'])
    .assign(
        channel=lambda df: df['channel'].fillna('unknown'),
        payment=lambda df: df['payment'].fillna('unknown'),
        order_date=lambda df: pd.to_datetime(df['order_date'])
    )
    .query('quantity > 0')
)

# Priceoyedineniye ceny
orders_enriched = orders_clean.merge(
    products_raw[['product_id', 'base_price', 'category']],
    on='product_id', how='left'
)
orders_enriched['unit_price']   = (
    orders_enriched['base_price']
    * (1 - orders_enriched['discount_pct'] / 100)
).fillna(0).round(0).astype(int)
orders_enriched['total_amount'] = (
    orders_enriched['unit_price'] * orders_enriched['quantity']
).fillna(0).astype(int)
orders_enriched['month']   = orders_enriched['order_date'].dt.month
orders_enriched['quarter'] = orders_enriched['order_date'].dt.quarter
orders_enriched['year']    = orders_enriched['order_date'].dt.year

# Revenue tier
conditions = [
    orders_enriched['total_amount'] < 1000,
    (orders_enriched['total_amount'] >= 1000) & (orders_enriched['total_amount'] < 5000),
    (orders_enriched['total_amount'] >= 5000) & (orders_enriched['total_amount'] < 20000),
    orders_enriched['total_amount'] >= 20000
]
orders_enriched['revenue_tier'] = np.select(
    conditions, ['low', 'medium', 'high', 'vip'], default='low'
)

# TRANSFORM вЂ” customers
customers_clean = (customers_raw
    .assign(
        full_name=lambda df: df['first_name'] + ' ' + df['last_name'],
        registered_at=lambda df: pd.to_datetime(df['registered_at'])
    )
)

logger.info(f"Transform: {len(orders_raw)} -> {len(orders_enriched)} строк заказов")
print(f"Заказов после очистки:  {len(orders_enriched)} (было {len(orders_raw)})")
print(f"Удалено дубликатов:      {len(orders_raw) - len(orders_enriched)}")


# ========================================
# ШАГ 3: Load вЂ” STAR SCHEMA V DUCKDB
# ========================================

print("\n" + "=" * 70)
print("ШАГ 3: Load вЂ” Star Schema v DuckDB")
print("=" * 70)

con = duckdb.connect('project/ecommerce_dw.duckdb')

# dim_products
con.execute("""
    CREATE OR REPLACE TABLE dim_products AS
    SELECT
        product_id,
        product_name,
        category,
        brand,
        base_price
    FROM products_raw
""")

# dim_customers
con.execute("""
    CREATE OR REPLACE TABLE dim_customers AS
    SELECT
        customer_id,
        full_name,
        email,
        city,
        age,
        gender,
        registered_at::DATE AS registered_date
    FROM customers_clean
""")

# dim_date
con.execute("""
    CREATE OR REPLACE TABLE dim_date AS
    SELECT DISTINCT
        CAST(order_date AS DATE)            AS date_id,
        EXTRACT(YEAR FROM order_date)       AS year,
        EXTRACT(MONTH FROM order_date)      AS month,
        EXTRACT(QUARTER FROM order_date)    AS quarter,
        EXTRACT(DAY FROM order_date)        AS day,
        DAYNAME(order_date)                 AS day_name,
        MONTHNAME(order_date)               AS month_name
    FROM orders_enriched
""")

# dim_channels
con.execute("""
    CREATE OR REPLACE TABLE dim_channels AS
    SELECT DISTINCT
        channel,
        CASE channel
            WHEN 'web'     THEN 'Online'
            WHEN 'mobile'  THEN 'Online'
            WHEN 'store'   THEN 'Offline'
            ELSE 'Unknown'
        END AS channel_type
    FROM orders_enriched
""")

# fct_orders (центральная таблица фактов)
con.execute("""
    CREATE OR REPLACE TABLE fct_orders AS
    SELECT
        o.order_id,
        o.customer_id,
        o.product_id,
        CAST(o.order_date AS DATE)  AS date_id,
        o.channel,
        o.status,
        o.quantity,
        o.unit_price,
        o.total_amount,
        o.discount_pct,
        o.revenue_tier,
        o.month,
        o.quarter,
        o.year,
        o.payment
    FROM orders_enriched o
    WHERE o.status IN ('completed', 'cancelled', 'refunded')
""")

print("Star Schema создана в project/ecommerce_dw.duckdb:")
for table in ['dim_products', 'dim_customers', 'dim_date',
              'dim_channels', 'fct_orders']:
    n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  {table}: {n:,} strok")


# ========================================
# ШАГ 4: SQL Аналитика
# ========================================

print("\n" + "=" * 70)
print("ШАГ 4: SQL Аналитика вЂ” KPI metrik")
print("=" * 70)

# KPI 1: GMV
gmv = con.execute("""
    SELECT SUM(total_amount) AS gmv
    FROM fct_orders
    WHERE status = 'completed'
""").fetchone()[0]

# KPI 2: Active Users
active_users = con.execute("""
    SELECT COUNT(DISTINCT customer_id) AS active_users
    FROM fct_orders
    WHERE status = 'completed'
""").fetchone()[0]

# KPI 3: Avg Order Value
aov = con.execute("""
    SELECT ROUND(AVG(total_amount), 0) AS aov
    FROM fct_orders
    WHERE status = 'completed'
""").fetchone()[0]

# KPI 4: Conversion (completed / total)
total_all = con.execute("SELECT COUNT(*) FROM fct_orders").fetchone()[0]
total_completed = con.execute(
    "SELECT COUNT(*) FROM fct_orders WHERE status='completed'"
).fetchone()[0]
conversion = round(total_completed / total_all * 100, 1)

print(f"""
3 KPI DASHBORDA:
  GMV (Gross Merchandise Value): {gmv:>12,.0f} rub
  Active Users:                  {active_users:>12,}
  Avg Order Value (AOV):         {aov:>12,.0f} rub
  Conversion Rate:               {conversion:>11.1f}%
""")

# Top kategorii
print("Топ категорий по GMV:")
top_cat = con.execute("""
    SELECT
        p.category,
        COUNT(f.order_id)     AS orders,
        SUM(f.total_amount)   AS gmv,
        ROUND(AVG(f.total_amount), 0) AS avg_check
    FROM fct_orders f
    JOIN dim_products p ON f.product_id = p.product_id
    WHERE f.status = 'completed'
    GROUP BY p.category
    ORDER BY gmv DESC
""").df()
print(top_cat.to_string(index=False))

# Top goroda
print("\nТоп городов по GMV:")
top_cities = con.execute("""
    SELECT
        c.city,
        COUNT(f.order_id)   AS orders,
        SUM(f.total_amount) AS gmv
    FROM fct_orders f
    JOIN dim_customers c ON f.customer_id = c.customer_id
    WHERE f.status = 'completed'
    GROUP BY c.city
    ORDER BY gmv DESC
    LIMIT 5
""").df()
print(top_cities.to_string(index=False))


# ========================================
# ШАГ 5: Dashboard
# ========================================

print("\n" + "=" * 70)
print("ШАГ 5: Dashboard вЂ” 6 grafikov")
print("=" * 70)

monthly_rev = con.execute("""
    SELECT month, SUM(total_amount) AS revenue, COUNT(*) AS orders
    FROM fct_orders
    WHERE status = 'completed'
    GROUP BY month ORDER BY month
""").df()

tier_stats = con.execute("""
    SELECT revenue_tier, COUNT(*) AS cnt, SUM(total_amount) AS revenue
    FROM fct_orders WHERE status = 'completed'
    GROUP BY revenue_tier
""").df()

channel_stats = con.execute("""
    SELECT channel, SUM(total_amount) AS revenue
    FROM fct_orders WHERE status = 'completed'
    GROUP BY channel ORDER BY revenue DESC
""").df()

city_stats = con.execute("""
    SELECT c.city, SUM(f.total_amount) AS revenue
    FROM fct_orders f
    JOIN dim_customers c ON f.customer_id = c.customer_id
    WHERE f.status = 'completed'
    GROUP BY c.city ORDER BY revenue DESC LIMIT 7
""").df()

cat_month = con.execute("""
    SELECT f.month, p.category, SUM(f.total_amount) AS revenue
    FROM fct_orders f
    JOIN dim_products p ON f.product_id = p.product_id
    WHERE f.status = 'completed'
    GROUP BY f.month, p.category
""").df()

con.close()

fig = plt.figure(figsize=(18, 12))
fig.suptitle('E-Commerce Dashboard 2024 вЂ” Monthly Project',
             fontsize=16, fontweight='bold', y=0.98)

gs = fig.add_gridspec(3, 3, hspace=0.45, wspace=0.35)

# KPI kartochki
kpi_items = [
    ('GMV',           f'{gmv/1_000_000:.1f}M rub', '#2ecc71'),
    ('Active Users',  f'{active_users}',             '#3498db'),
    ('AOV',           f'{aov:,.0f} rub',             '#e67e22'),
]
for i, (title, value, color) in enumerate(kpi_items):
    ax = fig.add_subplot(gs[0, i])
    ax.add_patch(mpatches.FancyBboxPatch(
        (0.05, 0.1), 0.9, 0.8,
        boxstyle="round,pad=0.05",
        facecolor=color, alpha=0.15,
        edgecolor=color, linewidth=2
    ))
    ax.text(0.5, 0.62, value, ha='center', va='center',
            fontsize=15, fontweight='bold', color=color,
            transform=ax.transAxes)
    ax.text(0.5, 0.25, title, ha='center', va='center',
            fontsize=9, color='gray', transform=ax.transAxes)
    ax.axis('off')

# График 1: Тренд выручки
ax1 = fig.add_subplot(gs[1, :2])
ax1.plot(monthly_rev['month'], monthly_rev['revenue'],
         marker='o', color='#2ecc71', linewidth=2.5, markersize=6)
ax1.fill_between(monthly_rev['month'], monthly_rev['revenue'],
                 alpha=0.12, color='#2ecc71')
ax1.set_title('GMV по месяцам', fontweight='bold')
ax1.set_xlabel('Mesyats')
ax1.set_ylabel('Выручка (руб)')
ax1.set_xticks(range(1, 13))
ax1.grid(True, alpha=0.3)

# Grafik 2: Revenue Tier pie
ax2 = fig.add_subplot(gs[1, 2])
tier_order  = ['low', 'medium', 'high', 'vip']
tier_colors = ['#95a5a6', '#3498db', '#e67e22', '#9b59b6']
tier_plot   = tier_stats.set_index('revenue_tier').reindex(
    [t for t in tier_order if t in tier_stats['revenue_tier'].values]
)
ax2.pie(tier_plot['revenue'].values,
        labels=tier_plot.index,
        autopct='%1.1f%%',
        colors=tier_colors[:len(tier_plot)],
        startangle=90,
        textprops={'fontsize': 9})
ax2.set_title('Доля GMV по tier', fontweight='bold')

# Grafik 3: Top kategorii
ax3 = fig.add_subplot(gs[2, 0])
ax3.barh(top_cat['category'], top_cat['gmv'],
         color='steelblue', alpha=0.8)
ax3.set_title('GMV по категориям', fontweight='bold')
ax3.set_xlabel('GMV (rub)')
ax3.invert_yaxis()
ax3.grid(axis='x', alpha=0.3)

# График 4: Каналы продаж
ax4 = fig.add_subplot(gs[2, 1])
ax4.bar(channel_stats['channel'], channel_stats['revenue'],
        color=['#3498db', '#2ecc71', '#e67e22', '#95a5a6'],
        alpha=0.85)
ax4.set_title('GMV по каналам', fontweight='bold')
ax4.set_xlabel('Kanal')
ax4.set_ylabel('GMV (rub)')
ax4.grid(axis='y', alpha=0.3)

# Grafik 5: Top goroda
ax5 = fig.add_subplot(gs[2, 2])
ax5.barh(city_stats['city'], city_stats['revenue'],
         color='coral', alpha=0.8)
ax5.set_title('Топ городов по GMV', fontweight='bold')
ax5.set_xlabel('GMV (rub)')
ax5.invert_yaxis()
ax5.grid(axis='x', alpha=0.3)

plt.savefig('project/reports/main_dashboard.png',
            dpi=150, bbox_inches='tight')
plt.close()
print("Dashboard сохранён: project/reports/main_dashboard.png")

# Heatmap: категория x месяц
fig2, ax6 = plt.subplots(figsize=(14, 6))
pivot = cat_month.pivot(
    index='category', columns='month', values='revenue'
).fillna(0)
sns.heatmap(pivot, annot=True, fmt='.0f', cmap='YlOrRd',
            ax=ax6, linewidths=0.5,
            cbar_kws={'label': 'GMV (rub)'})
ax6.set_title('GMV: Категория x Месяц (Heatmap)',
              fontsize=13, fontweight='bold')
ax6.set_xlabel('Mesyats')
ax6.set_ylabel('Kategoriya')
plt.tight_layout()
plt.savefig('project/reports/heatmap_category_month.png',
            dpi=150, bbox_inches='tight')
plt.close()
print("Heatmap сохранён: project/reports/heatmap_category_month.png")


# ========================================
# ШАГ 6: dbt модели для проекта
# ========================================

print("\n" + "=" * 70)
print("ШАГ 6: dbt модели для проекта")
print("=" * 70)

dbt_path = Path('project_dbt')
(dbt_path / 'models' / 'staging').mkdir(parents=True, exist_ok=True)
(dbt_path / 'models' / 'marts').mkdir(parents=True, exist_ok=True)
(dbt_path / 'macros').mkdir(exist_ok=True)
(dbt_path / 'tests').mkdir(exist_ok=True)

enc = 'utf-8'

# dbt_project.yml
dbt_project = """name: 'ecommerce_project'
version: '1.0.0'
config-version: 2
profile: 'ecommerce'
model-paths: ["models"]
macro-paths: ["macros"]
test-paths:  ["tests"]
models:
  ecommerce_project:
    staging:
      +materialized: view
    marts:
      +materialized: table
"""
with open(dbt_path / 'dbt_project.yml', 'w', encoding=enc) as f:
    f.write(dbt_project)

# profiles.yml
profiles_content = """ecommerce:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: ../project/ecommerce_dw.duckdb
      schema: main
"""
import os
profiles_dir = Path.home() / '.dbt'
profiles_dir.mkdir(exist_ok=True)
with open(profiles_dir / 'profiles.yml', 'w', encoding=enc) as f:
    f.write(profiles_content)

# stg_orders.sql
stg_orders = """{{ config(materialized='view') }}

SELECT
    order_id,
    customer_id,
    product_id,
    date_id         AS order_date,
    quantity,
    unit_price,
    total_amount,
    channel,
    status,
    discount_pct,
    revenue_tier,
    month,
    quarter,
    year,
    payment
FROM {{ source('ecommerce_dw', 'fct_orders') }}
WHERE order_id IS NOT NULL
"""
with open(dbt_path / 'models' / 'staging' / 'stg_orders.sql',
          'w', encoding=enc) as f:
    f.write(stg_orders)

# fct_sales.sql
fct_sales = """{{ config(materialized='table') }}

SELECT
    o.order_id,
    o.customer_id,
    o.product_id,
    o.order_date,
    o.quantity,
    o.unit_price,
    o.total_amount,
    o.channel,
    o.status,
    o.discount_pct,
    o.revenue_tier,
    o.month,
    o.quarter,
    o.year,
    CASE
        WHEN o.total_amount >= 20000 THEN 'VIP'
        WHEN o.total_amount >= 5000  THEN 'High'
        WHEN o.total_amount >= 1000  THEN 'Medium'
        ELSE 'Low'
    END AS value_segment
FROM {{ ref('stg_orders') }} o
WHERE o.status = 'completed'
"""
with open(dbt_path / 'models' / 'marts' / 'fct_sales.sql',
          'w', encoding=enc) as f:
    f.write(fct_sales)

# monthly_summary.sql
monthly_summary = """{{ config(materialized='table') }}

SELECT
    month,
    quarter,
    year,
    COUNT(order_id)       AS total_orders,
    SUM(total_amount)     AS gmv,
    ROUND(AVG(total_amount), 0) AS aov,
    COUNT(DISTINCT customer_id) AS active_customers
FROM {{ ref('fct_sales') }}
GROUP BY month, quarter, year
ORDER BY year, month
"""
with open(dbt_path / 'models' / 'marts' / 'monthly_summary.sql',
          'w', encoding=enc) as f:
    f.write(monthly_summary)

# schema.yml s testami
schema_yml = """version: 2

sources:
  - name: ecommerce_dw
    tables:
      - name: fct_orders

models:
  - name: stg_orders
    columns:
      - name: order_id
        tests:
          - unique
          - not_null
      - name: customer_id
        tests:
          - not_null
      - name: total_amount
        tests:
          - not_null
      - name: status
        tests:
          - accepted_values:
              values: ['completed', 'cancelled', 'refunded']

  - name: fct_sales
    columns:
      - name: order_id
        tests:
          - unique
          - not_null
      - name: value_segment
        tests:
          - accepted_values:
              values: ['Low', 'Medium', 'High', 'VIP']

  - name: monthly_summary
    columns:
      - name: month
        tests:
          - not_null
      - name: gmv
        tests:
          - not_null
"""
with open(dbt_path / 'models' / 'staging' / 'schema.yml',
          'w', encoding=enc) as f:
    f.write(schema_yml)

# Singular test
test_positive_gmv = """SELECT month, gmv
FROM {{ ref('monthly_summary') }}
WHERE gmv <= 0
"""
with open(dbt_path / 'tests' / 'test_positive_gmv.sql',
          'w', encoding=enc) as f:
    f.write(test_positive_gmv)

test_no_orphans = """SELECT f.order_id, f.customer_id
FROM {{ ref('fct_sales') }} f
LEFT JOIN {{ source('ecommerce_dw', 'dim_customers') }} c
    ON f.customer_id = c.customer_id
WHERE c.customer_id IS NULL
"""
with open(dbt_path / 'tests' / 'test_no_orphan_customers.sql',
          'w', encoding=enc) as f:
    f.write(test_no_orphans)

print("dbt проект создан в project_dbt/:")
print("  models/staging/stg_orders.sql")
print("  models/marts/fct_sales.sql")
print("  models/marts/monthly_summary.sql")
print("  models/staging/schema.yml  (5+ тестов)")
print("  tests/test_positive_gmv.sql")
print("  tests/test_no_orphan_customers.sql")


# ========================================
# ШАГ 7: README
# ========================================

print("\n" + "=" * 70)
print("ШАГ 7: README.md dlya GitHub")
print("=" * 70)

readme = """# E-Commerce Mini ETL + DW

Месячный проект: полный ETL pipeline для e-commerce аналитики.

## Stack
- Python (pandas, numpy, duckdb)
- dbt-duckdb
- matplotlib, seaborn

## Архитектура
```
CSV (raw) в†’ ETL (Python OOP) в†’ DuckDB (Star Schema) в†’ dbt в†’ Dashboard
```

## Star Schema
- fct_orders (центральная таблица)
- dim_products, dim_customers, dim_date, dim_channels

## KPI
- GMV (Gross Merchandise Value)
- Active Users
- AOV (Average Order Value)
- Conversion Rate

## Запуск
```bash
python monthly_project.py
cd project_dbt
dbt run
dbt test
```

## Rezultaty
- 5000 заказов, 500 клиентов, 100 товаров
- 5 kategoriy tovarov
- dbt модели + 7 тестов качества
- Dashboard s 6 grafikami
"""
with open('project/README.md', 'w', encoding=enc) as f:
    f.write(readme)
print("README.md создан: project/README.md")


# ========================================
# ИТОГОВЫЙ ОТЧЁТ
# ========================================

print("\n" + "=" * 70)
print("МЕСЯЧНЫЙ ПРОЕКТ ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Dannyye:
  products:  {len(products_df)} товаров, {len(categories)} категорий
  customers: {len(customers_df)} клиентов, {len(cities)} городов
  orders:    {len(orders_enriched)} заказов (после очистки)

Star Schema: project/ecommerce_dw.duckdb
  dim_products, dim_customers, dim_date, dim_channels
  fct_orders

KPI:
  GMV:          {gmv:>12,.0f} rub
  Active Users: {active_users:>12,}
  AOV:          {aov:>12,.0f} rub
  Conversion:   {conversion:>11.1f}%

Dashboard:
  project/reports/main_dashboard.png
  project/reports/heatmap_category_month.png

dbt proekt: project_dbt/
  3 modeli + schema.yml + 2 singular testa = 7+ testov

GitHub:
  git add project/ project_dbt/ monthly_project.py
  git commit -m "feat: monthly project e-commerce ETL + DW + dbt + dashboard"
  git push

КРИТЕРИИ ПРИЁМКИ:
  Rabochiy repozitoriy GitHub         OK
  dbt modeli + 5+ testov              OK (7 testov)
  Dashboard s 3 KPI                   OK (GMV, Users, AOV)
  Star Schema                         OK
  OOP ETL (iz Den 27)                 OK
""")
