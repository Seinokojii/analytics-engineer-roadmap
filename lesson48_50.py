# lesson48_50.py — Дни 48-50: Data Contracts + Mini-Project
# Запуск: python lesson48_50.py

import os, textwrap, json
import pandas as pd
import duckdb
from datetime import datetime

print("=" * 70)
print("ДНИ 48-50: Data Contracts + Mini-Project")
print("=" * 70)

DBT_PROJECT = "dbt_analytics"

# ══════════════════════════════════════════════════════════════════════
# ДЕНЬ 48: Data Contracts
# ══════════════════════════════════════════════════════════════════════
print("\n" + "─" * 50)
print("ДЕНЬ 48: Data Contracts")
print("─" * 50)

# ── ЧАСТЬ 1: Data Contract как YAML-файл ──────────────────────────────────
os.makedirs("contracts", exist_ok=True)

orders_contract = textwrap.dedent("""\
    # contracts/orders_v1.yml
    # Data Contract — соглашение о структуре таблицы orders
    # Версия: 1.0.0
    # Owner: source_team@company.com
    # Consumers: analytics, data_science, finance

    contract:
      name: orders
      version: "1.0.0"
      owner: source_team@company.com
      consumers:
        - team: analytics
          contact: analytics@company.com
        - team: data_science
          contact: ds@company.com

      # SLA на свежесть данных
      freshness:
        max_delay_hours: 24
        warn_delay_hours: 12

      # Схема данных
      schema:
        - name: order_id
          type: INTEGER
          nullable: false
          unique: true
          description: "Первичный ключ заказа"

        - name: user_id
          type: INTEGER
          nullable: false
          description: "ID пользователя из системы auth"

        - name: amount
          type: FLOAT
          nullable: false
          min_value: 0
          max_value: 10000000
          description: "Сумма заказа в рублях"

        - name: status
          type: VARCHAR
          nullable: false
          allowed_values: ["completed", "pending", "cancelled", "refunded"]
          description: "Статус заказа"

        - name: created_at
          type: TIMESTAMP
          nullable: false
          description: "Дата и время создания заказа"

      # Ожидаемые объёмы
      volume:
        min_rows_per_day: 10
        max_rows_per_day: 1000000
""")

customers_contract = textwrap.dedent("""\
    # contracts/customers_v1.yml
    contract:
      name: customers
      version: "1.0.0"
      owner: crm_team@company.com
      consumers:
        - team: analytics
          contact: analytics@company.com

      schema:
        - name: customer_id
          type: INTEGER
          nullable: false
          unique: true

        - name: email
          type: VARCHAR
          nullable: false
          pattern: "^[\\\\w.+-]+@[\\\\w-]+\\\\.[\\\\w.]+$"

        - name: plan
          type: VARCHAR
          nullable: false
          allowed_values: ["free", "basic", "premium", "enterprise"]

        - name: status
          type: VARCHAR
          nullable: false
          allowed_values: ["active", "inactive", "suspended"]

        - name: updated_at
          type: TIMESTAMP
          nullable: false
""")

with open("contracts/orders_v1.yml",    "w", encoding="utf-8") as f:
    f.write(orders_contract)
with open("contracts/customers_v1.yml", "w", encoding="utf-8") as f:
    f.write(customers_contract)
print("  ✅ contracts/orders_v1.yml")
print("  ✅ contracts/customers_v1.yml")

# ── ЧАСТЬ 2: Python-валидатор контракта ───────────────────────────────────
print("\n" + "─" * 50)
print("ЧАСТЬ 2: Python-валидатор контракта")
print("─" * 50)


