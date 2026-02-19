"""
День 17: dbt - Data Build Tool основы
Трансформации как код с тестами и документацией
"""

import subprocess
import os
from pathlib import Path

print("=" * 70)
print(" " * 15 + "🔧 ДЕНЬ 17: DBT ОСНОВЫ")
print("=" * 70)

# ========================================
# ЧАСТЬ 1: SETUP DBT PROJECT
# ========================================

print("\n" + "=" * 70)
print("📦 ЧАСТЬ 1: Создание dbt проекта")
print("=" * 70)

# Проверяем установку dbt
try:
    result = subprocess.run(['dbt', '--version'], capture_output=True, text=True)
    print("✅ dbt установлен:")
    print(result.stdout)
except FileNotFoundError:
    print("❌ dbt не установлен!")
    print("Установите: pip install dbt-core dbt-duckdb")
    exit(1)

# Создаем структуру проекта вручную (упрощенная версия)
project_path = Path('dbt_analytics')
if not project_path.exists():
    print(f"\n📁 Создаем проект: {project_path}")
    
    # Создаем структуру папок
    (project_path / 'models' / 'staging').mkdir(parents=True, exist_ok=True)
    (project_path / 'models' / 'marts').mkdir(parents=True, exist_ok=True)
    (project_path / 'data').mkdir(parents=True, exist_ok=True)
    (project_path / 'tests').mkdir(parents=True, exist_ok=True)
    
    # dbt_project.yml
    dbt_project_yml = """
name: 'analytics_project'
version: '1.0.0'
config-version: 2

profile: 'analytics'

model-paths: ["models"]
seed-paths: ["data"]
test-paths: ["tests"]

models:
  analytics_project:
    staging:
      +materialized: view
    marts:
      +materialized: table
"""
    
    with open(project_path / 'dbt_project.yml', 'w', encoding='utf-8') as f:
        f.write(dbt_project_yml.strip())
    
    # profiles.yml (DuckDB)
    profiles_yml = """
analytics:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: analytics.duckdb
      schema: main
"""
    
    profiles_path = Path.home() / '.dbt'
    profiles_path.mkdir(exist_ok=True)
    
    with open(profiles_path / 'profiles.yml', 'w', encoding='utf-8') as f:
        f.write(profiles_yml.strip())
    
    print("✅ Структура проекта создана")
    print("✅ profiles.yml настроен для DuckDB")

else:
    print(f"✅ Проект уже существует: {project_path}")


# ========================================
# ЧАСТЬ 2: СОЗДАНИЕ SEED DATA
# ========================================

print("\n" + "=" * 70)
print("🌱 ЧАСТЬ 2: Seed data (исходные данные)")
print("=" * 70)

import pandas as pd
import numpy as np

# Создаем тестовые данные
np.random.seed(42)

users_seed = pd.DataFrame({
    'user_id': range(1, 101),
    'user_name': [f'User_{i}' for i in range(1, 101)],
    'email': [f'user{i}@test.com' for i in range(1, 101)],
    'city': np.random.choice(['Moscow', 'SPB', 'Kazan'], 100),
    'created_at': pd.date_range('2024-01-01', periods=100, freq='D')  # D = days
})

orders_seed = pd.DataFrame({
    'order_id': range(1, 501),
    'user_id': np.random.randint(1, 101, 500),
    'amount': np.random.randint(100, 5000, 500),
    'status': np.random.choice(['completed', 'pending', 'cancelled'], 500, p=[0.7, 0.2, 0.1]),
    'created_at': pd.date_range('2024-01-01', periods=500, freq='3h')  # h = hours (lowercase!)
})

# Сохраняем как seeds
users_seed.to_csv(project_path / 'data' / 'raw_users.csv', index=False, encoding='utf-8')
orders_seed.to_csv(project_path / 'data' / 'raw_orders.csv', index=False, encoding='utf-8')

print("✅ Создано:")
print(f"  - raw_users.csv ({len(users_seed)} строк)")
print(f"  - raw_orders.csv ({len(orders_seed)} строк)")


# ========================================
# ЧАСТЬ 3: STAGING MODELS
# ========================================

print("\n" + "=" * 70)
print("🏗️ ЧАСТЬ 3: Staging Models (очистка данных)")
print("=" * 70)

# stg_users.sql
stg_users_sql = """
-- Staging: Очистка и стандартизация пользователей
SELECT 
    user_id,
    LOWER(TRIM(user_name)) AS user_name,
    LOWER(TRIM(email)) AS email,
    UPPER(city) AS city,
    created_at::TIMESTAMP AS created_at
FROM {{ ref('raw_users') }}
WHERE email IS NOT NULL
  AND email LIKE '%@%'
"""

with open(project_path / 'models' / 'staging' / 'stg_users.sql', 'w', encoding='utf-8') as f:
    f.write(stg_users_sql.strip())

# stg_orders.sql
stg_orders_sql = """
-- Staging: Фильтрация только completed заказов
SELECT 
    order_id,
    user_id,
    amount,
    status,
    created_at::TIMESTAMP AS created_at
FROM {{ ref('raw_orders') }}
WHERE status = 'completed'
  AND amount > 0
"""

