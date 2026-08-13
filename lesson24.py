"""
День 24: BI основы визуализации
matplotlib + seaborn + подготовка данных для Power BI
"""

import pandas as pd
import numpy as np
import duckdb
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
from pathlib import Path

print("=" * 70)
print(" " * 15 + "ДЕНЬ 24: BI ОСНОВЫ ВИЗУАЛИЗАЦИИ")
print("=" * 70)


# ========================================
# ЧАСТЬ 1: ПОДГОТОВКА ДАННЫХ ИЗ DBT
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Загрузка данных из dbt/DuckDB")
print("=" * 70)

# Подключаемся к нашей dbt базе
dbt_db_path = Path('dbt_analytics') / 'analytics.duckdb'

if dbt_db_path.exists():
    con = duckdb.connect(str(dbt_db_path), read_only=True)
    print(f"Подключились к: {dbt_db_path}")

    tables = con.execute("SHOW TABLES").df()
    print(f"Таблицы в базе:")
    for t in tables['name'].tolist():
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} strok")

    # Загрузка моделей
    fct_orders = con.execute("SELECT * FROM fct_orders_enriched").df()
    dim_customers = con.execute("SELECT * FROM dim_customers").df()
    con.close()
    print(f"\nfct_orders_enriched: {len(fct_orders)} strok")
    print(f"dim_customers: {len(dim_customers)} strok")

else:
    print("dbt база не найдена, создаём demo-данные")
    np.random.seed(42)
    N = 500
    fct_orders = pd.DataFrame({
        'order_id':     range(1, N + 1),
        'user_id':      np.random.randint(1, 101, N),
        'amount':       np.random.randint(100, 5000, N),
        'status':       np.random.choice(['completed'], N),
        'revenue_tier': np.random.choice(
            ['low', 'medium', 'high', 'vip'], N, p=[0.4, 0.35, 0.2, 0.05]
        ),
        'order_month':  np.random.randint(1, 13, N),
        'order_quarter': np.random.randint(1, 5, N),
        'order_date':   pd.date_range('2024-01-01', periods=N, freq='17H')
    })
    dim_customers = pd.DataFrame({
        'user_id':      range(1, 101),
        'user_name':    [f'User_{i}' for i in range(1, 101)],
        'city':         np.random.choice(['MOSCOW', 'SPB', 'KAZAN'], 100),
        'total_orders': np.random.randint(1, 20, 100),
        'total_spent':  np.random.randint(500, 50000, 100)
    })
    print("Demo-данные созданы")


# ========================================
# ЧАСТЬ 2: KPI DASHBOARD
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: KPI — ключевые метрики")
print("=" * 70)

total_revenue    = fct_orders['amount'].sum()
total_orders     = len(fct_orders)
unique_customers = fct_orders['user_id'].nunique()
avg_order        = fct_orders['amount'].mean()

print(f"""
KPI DASHBOARD:
  Общая выручка:       {total_revenue:>12,.0f} rub
  Всего заказов:            {total_orders:>12,}
  Уникальных клиентов:      {unique_customers:>12,}
  Средний чек:             {avg_order:>12,.0f} rub
""")


# ========================================
# ЧАСТЬ 3: ВИЗУАЛИЗАЦИЯ — 4 ГРАФИКА
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: Визуализация — 4 графика")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('E-Commerce Analytics Dashboard', fontsize=16, fontweight='bold')

# --- ГРАФИК 1: Выручка по месяцам ---
ax1 = axes[0, 0]
monthly = fct_orders.groupby('order_month')['amount'].sum().reset_index()
monthly.columns = ['month', 'revenue']
ax1.bar(monthly['month'], monthly['revenue'], color='steelblue', alpha=0.8)
ax1.set_title('Выручка по месяцам')
ax1.set_xlabel('Месяц')
ax1.set_ylabel('Выручка (руб)')
ax1.set_xticks(range(1, 13))
for bar, val in zip(ax1.patches, monthly['revenue']):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1000,
             f'{val/1000:.0f}k', ha='center', va='bottom', fontsize=8)

# --- GRAFIK 2: Распределение revenue_tier ---
ax2 = axes[0, 1]
tier_counts = fct_orders['revenue_tier'].value_counts()
colors = ['#2ecc71', '#3498db', '#e67e22', '#9b59b6', '#e74c3c']
ax2.pie(tier_counts.values, labels=tier_counts.index,
        autopct='%1.1f%%', colors=colors[:len(tier_counts)], startangle=90)
ax2.set_title('Распределение по revenue tier')

# --- ГРАФИК 3: Топ-10 клиентов ---
ax3 = axes[1, 0]
top10 = dim_customers.nlargest(10, 'total_spent')[['user_name', 'total_spent']]
ax3.barh(top10['user_name'], top10['total_spent'], color='coral', alpha=0.8)
ax3.set_title('Топ-10 клиентов по выручке')
ax3.set_xlabel('Total spent (rub)')
ax3.invert_yaxis()

