# metrics_api/main.py
# FastAPI -- Single Source of Truth dlya metrik

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import duckdb
from pathlib import Path
from typing import Optional

app = FastAPI(
    title='Analytics Metrics API',
    description='Single Source of Truth. Powered by dbt Semantic Layer.',
    version='1.0.0',
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

DB_PATH = Path(__file__).parent.parent / 'dbt_analytics' / 'dev.duckdb'


def get_con():
    if not DB_PATH.exists():
        raise HTTPException(503, f'Database not found: {DB_PATH}. Run dbt run first.')
    return duckdb.connect(str(DB_PATH), read_only=True)


@app.get('/', tags=['info'])
def root():
    return {
        'service': 'Analytics Metrics API',
        'endpoints': [
            '/metrics/catalog',
            '/metrics/summary',
            '/metrics/by-city',
            '/metrics/revenue-trend',
            '/metrics/ltv-report',
        ],
    }


@app.get('/metrics/catalog', tags=['catalog'])
def catalog():
    # Katalog 8 metrik (sootvetstvuet _metrics.yml)
    return {
        'metrics': {
            'total_revenue':        'SUM(amount)',
            'order_count':          'COUNT_DISTINCT(order_id)',
            'customer_count':       'COUNT_DISTINCT(user_id)',
            'average_order_value':  'total_revenue / order_count',
            'revenue_per_customer': 'total_revenue / customer_count',
            'cumulative_revenue':   'SUM(amount) rolling',
            'ltv_simple':           'revenue_per_customer / 0.05',
            'total_customer_ltv':   'SUM(total_spent) iz dim_customers',
        }
    }


@app.get('/metrics/summary', tags=['metrics'])
def summary(
    start_date: Optional[str] = Query(None, description='YYYY-MM-DD'),
    end_date:   Optional[str] = Query(None, description='YYYY-MM-DD'),
):
    con = get_con()
    date_filter = ''
    if start_date and end_date:
        date_filter = f"AND order_date BETWEEN '{start_date}' AND '{end_date}'"
    elif start_date:
        date_filter = f"AND order_date >= '{start_date}'"

    q = (
        'SELECT '
        'ROUND(SUM(amount), 2) AS total_revenue, '
        'COUNT(DISTINCT order_id) AS order_count, '
        'COUNT(DISTINCT user_id) AS customer_count, '
        'ROUND(SUM(amount)/NULLIF(COUNT(DISTINCT order_id),0),2) AS average_order_value, '
        'ROUND(SUM(amount)/NULLIF(COUNT(DISTINCT user_id),0),2) AS revenue_per_customer, '
        'ROUND(SUM(amount)/NULLIF(COUNT(DISTINCT user_id),0)/0.05,2) AS ltv_simple '
        'FROM main.fct_orders WHERE 1=1 '
    ) + date_filter
    try:
        r = con.execute(q).fetchone()
        con.close()
        return {
            'period': {'start': start_date, 'end': end_date},
            'metrics': {
                'total_revenue':        r[0],
                'order_count':          r[1],
                'customer_count':       r[2],
                'average_order_value':  r[3],
                'revenue_per_customer': r[4],
                'ltv_simple':           r[5],
            },
        }
    except Exception as e:
        con.close()
        raise HTTPException(500, str(e))


@app.get('/metrics/by-city', tags=['metrics'])
def by_city(limit: int = Query(10, ge=1, le=100)):
    con = get_con()
    q = (
        'SELECT city, '
        'ROUND(SUM(amount),2) AS total_revenue, '
        'COUNT(DISTINCT order_id) AS order_count, '
        'COUNT(DISTINCT user_id) AS customer_count, '
        'ROUND(SUM(amount)/NULLIF(COUNT(DISTINCT order_id),0),2) AS average_order_value '
        'FROM main.fct_orders WHERE city IS NOT NULL '
        'GROUP BY city ORDER BY total_revenue DESC '
        f'LIMIT {limit}'
    )
    try:
        rows = con.execute(q).fetchall()
        cols = ['city', 'total_revenue', 'order_count',
                'customer_count', 'average_order_value']
        con.close()
        return {'data': [dict(zip(cols, r)) for r in rows]}
    except Exception as e:
        con.close()
        raise HTTPException(500, str(e))


@app.get('/metrics/revenue-trend', tags=['metrics'])
def revenue_trend(
    granularity: str = Query('month', description='day | week | month'),
    periods:     int  = Query(12, ge=1, le=36),
):
    if granularity not in ('day', 'week', 'month'):
        raise HTTPException(400, 'granularity: day | week | month')
    con = get_con()
    q = (
        f"SELECT DATE_TRUNC('{granularity}', order_date) AS period, "
        'ROUND(SUM(amount),2) AS revenue, '
        'COUNT(DISTINCT order_id) AS orders, '
        f"ROUND(SUM(SUM(amount)) OVER (ORDER BY DATE_TRUNC('{granularity}', order_date)),2) "
        'AS cumulative_revenue '
        'FROM main.fct_orders '
        f"WHERE order_date >= (SELECT MAX(order_date) - INTERVAL '{periods} {granularity}s' "
        'FROM main.fct_orders) '
        f"GROUP BY DATE_TRUNC('{granularity}', order_date) ORDER BY period"
    )
    try:
        rows = con.execute(q).fetchall()
        cols = ['period', 'revenue', 'orders', 'cumulative_revenue']
        con.close()
        return {
            'granularity': granularity,
            'data': [{**dict(zip(cols, r)), 'period': str(r[0])} for r in rows],
        }
    except Exception as e:
        con.close()
        raise HTTPException(500, str(e))


@app.get('/metrics/ltv-report', tags=['metrics'])
def ltv_report():
    con = get_con()
    q = (
        'SELECT city, '
        'COUNT(DISTINCT user_id) AS customers, '
        'ROUND(AVG(total_spent),2) AS avg_historical_ltv, '
        'ROUND(AVG(avg_order_value),2) AS avg_order_value, '
        'ROUND(AVG(total_spent/0.05),2) AS avg_predictive_ltv '
        'FROM main.dim_customers '
        'WHERE total_spent > 0 '
        'GROUP BY city ORDER BY avg_historical_ltv DESC LIMIT 10'
    )
    try:
        rows = con.execute(q).fetchall()
        cols = ['city', 'customers', 'avg_historical_ltv',
                'avg_order_value', 'avg_predictive_ltv']
        con.close()
        return {'data': [dict(zip(cols, r)) for r in rows]}
    except Exception as e:
        con.close()
        raise HTTPException(500, str(e))
