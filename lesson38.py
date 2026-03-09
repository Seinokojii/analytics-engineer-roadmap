# lesson38.py — День 38: pytest для ETL
# Запуск: python lesson38.py
# Тесты:  pytest lesson38.py -v

import pandas as pd
import pytest


# ══════════════════════════════════════════════════════════════════════
# ETL-ФУНКЦИИ
# ══════════════════════════════════════════════════════════════════════

def clean_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Очищает заказы: убирает null order_id, заполняет channel, чистит суммы."""
    df = df.copy()
    df = df.dropna(subset=['order_id'])
    df['channel'] = df['channel'].fillna('unknown')
    df['total_amount'] = pd.to_numeric(df['total_amount'], errors='coerce').fillna(0.0)
    df = df[df['total_amount'] >= 0]
    return df.reset_index(drop=True)


def calculate_revenue_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Метрики выручки по каналам: total_revenue, order_count, avg_order_value."""
    return (
        df.groupby('channel', as_index=False)
        .agg(
            total_revenue=('total_amount', 'sum'),
            order_count=('order_id', 'count'),
        )
        .assign(avg_order_value=lambda x: (x['total_revenue'] / x['order_count']).round(2))
        .sort_values('total_revenue', ascending=False)
        .reset_index(drop=True)
    )


def add_revenue_tier(df: pd.DataFrame) -> pd.DataFrame:
    """Добавляет revenue_tier: low / medium / high."""
    def _tier(val):
        if val < 1000:   return 'low'
        elif val < 5000: return 'medium'
        else:            return 'high'
    df = df.copy()
    df['revenue_tier'] = df['total_amount'].apply(_tier)
    return df


def join_customers(orders: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    """LEFT JOIN заказов с клиентами. Неизвестные → 'Unknown'."""
    result = orders.merge(customers, on='customer_id', how='left')
    result['customer_name'] = result['customer_name'].fillna('Unknown')
    return result


# ══════════════════════════════════════════════════════════════════════
# ФИКСТУРЫ
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_orders():
    return pd.DataFrame({
        'order_id':     [1, 2, 3, 4, 5],
        'customer_id':  [10, 20, 10, 30, 20],
        'channel':      ['web', 'mobile', 'web', 'email', 'mobile'],
        'total_amount': [500.0, 2000.0, 1500.0, 8000.0, 300.0],
        'status':       ['completed', 'completed', 'pending', 'completed', 'cancelled'],
    })


@pytest.fixture
def dirty_orders():
    return pd.DataFrame({
        'order_id':     [1, None, 3, 4, 5],
        'customer_id':  [10, 20, 10, 30, 20],
        'channel':      ['web', 'mobile', None, 'email', 'mobile'],
        'total_amount': [500.0, 2000.0, 100.0, '8000', None],
        'status':       ['completed', 'completed', 'pending', 'completed', 'cancelled'],
    })


@pytest.fixture
def sample_customers():
    return pd.DataFrame({
        'customer_id':   [10, 20, 30],
        'customer_name': ['Alice', 'Bob', 'Charlie'],
    })


# ══════════════════════════════════════════════════════════════════════
# ТЕСТЫ
# ══════════════════════════════════════════════════════════════════════

class TestCleanOrders:

    def test_removes_null_order_id(self, dirty_orders):
        assert clean_orders(dirty_orders)['order_id'].isna().sum() == 0

    def test_fills_null_channel(self, dirty_orders):
        assert 'unknown' in clean_orders(dirty_orders)['channel'].values

    def test_removes_negative_amounts(self, dirty_orders):
        assert (clean_orders(dirty_orders)['total_amount'] < 0).sum() == 0

    def test_converts_string_amount_to_float(self, dirty_orders):
        assert clean_orders(dirty_orders)['total_amount'].dtype == float

    def test_does_not_mutate_input(self, dirty_orders):
        original_len = len(dirty_orders)
        clean_orders(dirty_orders)
        assert len(dirty_orders) == original_len

    def test_clean_data_unchanged(self, sample_orders):
        assert len(clean_orders(sample_orders)) == len(sample_orders)


class TestCalculateRevenueMetrics:

    def test_returns_expected_columns(self, sample_orders):
        cols = calculate_revenue_metrics(sample_orders).columns
        assert {'channel', 'total_revenue', 'order_count', 'avg_order_value'}.issubset(cols)

    def test_total_revenue_matches_source(self, sample_orders):
        result = calculate_revenue_metrics(sample_orders)
        assert result['total_revenue'].sum() == pytest.approx(sample_orders['total_amount'].sum())

    def test_sorted_by_revenue_desc(self, sample_orders):
        revenues = calculate_revenue_metrics(sample_orders)['total_revenue'].tolist()
        assert revenues == sorted(revenues, reverse=True)

    def test_group_count_equals_unique_channels(self, sample_orders):
        assert len(calculate_revenue_metrics(sample_orders)) == sample_orders['channel'].nunique()


@pytest.mark.parametrize("amount,expected", [
    (0,     'low'),
    (999,   'low'),
    (1000,  'medium'),
    (4999,  'medium'),
    (5000,  'high'),
    (99999, 'high'),
])
def test_revenue_tier_boundaries(amount, expected):
    df = pd.DataFrame({
        'order_id': [1], 'customer_id': [1],
        'channel': ['web'], 'total_amount': [float(amount)], 'status': ['completed'],
    })
    assert add_revenue_tier(df).loc[0, 'revenue_tier'] == expected


class TestJoinCustomers:

    def test_known_customer_gets_name(self, sample_orders, sample_customers):
        result = join_customers(sample_orders, sample_customers)
        assert (result[result['customer_id'] == 10]['customer_name'] == 'Alice').all()

    def test_unknown_customer_gets_unknown(self, sample_customers):
        orders = pd.DataFrame({
            'order_id': [99], 'customer_id': [999],
            'channel': ['web'], 'total_amount': [100.0], 'status': ['completed'],
        })
        assert join_customers(orders, sample_customers).loc[0, 'customer_name'] == 'Unknown'

    def test_no_rows_lost(self, sample_orders, sample_customers):
        assert len(join_customers(sample_orders, sample_customers)) == len(sample_orders)


# ══════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import subprocess, sys

    print("=" * 70)
    print("ДЕНЬ 38: pytest для ETL")
    print("=" * 70)

    subprocess.run([sys.executable, "-m", "pip", "install", "pytest", "pytest-cov", "-q"])

    print("\n🧪 Запуск тестов...")
    subprocess.run([
        sys.executable, "-m", "pytest", __file__,
        "-v", "--tb=short"
    ])

    print("\n📋 Быстрый демо-прогон функций:")
    orders = pd.DataFrame({
        'order_id':     [1, None, 3, 4],
        'customer_id':  [10, 20, 10, 30],
        'channel':      ['web', 'mobile', None, 'email'],
        'total_amount': [500.0, -100.0, '8000', 300.0],
        'status':       ['completed', 'completed', 'pending', 'cancelled'],
    })
    cleaned = clean_orders(orders)
    tiered  = add_revenue_tier(cleaned)
    metrics = calculate_revenue_metrics(tiered)

    print(f"\nДо clean: {len(orders)} строк → После: {len(cleaned)} строк")
    print(f"\nМетрики по каналам:\n{metrics.to_string(index=False)}")
    print(f"\nТиры выручки:\n{tiered[['order_id','total_amount','revenue_tier']].to_string(index=False)}")