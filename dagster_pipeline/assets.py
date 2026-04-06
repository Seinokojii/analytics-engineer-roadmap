# dagster_pipeline/assets.py
# Days 61-65: Software-Defined Assets
# [[Dagster]] [[DuckDB]] [[ETL Pipeline]]

import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, date, timedelta
import random

from dagster import (
    asset, multi_asset, AssetOut, Output,
    MetadataValue, AssetExecutionContext,
    MaterializeResult,
)

random.seed(42)
np.random.seed(42)

DATA_DIR = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)
DB_PATH  = Path(__file__).parent / 'analytics.duckdb'


def get_con(read_only: bool = False):
    return duckdb.connect(str(DB_PATH), read_only=read_only)


# ── Day 61: Pervyy @asset s metadata ─────────────────

@asset(
    group_name='ingestion',
    kinds={'python', 'csv'},
    description='Generiruet i zagruzhaet raw_orders CSV',
)
def raw_orders(context: AssetExecutionContext) -> Output:
    n = 1000
    cities  = ['MOSCOW', 'SPB', 'KAZAN', 'NOVOSIBIRSK', 'YEKATERINBURG']
    df = pd.DataFrame({
        'order_id':   range(1, n + 1),
        'user_id':    np.random.randint(1, 101, n),
        'amount':     np.round(np.random.uniform(10, 5000, n), 2),
        'status':     np.random.choice(['completed', 'pending', 'cancelled'], n,
                                       p=[0.7, 0.2, 0.1]),
        'city':       np.random.choice(cities, n),
        'order_date': [
            date(2024, 1, 1) + timedelta(days=random.randint(0, 364))
            for _ in range(n)
        ],
    })

    csv_path = DATA_DIR / 'raw_orders.csv'
    df.to_csv(csv_path, index=False)

    context.log.info(f'Generated {n} orders -> {csv_path}')

    return Output(
        value=df,
        metadata={
            'row_count':  len(df),
            'file_size':  csv_path.stat().st_size,
            'timestamp':  str(datetime.now()),
            'cities':     MetadataValue.json(list(df['city'].unique())),
            'preview':    MetadataValue.md(df.head(3).to_markdown()),
        }
    )


@asset(
    group_name='ingestion',
    kinds={'python', 'csv'},
    description='Generiruet raw_users CSV',
)
def raw_users(context: AssetExecutionContext) -> Output:
    channels = ['organic', 'paid', 'referral', 'social']
    cities   = ['MOSCOW', 'SPB', 'KAZAN', 'NOVOSIBIRSK', 'YEKATERINBURG']
    n = 100
    df = pd.DataFrame({
        'user_id':   range(1, n + 1),
        'email':     [f'user{i}@example.com' for i in range(1, n + 1)],
        'city':      np.random.choice(cities, n),
        'channel':   np.random.choice(channels, n, p=[0.4, 0.3, 0.2, 0.1]),
        'created_at': [
            date(2023, 1, 1) + timedelta(days=random.randint(0, 364))
            for _ in range(n)
        ],
    })

    csv_path = DATA_DIR / 'raw_users.csv'
    df.to_csv(csv_path, index=False)

    return Output(
        value=df,
        metadata={
            'row_count': len(df),
            'file_size': csv_path.stat().st_size,
            'timestamp': str(datetime.now()),
        }
    )


# ── Day 63: Deps chain: raw -> stg -> fct ────────────

@asset(
    deps=['raw_orders'],
    group_name='staging',
    kinds={'duckdb'},
    description='Ochishchaet raw_orders: tolko completed, amount > 0',
)
def stg_orders(context: AssetExecutionContext) -> Output:
    con = get_con()
    con.execute("""
        CREATE OR REPLACE TABLE stg_orders AS
        SELECT
            order_id,
            user_id,
            ROUND(amount, 2) AS amount,
            city,
            order_date::DATE AS order_date
        FROM read_csv_auto('{csv}')
        WHERE status = 'completed'
          AND amount > 0
    """.replace('{csv}', str(DATA_DIR / 'raw_orders.csv')))

    cnt = con.execute('SELECT COUNT(*) FROM stg_orders').fetchone()[0]
    con.close()

    context.log.info(f'stg_orders: {cnt} rows (completed only)')

    return Output(
        value=cnt,
        metadata={
            'row_count': cnt,
            'filter':    'status=completed AND amount>0',
            'timestamp': str(datetime.now()),
        }
    )