class DataContractValidator:
    """
    Проверяет DataFrame на соответствие Data Contract.
    Используется в ETL до загрузки данных в аналитическую БД.
    """

    def __init__(self, contract: dict):
        self.contract = contract["contract"]
        self.schema   = {col["name"]: col
                         for col in self.contract["schema"]}
        self.errors   = []
        self.warnings = []

    def validate(self, df: pd.DataFrame) -> bool:
        self.errors   = []
        self.warnings = []

        self._check_required_columns(df)
        self._check_nulls(df)
        self._check_unique(df)
        self._check_allowed_values(df)
        self._check_numeric_ranges(df)

        return len(self.errors) == 0

    def _check_required_columns(self, df):
        for col_name, col_spec in self.schema.items():
            if col_name not in df.columns:
                self.errors.append(
                    f"MISSING_COLUMN: '{col_name}' required by contract"
                )

    def _check_nulls(self, df):
        for col_name, col_spec in self.schema.items():
            if col_name not in df.columns:
                continue
            if not col_spec.get("nullable", True):
                null_count = df[col_name].isna().sum()
                if null_count > 0:
                    self.errors.append(
                        f"NULL_VIOLATION: '{col_name}' "
                        f"has {null_count} nulls (nullable=false)"
                    )

    def _check_unique(self, df):
        for col_name, col_spec in self.schema.items():
            if col_name not in df.columns:
                continue
            if col_spec.get("unique", False):
                dup_count = df[col_name].duplicated().sum()
                if dup_count > 0:
                    self.errors.append(
                        f"UNIQUE_VIOLATION: '{col_name}' "
                        f"has {dup_count} duplicates"
                    )

    def _check_allowed_values(self, df):
        for col_name, col_spec in self.schema.items():
            if col_name not in df.columns:
                continue
            allowed = col_spec.get("allowed_values")
            if allowed:
                invalid = df[~df[col_name].isin(allowed)][col_name].unique()
                if len(invalid) > 0:
                    self.errors.append(
                        f"VALUE_VIOLATION: '{col_name}' "
                        f"has invalid values: {list(invalid)}"
                    )

    def _check_numeric_ranges(self, df):
        for col_name, col_spec in self.schema.items():
            if col_name not in df.columns:
                continue
            if "min_value" in col_spec and col_name in df.columns:
                below = (df[col_name] < col_spec["min_value"]).sum()
                if below > 0:
                    self.errors.append(
                        f"RANGE_VIOLATION: '{col_name}' "
                        f"has {below} values below min={col_spec['min_value']}"
                    )
            if "max_value" in col_spec and col_name in df.columns:
                above = (df[col_name] > col_spec["max_value"]).sum()
                if above > 0:
                    self.errors.append(
                        f"RANGE_VIOLATION: '{col_name}' "
                        f"has {above} values above max={col_spec['max_value']}"
                    )

    def report(self) -> str:
        lines = [f"Contract: {self.contract['name']} v{self.contract['version']}"]
        if self.errors:
            lines.append(f"  Status: FAILED ({len(self.errors)} errors)")
            for e in self.errors:
                lines.append(f"    ❌ {e}")
        else:
            lines.append("  Status: PASSED")
        return "\n".join(lines)


# ── Тест валидатора ───────────────────────────────────────────────────────
import yaml

with open("contracts/orders_v1.yml", "r", encoding="utf-8") as f:
    orders_contract_dict = yaml.safe_load(f)

validator = DataContractValidator(orders_contract_dict)

# Хорошие данные
good_df = pd.DataFrame({
    "order_id":  [1, 2, 3, 4, 5],
    "user_id":   [10, 20, 10, 30, 20],
    "amount":    [500.0, 2000.0, 1500.0, 8000.0, 300.0],
    "status":    ["completed", "completed", "pending", "completed", "cancelled"],
    "created_at": pd.to_datetime(["2024-01-01"]*5),
})

# Плохие данные
bad_df = pd.DataFrame({
    "order_id":  [1, 1, 3, None, 5],
    "user_id":   [10, 20, 10, 30, 20],
    "amount":    [-100.0, 2000.0, 1500.0, 8000.0, 300.0],
    "status":    ["completed", "TikTok", "pending", "completed", "cancelled"],
    "created_at": pd.to_datetime(["2024-01-01"]*5),
})

print("\n  Валидация good_df:")
validator.validate(good_df)
print("  " + validator.report().replace("\n", "\n  "))

print("\n  Валидация bad_df:")
validator.validate(bad_df)
print("  " + validator.report().replace("\n", "\n  "))

# ══════════════════════════════════════════════════════════════════════
# ДЕНЬ 49: dbt contract — встроенные контракты
# ══════════════════════════════════════════════════════════════════════
print("\n" + "─" * 50)
print("ДЕНЬ 49: dbt contract в schema.yml")
print("─" * 50)

# dbt 1.5+ поддерживает contracts нативно в schema.yml
schema_with_contracts = textwrap.dedent("""\
    version: 2

    models:
      - name: fct_orders_enriched
        description: "Обогащённые заказы с тирами и статусами"

        columns:
          - name: order_id
            data_type: integer
            constraints:
              - type: not_null
              - type: unique
            data_tests:
              - not_null
              - unique

          - name: total_amount
            data_type: double
            constraints:
              - type: not_null
            data_tests:
              - not_null
              - dbt_expectations.expect_column_values_to_be_between:
                  min_value: 0
                  max_value: 1000000

          - name: revenue_tier
            data_type: varchar
            constraints:
              - type: not_null
            data_tests:
              - not_null
              - accepted_values:
                  values: ['zero', 'low', 'medium', 'high', 'vip']

          - name: order_date
            data_type: date

          - name: activity_status
            data_type: varchar

          - name: days_since_order
            data_type: bigint

          - name: unit_price_safe
            data_type: double

          - name: customer_id
            data_type: bigint

      - name: fct_orders_surrogate
        description: "Заказы с суррогатным ключом"
        columns:
          - name: order_sk
            data_tests:
              - not_null
              - unique

      - name: dim_date
        description: "Таблица дат 2023-2025"
        data_tests:
          - dbt_expectations.expect_table_row_count_to_be_between:
              min_value: 700
              max_value: 1200
        columns:
          - name: date_id
            data_tests:
              - not_null
              - unique
""")

schema_path = os.path.join(DBT_PROJECT, "models", "marts", "schema.yml")
with open(schema_path, "w", encoding="utf-8") as f:
    f.write(schema_with_contracts)
