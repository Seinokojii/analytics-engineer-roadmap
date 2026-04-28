# dagster_dbt_pipeline/partitioned_assets.py
# Day 68-69: DailyPartitionsDefinition + Incremental asset
# [[Dagster]] [[Incremental Model]] [[DuckDB]]

import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, date, timedelta
import random

from dagster import (
    asset, Output, AssetExecutionContext,
    DailyPartitionsDefinition, BackfillPolicy,
)

random.seed(42)
np.random.seed(42)

DB_PATH = Path(__file__).parent / 'partitioned.duckdb'

# Партиции с 2024-01-01 по сегодня
daily_partitions = DailyPartitionsDefinition(
    start_date='2024-01-01',
    timezone='UTC',
)


def get_con():
    return duckdb.connect(str(DB_PATH))


# ── Инкрементальный asset по дате ────────────────────

@asset(
    partitions_def=daily_partitions,
    group_name='partitioned',
    kinds={'duckdb'},
    description='Inkrementalnyy asset: zakazy za odnu datu (1 partitsiya = 1 den)',
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=1),
)
def daily_orders(context: AssetExecutionContext) -> Output:
    partition_date = context.partition_key  # '2024-01-15'
    context.log.info(f'Processing partition: {partition_date}')

    # Генерируем данные за конкретный день
    target_date = date.fromisoformat(partition_date)
    n = random.randint(10, 50)

    df = pd.DataFrame({
        'order_id':   [f'{partition_date}_{i}' for i in range(1, n + 1)],
        'user_id':    np.random.randint(1, 101, n),
        'amount':     np.round(np.random.uniform(10, 5000, n), 2),
        'order_date': target_date,
        'city':       np.random.choice(
            ['MOSCOW', 'SPB', 'KAZAN'], n
        ),
    })

    con = get_con()
    # Создаём таблицу если нет
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_orders (
            order_id   VARCHAR,
            user_id    INTEGER,
            amount     FLOAT,
            order_date DATE,
            city       VARCHAR
        )
    """)
    # Удаляем старые данные за этот день (идемпотентность)
    con.execute(
        f"DELETE FROM daily_orders WHERE order_date = '{partition_date}'"
    )
    # Вставляем новые
    con.execute('INSERT INTO daily_orders SELECT * FROM df')

    total = con.execute('SELECT COUNT(*) FROM daily_orders').fetchone()[0]
    con.close()

    return Output(
        value=len(df),
        metadata={
            'partition_date': partition_date,
            'rows_this_partition': len(df),
            'total_rows_in_table': total,
            'revenue_today': float(df['amount'].sum().round(2)),
        }
    )


@asset(
    deps=['daily_orders'],
    partitions_def=daily_partitions,
    group_name='partitioned',
    kinds={'duckdb'},
    description='Daily revenue summary po kazdoy partitsii',
)
def daily_revenue_summary(context: AssetExecutionContext) -> Output:
    partition_date = context.partition_key

    con = get_con()
    try:
        result = con.execute(
            f"""
            SELECT
                order_date,
                COUNT(*)              AS orders,
                ROUND(SUM(amount), 2) AS revenue,
                ROUND(AVG(amount), 2) AS avg_order
            FROM daily_orders
            WHERE order_date = '{partition_date}'
            GROUP BY order_date
            """
        ).fetchone()
        con.close()

        if not result:
            return Output(0, metadata={'status': 'no data for this partition'})

        return Output(
            value=result[1],
            metadata={
                'date':     str(result[0]),
                'orders':   result[1],
                'revenue':  result[2],
                'avg_order': result[3],
            }
        )
    except Exception as e:
        con.close()
        context.log.warning(f'No data yet for {partition_date}: {e}')
        return Output(0, metadata={'status': 'table not ready'})