@asset(
    deps=['raw_users'],
    group_name='staging',
    kinds={'duckdb'},
    description='Ochishchaet raw_users: LOWER email, UPPER city',
)
def stg_users(context: AssetExecutionContext) -> Output:
    con = get_con()
    con.execute("""
        CREATE OR REPLACE TABLE stg_users AS
        SELECT
            user_id,
            LOWER(TRIM(email))  AS email,
            UPPER(city)         AS city,
            channel,
            created_at::DATE    AS created_at
        FROM read_csv_auto('{csv}')
        WHERE email IS NOT NULL
    """.replace('{csv}', str(DATA_DIR / 'raw_users.csv')))

    cnt = con.execute('SELECT COUNT(*) FROM stg_users').fetchone()[0]
    con.close()

    return Output(value=cnt, metadata={'row_count': cnt})


@asset(
    deps=['stg_orders', 'stg_users'],
    group_name='marts',
    kinds={'duckdb'},
    description='Fact table: orders JOIN users, biznes-metriki',
)
def fct_orders(context: AssetExecutionContext) -> Output:
    con = get_con()
    con.execute("""
        CREATE OR REPLACE TABLE fct_orders AS
        SELECT
            o.order_id,
            o.user_id,
            u.email,
            o.city,
            u.channel,
            o.amount,
            o.order_date
        FROM stg_orders o
        LEFT JOIN stg_users u ON o.user_id = u.user_id
    """)

    stats = con.execute("""
        SELECT
            COUNT(*)          AS row_count,
            ROUND(SUM(amount),2)  AS total_revenue,
            ROUND(AVG(amount),2)  AS avg_order_value
        FROM fct_orders
    """).fetchone()
    con.close()

    context.log.info(f'fct_orders: {stats[0]} rows | revenue={stats[1]}')

    return Output(
        value=stats[0],
        metadata={
            'row_count':          stats[0],
            'total_revenue':      stats[1],
            'avg_order_value':    stats[2],
            'timestamp':          str(datetime.now()),
        }
    )


# ── Day 63: @multi_asset ──────────────────────────────

@multi_asset(
    deps=['stg_orders', 'stg_users'],
    outs={
        'dim_customers': AssetOut(
            group_name='marts',
            kinds={'duckdb'},
            description='Dimension: klienty s aggregatami',
        ),
        'dim_dates': AssetOut(
            group_name='marts',
            kinds={'duckdb'},
            description='Date dimension: 2023-2025',
        ),
    }
)
def build_dimensions(context: AssetExecutionContext):
    con = get_con()

    # dim_customers
    con.execute("""
        CREATE OR REPLACE TABLE dim_customers AS
        SELECT
            u.user_id,
            u.email,
            u.city,
            u.channel,
            COUNT(o.order_id)       AS total_orders,
            ROUND(SUM(o.amount),2)  AS total_spent,
            ROUND(AVG(o.amount),2)  AS avg_order_value,
            MAX(o.order_date)       AS last_order_date
        FROM stg_users u
        LEFT JOIN stg_orders o ON u.user_id = o.user_id
        GROUP BY u.user_id, u.email, u.city, u.channel
    """)

    # dim_dates
    con.execute("""
        CREATE OR REPLACE TABLE dim_dates AS
        SELECT
            gs::DATE                    AS date_day,
            EXTRACT(YEAR  FROM gs::DATE) AS year,
            EXTRACT(MONTH FROM gs::DATE) AS month,
            EXTRACT(DOW   FROM gs::DATE) AS day_of_week,
            CASE EXTRACT(DOW FROM gs::DATE)
                WHEN 0 THEN 'Sunday'
                WHEN 1 THEN 'Monday'
                WHEN 2 THEN 'Tuesday'
                WHEN 3 THEN 'Wednesday'
                WHEN 4 THEN 'Thursday'
                WHEN 5 THEN 'Friday'
                WHEN 6 THEN 'Saturday'
            END                          AS day_name
        FROM GENERATE_SERIES(
            DATE '2023-01-01',
            DATE '2025-12-31',
            INTERVAL '1 day'
        ) t(gs)
    """)

    c_cnt = con.execute('SELECT COUNT(*) FROM dim_customers').fetchone()[0]
    d_cnt = con.execute('SELECT COUNT(*) FROM dim_dates').fetchone()[0]
    con.close()

    context.log.info(f'dim_customers={c_cnt} | dim_dates={d_cnt}')

    yield Output(c_cnt, output_name='dim_customers',
                 metadata={'row_count': c_cnt})
    yield Output(d_cnt, output_name='dim_dates',
                 metadata={'row_count': d_cnt})