with open(project_path / 'models' / 'staging' / 'stg_orders.sql', 'w', encoding='utf-8') as f:
    f.write(stg_orders_sql.strip())

print("✅ Созданы staging модели:")
print("  - stg_users.sql (очистка пользователей)")
print("  - stg_orders.sql (фильтрация заказов)")


# ========================================
# ЧАСТЬ 4: MARTS MODELS
# ========================================

print("\n" + "=" * 70)
print("📊 ЧАСТЬ 4: Marts Models (бизнес-логика)")
print("=" * 70)

# fct_orders.sql
fct_orders_sql = """
-- Fact table: Заказы с информацией о пользователях
SELECT 
    o.order_id,
    o.user_id,
    u.user_name,
    u.city,
    o.amount,
    o.created_at AS order_date
FROM {{ ref('stg_orders') }} o
LEFT JOIN {{ ref('stg_users') }} u ON o.user_id = u.user_id
"""

with open(project_path / 'models' / 'marts' / 'fct_orders.sql', 'w', encoding='utf-8') as f:
    f.write(fct_orders_sql.strip())

# dim_customers.sql
dim_customers_sql = """
-- Dimension table: Агрегация по клиентам
SELECT 
    u.user_id,
    u.user_name,
    u.email,
    u.city,
    u.created_at AS registration_date,
    COUNT(o.order_id) AS total_orders,
    COALESCE(SUM(o.amount), 0) AS total_spent,
    COALESCE(AVG(o.amount), 0) AS avg_order_value,
    MAX(o.created_at) AS last_order_date
FROM {{ ref('stg_users') }} u
LEFT JOIN {{ ref('stg_orders') }} o ON u.user_id = o.user_id
GROUP BY u.user_id, u.user_name, u.email, u.city, u.created_at
"""

with open(project_path / 'models' / 'marts' / 'dim_customers.sql', 'w', encoding='utf-8') as f:
    f.write(dim_customers_sql.strip())

print("✅ Созданы marts модели:")
print("  - fct_orders.sql (факты заказов)")
print("  - dim_customers.sql (измерение клиентов)")


# ========================================
# ЧАСТЬ 5: SCHEMA.YML (ТЕСТЫ)
# ========================================

print("\n" + "=" * 70)
print("✅ ЧАСТЬ 5: Тесты качества данных")
print("=" * 70)

schema_yml = """
version: 2

models:
  - name: stg_users
    description: "Staging: Очищенные пользователи"
    columns:
      - name: user_id
        description: "Уникальный ID пользователя"
        tests:
          - unique
          - not_null
      - name: email
        description: "Email пользователя"
        tests:
          - not_null

  - name: stg_orders
    description: "Staging: Completed заказы"
    columns:
      - name: order_id
        description: "Уникальный ID заказа"
        tests:
          - unique
          - not_null
      - name: amount
        description: "Сумма заказа"
        tests:
          - not_null

  - name: fct_orders
    description: "Fact table: Заказы с деталями"
    columns:
      - name: order_id
        tests:
          - unique
          - not_null

  - name: dim_customers
    description: "Dimension: Агрегация по клиентам"
    columns:
      - name: user_id
        tests:
          - unique
          - not_null
"""

with open(project_path / 'models' / 'schema.yml', 'w', encoding='utf-8') as f:
    f.write(schema_yml.strip())

print("✅ Создан schema.yml с тестами:")
print("  - unique (уникальность)")
print("  - not_null (обязательность)")


# ========================================
# ЧАСТЬ 6: ЗАПУСК DBT
# ========================================

print("\n" + "=" * 70)
print("🚀 ЧАСТЬ 6: Команды для запуска dbt")
print("=" * 70)

print("""
📝 Инструкции для запуска:

1. Перейди в папку проекта:
   cd dbt_analytics

2. Загрузи seed данные:
   dbt seed

3. Запусти все модели:
   dbt run

4. Запусти тесты:
   dbt test

5. Сгенерируй документацию:
   dbt docs generate
   dbt docs serve

6. Посмотри граф зависимостей:
   (откроется в браузере после dbt docs serve)

🔍 Полезные команды:
- dbt run --select stg_users       # Запустить одну модель
- dbt test --select stg_orders     # Тесты для одной модели
- dbt run --models staging+        # Staging и все downstream
- dbt ls --select tag:daily        # Показать модели с тегом
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 17 ЗАВЕРШЕН!")
print("=" * 70)
print(f"""
Ты создал dbt проект:
1. ✅ Структура проекта (models, data, tests)
2. ✅ Seed data (raw_users.csv, raw_orders.csv)
3. ✅ Staging models (stg_users, stg_orders)
4. ✅ Marts models (fct_orders, dim_customers)
5. ✅ Тесты качества (unique, not_null)
6. ✅ Граф зависимостей (через {{ ref() }})

Проект создан в: {project_path.absolute()}

СЛЕДУЮЩИЙ ШАГ:
cd dbt_analytics
dbt seed
dbt run
dbt test

Следующий день: День 18 - dbt Advanced (documentation, macros)
""")