print("  ✅ models/marts/schema.yml обновлён с dbt contracts")

# ══════════════════════════════════════════════════════════════════════
# ДЕНЬ 50: Mini-Project — полный пайплайн
# ══════════════════════════════════════════════════════════════════════
print("\n" + "─" * 50)
print("ДЕНЬ 50: Mini-Project — полный пайплайн")
print("─" * 50)

# CI workflow с Data Contract проверкой
ci_with_contracts = textwrap.dedent("""\
    name: dbt CI + Data Contracts

    on:
      pull_request:
        branches: [main, dev]
        paths:
          - 'dbt_analytics/**'
          - 'contracts/**'
          - '.github/workflows/**'

    jobs:
      data-contracts:
        name: Validate Data Contracts
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: '3.12'
          - name: Install deps
            run: pip install pandas pyyaml --quiet
          - name: Validate contracts
            run: python -c "
    import yaml, sys
    import os
    contracts_dir = 'contracts'
    for f in os.listdir(contracts_dir):
        if f.endswith('.yml'):
            with open(os.path.join(contracts_dir, f)) as fp:
                contract = yaml.safe_load(fp)
            assert 'contract' in contract, f'Invalid contract: {f}'
            assert 'schema' in contract['contract'], f'No schema in: {f}'
            print(f'OK: {f}')
    "

      dbt-ci:
        name: dbt build + test
        runs-on: ubuntu-latest
        needs: data-contracts

        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: '3.12'
          - name: Install dbt
            run: pip install dbt-duckdb --quiet
          - name: dbt deps
            working-directory: dbt_analytics
            run: dbt deps
          - name: dbt build
            working-directory: dbt_analytics
            run: dbt build --target ci
          - name: dbt snapshot compile
            working-directory: dbt_analytics
            run: dbt compile --select snapshot:*
          - name: Upload logs on failure
            if: failure()
            uses: actions/upload-artifact@v4
            with:
              name: dbt-logs
              path: dbt_analytics/logs/
""")

with open(".github/workflows/dbt_ci.yml", "w", encoding="utf-8") as f:
    f.write(ci_with_contracts)
print("  ✅ .github/workflows/dbt_ci.yml обновлён с Data Contract проверкой")

# ── Итоговый запуск dbt ───────────────────────────────────────────────────
import subprocess

print("\n🚀 Финальный dbt run (Days 46-50):")
steps = [
    (["dbt", "deps"],                                      "deps"),
    (["dbt", "snapshot"],                                  "snapshot"),
    (["dbt", "run",  "--select", "dim_customers",
                                 "dim_customers_history",
                                 "fct_orders_enriched",
                                 "fct_orders_surrogate",
                                 "dim_date"],              "run models"),
    (["dbt", "test", "--select", "fct_orders_enriched"],   "test"),
    (["dbt", "docs", "generate"],                          "docs generate"),
]

for cmd, label in steps:
    r = subprocess.run(cmd, cwd=DBT_PROJECT,
                       capture_output=True, text=True)
    status = "✅" if r.returncode == 0 else "⚠️ "
    print(f"  {status} dbt {label}")
    if r.returncode != 0:
        print(f"     {r.stdout[-300:]}")

print("""
📁 ИТОГОВАЯ СТРУКТУРА (Days 46-50):

├── .github/
│   └── workflows/
│       ├── dbt_ci.yml    ← PR: contracts + dbt build + test
│       └── dbt_cd.yml    ← main: полный deploy в prod
├── contracts/
│   ├── orders_v1.yml     ← Data Contract для orders
│   └── customers_v1.yml  ← Data Contract для customers
├── requirements.txt
└── dbt_analytics/
    ├── snapshots/
    │   ├── snap_customers.sql      ← SCD Type 2 timestamp
    │   └── snap_orders_status.sql  ← SCD Type 2 check
    └── models/marts/
        ├── dim_customers.sql         ← текущее состояние
        ├── dim_customers_history.sql ← полная история

📋 ШПАРГАЛКА Data Contracts:

  YAML-контракт: contracts/model_v1.yml
    - Определяет схему, типы, ограничения, SLA

  Python-валидатор (lesson48_50.py):
    validator = DataContractValidator(contract_dict)
    passed = validator.validate(df)
    print(validator.report())

  dbt contract (schema.yml):
    config:
      contract:
        enforced: true   ← dbt проверит типы колонок при компиляции
    columns:
      - name: order_id
        data_type: integer
        constraints:
          - type: not_null

  GitHub Actions pipeline:
    PR  → validate contracts → dbt build --target ci
    main → dbt build --target prod → dbt snapshot → docs
""")

print("\n✅ Дни 46-50 завершены!")
print("🚀 Следующий блок: Days 51-55 — dbt Semantic Layer + MetricFlow")

print("""
Git:
    git add contracts/ .github/ dbt_analytics/ requirements.txt
    git add lesson46.py lesson47.py lesson48_50.py
    git commit -m "feat: days 46-50 snapshots CI/CD data contracts"
    git push
""")