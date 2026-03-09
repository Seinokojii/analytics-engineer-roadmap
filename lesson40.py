# lesson40.py — День 40: Mini-project, полный ETL pipeline + тесты
# Запуск: python lesson40.py
# Тесты:  pytest lesson40.py -v

import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "great-expectations", "pytest", "-q"])

import pandas as pd
import pytest
import great_expectations as gx
from great_expectations.expectations.core import (
    ExpectTableRowCountToBeBetween,
    ExpectColumnToExist,
    ExpectColumnValuesToNotBeNull,
    ExpectColumnValuesToBeUnique,
    ExpectColumnValuesToBeBetween,
    ExpectColumnValuesToBeInSet,
)
from datetime import datetime
from typing import Optional


# ══════════════════════════════════════════════════════════════════════
# ETL-ФУНКЦИИ (из Day 38)
# ══════════════════════════════════════════════════════════════════════

def clean_orders(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.dropna(subset=['order_id'])
    df['channel'] = df['channel'].fillna('unknown')
    df['total_amount'] = pd.to_numeric(df['total_amount'], errors='coerce').fillna(0.0)
    df = df[df['total_amount'] >= 0]
    return df.reset_index(drop=True)


def calculate_revenue_metrics(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby('channel', as_index=False)
        .agg(total_revenue=('total_amount', 'sum'), order_count=('order_id', 'count'))
        .assign(avg_order_value=lambda x: (x['total_revenue'] / x['order_count']).round(2))
        .sort_values('total_revenue', ascending=False)
        .reset_index(drop=True)
    )


def add_revenue_tier(df: pd.DataFrame) -> pd.DataFrame:
    def _tier(v):
        if v < 1000: return 'low'
        elif v < 5000: return 'medium'
        else: return 'high'
    df = df.copy()
    df['revenue_tier'] = df['total_amount'].apply(_tier)
    return df


def join_customers(orders: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    result = orders.merge(customers, on='customer_id', how='left')
    result['customer_name'] = result['customer_name'].fillna('Unknown')
    return result


# ══════════════════════════════════════════════════════════════════════
# GX-ВАЛИДАЦИЯ (из Day 39)
# ══════════════════════════════════════════════════════════════════════

def validate_orders(df: pd.DataFrame, raise_on_failure: bool = True) -> bool:
    context = gx.get_context(mode="ephemeral")
    ds      = context.data_sources.add_pandas("etl_source")
    asset   = ds.add_dataframe_asset("orders")
    suite   = gx.ExpectationSuite(name="orders_suite")
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
    ]:
        suite.add_expectation(exp)
    context.suites.add(suite)
    batch_def = asset.add_batch_definition_whole_dataframe("batch")
    batch     = batch_def.get_batch(batch_parameters={"dataframe": df})
    results   = batch.validate(suite)

    if not results.success and raise_on_failure:
        failed = [r.expectation_config.type for r in results.results if not r.success]
        raise ValueError(f"Data quality check failed: {failed}")
    return bool(results.success)


# ══════════════════════════════════════════════════════════════════════
# ETL PIPELINE
# ══════════════════════════════════════════════════════════════════════

class ETLPipelineError(Exception):
    pass


class OrdersETLPipeline:
    """
    ETL пайплайн: extract → validate (GX) → transform → load.

    Usage:
        pipeline = OrdersETLPipeline()
        result = pipeline.run(raw_df, customers_df)
        # result = {'cleaned': df, 'enriched': df, 'metrics': df}
    """

    def __init__(self, validate: bool = True):
        self.validate = validate
        self._log     = []

    def _record(self, step: str, msg: str, ok: bool = True):
        self._log.append({'step': step, 'msg': msg, 'ok': ok, 'ts': datetime.now().isoformat()})
        print(f"  {'✅' if ok else '❌'} [{step}] {msg}")

    def extract(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(raw_df, pd.DataFrame):
            raise ETLPipelineError("raw_df must be a pandas DataFrame")
        if len(raw_df) == 0:
            raise ETLPipelineError("raw_df is empty")
        self._record("EXTRACT", f"{len(raw_df)} строк, {len(raw_df.columns)} колонок")
        return raw_df.copy()

    def validate_input(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.validate:
            self._record("VALIDATE", "Пропущено (validate=False)")
            return df
        passed = validate_orders(df, raise_on_failure=False)
        if not passed:
            self._record("VALIDATE", "GX FAILED — данные не прошли контракт", ok=False)
            raise ETLPipelineError("Input data failed GX validation")
        self._record("VALIDATE", "GX passed")
        return df

    def transform(self, df: pd.DataFrame,
                customers: Optional[pd.DataFrame] = None) -> dict:
        cleaned  = clean_orders(df)
        self._record("TRANSFORM", f"clean_orders: {len(df)} → {len(cleaned)} строк")
        enriched = add_revenue_tier(cleaned)
        self._record("TRANSFORM", "add_revenue_tier")
        if customers is not None:
            enriched = join_customers(enriched, customers)
            self._record("TRANSFORM", "join_customers")
        metrics  = calculate_revenue_metrics(enriched)
        self._record("TRANSFORM", f"metrics: {len(metrics)} каналов")
        return {'cleaned': cleaned, 'enriched': enriched, 'metrics': metrics}

    def load(self, transformed: dict) -> dict:
        for name, df in transformed.items():
            self._record("LOAD", f"'{name}': {len(df)} строк")
        return transformed

    def run(self, raw_df: pd.DataFrame,
            customers: Optional[pd.DataFrame] = None) -> dict:
        print("\n--- ETL Pipeline Start ---")
        try:
            df          = self.extract(raw_df)
            df          = self.validate_input(df)
            transformed = self.transform(df, customers)
            result      = self.load(transformed)
            self._record("PIPELINE", "Completed successfully")
            return result
        except ETLPipelineError as e:
            self._record("PIPELINE", f"Failed: {e}", ok=False)
            raise

    @property
    def run_log(self):
        return self._log


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
        'total_amount': [500.0, 2000.0, -100.0, '8000', None],
        'status':       ['completed', 'completed', 'pending', 'completed', 'cancelled'],
    })

@pytest.fixture
def sample_customers():
    return pd.DataFrame({
        'customer_id':   [10, 20, 30],
        'customer_name': ['Alice', 'Bob', 'Charlie'],
    })


# ══════════════════════════════════════════════════════════════════════
# ТЕСТЫ — Pipeline Extract
# ══════════════════════════════════════════════════════════════════════

class TestExtract:

    def test_returns_copy_not_original(self, sample_orders):
        p = OrdersETLPipeline(validate=False)
        assert p.extract(sample_orders) is not sample_orders

    def test_raises_on_empty_df(self):
        p = OrdersETLPipeline(validate=False)
        with pytest.raises(ETLPipelineError, match="empty"):
            p.extract(pd.DataFrame())

    def test_raises_on_non_dataframe(self):
        p = OrdersETLPipeline(validate=False)
        with pytest.raises(ETLPipelineError):
            p.extract([1, 2, 3])


# ══════════════════════════════════════════════════════════════════════
# ТЕСТЫ — Pipeline Transform
# ══════════════════════════════════════════════════════════════════════

class TestTransform:

    def test_returns_three_tables(self, sample_orders):
        p = OrdersETLPipeline(validate=False)
        assert set(p.transform(sample_orders).keys()) == {'cleaned', 'enriched', 'metrics'}

    def test_enriched_has_revenue_tier(self, sample_orders):
        p = OrdersETLPipeline(validate=False)
        assert 'revenue_tier' in p.transform(sample_orders)['enriched'].columns

    def test_metrics_has_required_columns(self, sample_orders):
        p = OrdersETLPipeline(validate=False)
        cols = p.transform(sample_orders)['metrics'].columns
        assert {'channel', 'total_revenue', 'order_count', 'avg_order_value'}.issubset(cols)

    def test_with_customers_adds_name(self, sample_orders, sample_customers):
        p = OrdersETLPipeline(validate=False)
        result = p.transform(sample_orders, customers=sample_customers)
        assert 'customer_name' in result['enriched'].columns

    def test_dirty_data_cleaned(self, dirty_orders):
        p = OrdersETLPipeline(validate=False)
        result = p.transform(dirty_orders)
        assert result['cleaned']['order_id'].isna().sum() == 0
        assert (result['cleaned']['total_amount'] < 0).sum() == 0


# ══════════════════════════════════════════════════════════════════════
# ТЕСТЫ — E2E
# ══════════════════════════════════════════════════════════════════════

class TestPipelineE2E:

    def test_full_run_returns_all_tables(self, sample_orders, sample_customers):
        p = OrdersETLPipeline(validate=False)
        result = p.run(sample_orders, sample_customers)
        assert {'cleaned', 'enriched', 'metrics'}.issubset(result.keys())
        assert len(result['cleaned']) > 0

    def test_run_log_populated(self, sample_orders):
        p = OrdersETLPipeline(validate=False)
        p.run(sample_orders)
        assert len(p.run_log) > 0

    def test_raises_on_empty_input(self):
        p = OrdersETLPipeline(validate=False)
        with pytest.raises(ETLPipelineError):
            p.run(pd.DataFrame())

    def test_total_revenue_matches_source(self, sample_orders):
        p = OrdersETLPipeline(validate=False)
        result = p.run(sample_orders)
        assert result['metrics']['total_revenue'].sum() == pytest.approx(
            sample_orders['total_amount'].sum()
        )


# ══════════════════════════════════════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 70)
    print("ДЕНЬ 40: Mini-project — Полный ETL Pipeline + тест-suite")
    print("=" * 70)

    orders = pd.DataFrame({
        'order_id':     [1, 2, 3, 4, 5],
        'customer_id':  [10, 20, 10, 30, 20],
        'channel':      ['web', 'mobile', 'web', 'email', 'mobile'],
        'total_amount': [500.0, 2000.0, 1500.0, 8000.0, 300.0],
        'status':       ['completed', 'completed', 'pending', 'completed', 'cancelled'],
    })
    customers = pd.DataFrame({
        'customer_id':   [10, 20, 30],
        'customer_name': ['Alice', 'Bob', 'Charlie'],
    })

    pipeline = OrdersETLPipeline(validate=False)
    result   = pipeline.run(orders, customers)

    print(f"\nМетрики по каналам:\n{result['metrics'].to_string(index=False)}")
    print(f"\nОбогащённые заказы:\n{result['enriched'][['order_id','customer_name','revenue_tier']].to_string(index=False)}")

    print("\n🧪 Запуск тестов...")
    subprocess.run([sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"])