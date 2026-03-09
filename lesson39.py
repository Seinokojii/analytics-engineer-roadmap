# lesson39.py — День 39: Great Expectations
# Запуск: python lesson39.py
# Тесты:  pytest lesson39.py -v

import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "great-expectations", "pytest", "-q"])

import pandas as pd
import pytest
import great_expectations as gx



# ══════════════════════════════════════════════════════════════════════
# GX-ФУНКЦИИ
# ══════════════════════════════════════════════════════════════════════

def _build_suite() -> gx.ExpectationSuite:
    suite = gx.ExpectationSuite(name="orders_suite")
    for exp in [
        gx.expectations.ExpectTableRowCountToBeBetween(min_value=1, max_value=10_000_000),
        gx.expectations.ExpectColumnToExist(column="order_id"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="order_id"),
        gx.expectations.ExpectColumnValuesToBeUnique(column="order_id"),
        gx.expectations.ExpectColumnToExist(column="total_amount"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="total_amount"),
        gx.expectations.ExpectColumnValuesToBeBetween(column="total_amount", min_value=0),
        gx.expectations.ExpectColumnToExist(column="channel"),
        gx.expectations.ExpectColumnValuesToNotBeNull(column="channel"),
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="channel", value_set=["web", "mobile", "email", "unknown"]
        ),
        gx.expectations.ExpectColumnToExist(column="status"),
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="status", value_set=["completed", "pending", "cancelled", "refunded"]
        ),
    ]:
        suite.add_expectation(exp)
    return suite


def validate_orders(df: pd.DataFrame, raise_on_failure: bool = True) -> bool:
    context   = gx.get_context(mode="ephemeral")
    ds        = context.data_sources.add_pandas("etl_source")
    asset     = ds.add_dataframe_asset("orders")
    suite     = _build_suite()
    context.suites.add(suite)
    batch_def = asset.add_batch_definition_whole_dataframe("batch")
    batch     = batch_def.get_batch(batch_parameters={"dataframe": df})
    results   = batch.validate(suite)

    if not results.success and raise_on_failure:
        failed = [r.expectation_config.type for r in results.results if not r.success]
        raise ValueError(f"Data quality check failed: {failed}")
    return bool(results.success)




# ══════════════════════════════════════════════════════════════════════
# ФИКСТУРЫ
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def good_orders():
    return pd.DataFrame({
        'order_id':     [1, 2, 3, 4, 5],
        'customer_id':  [10, 20, 10, 30, 20],
        'channel':      ['web', 'mobile', 'web', 'email', 'mobile'],
        'total_amount': [500.0, 2000.0, 1500.0, 8000.0, 300.0],
        'status':       ['completed', 'completed', 'pending', 'completed', 'cancelled'],
    })


# ══════════════════════════════════════════════════════════════════════
# ТЕСТЫ
# ══════════════════════════════════════════════════════════════════════

class TestValidateOrders:

    def test_good_data_passes(self, good_orders):
        assert validate_orders(good_orders, raise_on_failure=False) is True

    def test_null_order_id_fails(self):
        df = pd.DataFrame({
            'order_id': [None], 'customer_id': [1],
            'channel': ['web'], 'total_amount': [100.0], 'status': ['completed'],
        })
        assert validate_orders(df, raise_on_failure=False) is False

    def test_negative_amount_fails(self):
        df = pd.DataFrame({
            'order_id': [1], 'customer_id': [1],
            'channel': ['web'], 'total_amount': [-100.0], 'status': ['completed'],
        })
        assert validate_orders(df, raise_on_failure=False) is False

    def test_invalid_channel_fails(self):
        df = pd.DataFrame({
            'order_id': [1], 'customer_id': [1],
            'channel': ['TikTok'], 'total_amount': [100.0], 'status': ['completed'],
        })
        assert validate_orders(df, raise_on_failure=False) is False

    def test_raises_value_error_when_flag_true(self):
        df = pd.DataFrame({
            'order_id': [None], 'customer_id': [1],
            'channel': ['web'], 'total_amount': [100.0], 'status': ['completed'],
        })
        with pytest.raises(ValueError):
            validate_orders(df, raise_on_failure=True)

    def test_duplicate_order_id_fails(self):
        df = pd.DataFrame({
            'order_id': [1, 1], 'customer_id': [10, 20],
            'channel': ['web', 'mobile'], 'total_amount': [100.0, 200.0],
            'status': ['completed', 'completed'],
        })
        assert validate_orders(df, raise_on_failure=False) is False


# ══════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 70)
    print("ДЕНЬ 39: Great Expectations")
    print(f"GX версия: {gx.__version__}")
    print("=" * 70)

    good = pd.DataFrame({
        'order_id':     [1, 2, 3, 4, 5],
        'customer_id':  [10, 20, 10, 30, 20],
        'channel':      ['web', 'mobile', 'web', 'email', 'mobile'],
        'total_amount': [500.0, 2000.0, 1500.0, 8000.0, 300.0],
        'status':       ['completed', 'completed', 'pending', 'completed', 'cancelled'],
    })
    bad = pd.DataFrame({
        'order_id':     [1, 1, None, 4, 5],
        'customer_id':  [10, 20, 10, 30, 20],
        'channel':      ['web', 'TikTok', 'web', 'email', None],
        'total_amount': [-100.0, 2000.0, 1500.0, 8000.0, 300.0],
        'status':       ['completed', 'completed', 'pending', 'completed', 'cancelled'],
    })

    print("\n📋 Демо-валидация:")
    r1 = validate_orders(good, raise_on_failure=False)
    r2 = validate_orders(bad,  raise_on_failure=False)
    print(f"  good_orders: {'✅ PASSED' if r1 else '❌ FAILED'}")
    print(f"  bad_orders:  {'✅ PASSED' if r2 else '❌ FAILED (ожидаемо)'}")

    print("\n🧪 Запуск тестов...")
    subprocess.run([sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"])