# --- ГРАФИК 4: Boxplot суммы заказа по tier ---
ax4 = axes[1, 1]
tiers_order = ['low', 'medium', 'high', 'vip']
tiers_data = [fct_orders[fct_orders['revenue_tier'] == t]['amount'].values
              for t in tiers_order if t in fct_orders['revenue_tier'].values]
tiers_labels = [t for t in tiers_order
                if t in fct_orders['revenue_tier'].values]
ax4.boxplot(tiers_data, labels=tiers_labels, patch_artist=True,
            boxprops=dict(facecolor='lightblue', alpha=0.7))
ax4.set_title('Сумма заказа по tier (boxplot)')
ax4.set_xlabel('Revenue Tier')
ax4.set_ylabel('Amount (rub)')

plt.tight_layout()
plt.savefig('reports/dashboard.png', dpi=150, bbox_inches='tight')
plt.close()
print("График сохранён: reports/dashboard.png")


# ========================================
# ЧАСТЬ 4: ЭКСПОРТ ДЛЯ POWER BI
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: Экспорт данных для Power BI")
print("=" * 70)

# Power BI читает CSV и Excel
fct_orders.to_csv('reports/fct_orders_for_powerbi.csv', index=False, encoding='utf-8')
dim_customers.to_csv('reports/dim_customers_for_powerbi.csv', index=False, encoding='utf-8')

# Summary для дашборда
summary = fct_orders.groupby('order_month').agg(
    orders=('order_id', 'count'),
    revenue=('amount', 'sum'),
    avg_check=('amount', 'mean'),
    customers=('user_id', 'nunique')
).reset_index()
summary['revenue'] = summary['revenue'].round(0)
summary['avg_check'] = summary['avg_check'].round(0)
summary.to_csv('reports/monthly_summary_for_powerbi.csv', index=False, encoding='utf-8')

print("Файлы для Power BI сохранены в reports/:")
print("  fct_orders_for_powerbi.csv")
print("  dim_customers_for_powerbi.csv")
print("  monthly_summary_for_powerbi.csv")

print("""
ИНСТРУКЦИЯ ПОДКЛЮЧЕНИЯ К POWER BI:
1. Skachy Power BI Desktop: https://powerbi.microsoft.com/desktop
2. Открой Power BI Desktop
3. Get Data → Text/CSV
4. Vyberi fct_orders_for_powerbi.csv
5. Load → OK
6. Повтори для dim_customers_for_powerbi.csv
7. Model View: создай связь user_id → user_id
""")


# ========================================
# ЧАСТЬ 5: SEABORN — КРАСИВЫЕ ГРАФИКИ
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: Seaborn — продвинутая визуализация")
print("=" * 70)

fig2, axes2 = plt.subplots(1, 2, figsize=(14, 5))
fig2.suptitle('Advanced Analytics', fontsize=14, fontweight='bold')

# Heatmap: vyruchka po kvartalу i tieru
ax5 = axes2[0]
pivot = fct_orders.groupby(['order_quarter', 'revenue_tier'])['amount'].sum().unstack(fill_value=0)
sns.heatmap(pivot, annot=True, fmt='.0f', cmap='Blues', ax=ax5)
ax5.set_title('Выручка: Квартал x Tier')
ax5.set_xlabel('Revenue Tier')
ax5.set_ylabel('Kvartal')

# Distribution: распределение суммы заказа
ax6 = axes2[1]
sns.histplot(fct_orders['amount'], bins=30, kde=True, ax=ax6, color='steelblue')
ax6.set_title('Распределение суммы заказа')
ax6.set_xlabel('Amount (rub)')
ax6.set_ylabel('Количество заказов')
ax6.axvline(fct_orders['amount'].mean(), color='red', linestyle='--',
            label=f"Mean: {fct_orders['amount'].mean():.0f}")
ax6.axvline(fct_orders['amount'].median(), color='orange', linestyle='--',
            label=f"Median: {fct_orders['amount'].median():.0f}")
ax6.legend()

plt.tight_layout()
plt.savefig('reports/advanced_analytics.png', dpi=150, bbox_inches='tight')
plt.close()
print("График сохранён: reports/advanced_analytics.png")


# ========================================
# ITOGI
# ========================================

print("\n" + "=" * 70)
print("ДЕНЬ 24 ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Ты создал:
1. KPI метрик из dbt/DuckDB (revenue, orders, customers, avg_check)
2. Dashboard из 4 графиков → reports/dashboard.png
3. CSV экспорт для Power BI (3 файла в reports/)
4. Seaborn heatmap + distribution → reports/advanced_analytics.png

СЛЕДУЮЩИЙ ШАГ:
python lesson24_bi_basics.py
Открой reports/dashboard.png — это твой первый dashboard!

Следующий день: День 25 — Power BI загрузка данных
""")