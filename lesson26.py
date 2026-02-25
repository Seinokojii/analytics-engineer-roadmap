"""
День 26: Power BI — 3 визуализации
Тренд выручки, сегментация клиентов, анализ Revenue Tier
"""

import pandas as pd
import numpy as np
import duckdb
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
from pathlib import Path

# Поддержка кириллицы в matplotlib
plt.rcParams['font.family'] = 'DejaVu Sans'

print("=" * 70)
print(" " * 8 + "ДЕНЬ 26: POWER BI — 3 ВИЗУАЛИЗАЦИИ")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)


# ========================================
# ЧАСТЬ 1: ДАННЫЕ ИЗ DBT
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Загрузка данных")
print("=" * 70)

dbt_db_path = Path('dbt_analytics') / 'analytics.duckdb'

if dbt_db_path.exists():
    con = duckdb.connect(str(dbt_db_path), read_only=True)
    fct_orders    = con.execute("SELECT * FROM fct_orders_enriched").df()
    dim_customers = con.execute("SELECT * FROM dim_customers").df()
    con.close()
    print(f"Из dbt: {len(fct_orders)} заказов, {len(dim_customers)} клиентов")
else:
    np.random.seed(42)
    N = 500
    fct_orders = pd.DataFrame({
        'order_id':      range(1, N + 1),
        'user_id':       np.random.randint(1, 101, N),
        'amount':        np.random.randint(100, 5000, N),
        'revenue_tier':  np.random.choice(
            ['low', 'medium', 'high', 'vip'], N, p=[0.4, 0.35, 0.2, 0.05]
        ),
        'order_month':   np.random.randint(1, 13, N),
        'order_quarter': np.random.randint(1, 5, N),
        'order_date':    pd.date_range('2024-01-01', periods=N, freq='17H')
    })
    dim_customers = pd.DataFrame({
        'user_id':      range(1, 101),
        'user_name':    [f'Клиент_{i}' for i in range(1, 101)],
        'city':         np.random.choice(['Москва', 'СПб', 'Казань'], 100),
        'total_orders': np.random.randint(1, 20, 100),
        'total_spent':  np.random.randint(500, 50000, 100)
    })
    print("Демо-данные созданы")

# Добавляем order_month если нет
if 'order_month' not in fct_orders.columns:
    fct_orders['order_date']    = pd.to_datetime(fct_orders['order_date'])
    fct_orders['order_month']   = fct_orders['order_date'].dt.month
    fct_orders['order_quarter'] = fct_orders['order_date'].dt.quarter

# Названия месяцев на русском
months_ru = {
    1: 'Янв', 2: 'Фев', 3: 'Мар', 4: 'Апр',
    5: 'Май', 6: 'Июн', 7: 'Июл', 8: 'Авг',
    9: 'Сен', 10: 'Окт', 11: 'Ноя', 12: 'Дек'
}

# Переименовываем тиры на русский
tier_ru = {
    'low': 'Низкий',
    'medium': 'Средний',
    'high': 'Высокий',
    'vip': 'VIP'
}
if 'revenue_tier' in fct_orders.columns:
    fct_orders['tier_ru'] = fct_orders['revenue_tier'].map(tier_ru)


# ========================================
# ЧАСТЬ 2: ВИЗУАЛИЗАЦИЯ 1 — ТРЕНД ВЫРУЧКИ
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: Визуализация 1 — Тренд выручки")
print("=" * 70)

monthly = fct_orders.groupby('order_month')['amount'].sum().reset_index()
monthly.columns = ['month', 'revenue']
monthly['month_name'] = monthly['month'].map(months_ru)

quarterly = fct_orders.groupby('order_quarter')['amount'].sum().reset_index()
quarterly.columns = ['quarter', 'revenue']

fig1, axes1 = plt.subplots(1, 2, figsize=(14, 5))
fig1.suptitle('Визуализация 1: Тренд Выручки', fontsize=14, fontweight='bold')

# Line chart
ax1 = axes1[0]
ax1.plot(range(len(monthly)), monthly['revenue'],
         marker='o', color='#2ecc71', linewidth=2.5, markersize=7)
ax1.fill_between(range(len(monthly)), monthly['revenue'],
                 alpha=0.15, color='#2ecc71')

max_idx = monthly['revenue'].idxmax()
min_idx = monthly['revenue'].idxmin()
ax1.annotate(f"МАКС\n{monthly.loc[max_idx,'revenue']:,.0f}₽",
             xy=(max_idx, monthly.loc[max_idx,'revenue']),
             xytext=(0, 15), textcoords='offset points',
             ha='center', color='green', fontsize=8, fontweight='bold')
ax1.annotate(f"МИН\n{monthly.loc[min_idx,'revenue']:,.0f}₽",
             xy=(min_idx, monthly.loc[min_idx,'revenue']),
             xytext=(0, -30), textcoords='offset points',
             ha='center', color='red', fontsize=8, fontweight='bold')

ax1.set_title('Выручка по месяцам')
ax1.set_xlabel('Месяц')
ax1.set_ylabel('Выручка (₽)')
ax1.set_xticks(range(len(monthly)))
ax1.set_xticklabels(monthly['month_name'], rotation=45)
ax1.grid(True, alpha=0.3)

# Bar chart по кварталам
ax2 = axes1[1]
colors_bar = ['#3498db', '#2ecc71', '#e67e22', '#9b59b6']
bars = ax2.bar([f'Кв.{q}' for q in quarterly['quarter']],
               quarterly['revenue'],
               color=colors_bar[:len(quarterly)], alpha=0.85)

for bar, val in zip(bars, quarterly['revenue']):
    ax2.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + quarterly['revenue'].max() * 0.01,
             f'{val/1000:.1f}т₽', ha='center', va='bottom',
             fontsize=10, fontweight='bold')

ax2.set_title('Выручка по кварталам')
ax2.set_xlabel('Квартал')
ax2.set_ylabel('Выручка (₽)')
ax2.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig('reports/viz1_trend.png', dpi=150, bbox_inches='tight')
plt.close()
print("Сохранено: reports/viz1_trend.png")


# ========================================
# ЧАСТЬ 3: ВИЗУАЛИЗАЦИЯ 2 — СЕГМЕНТАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: Визуализация 2 — Сегментация клиентов")
print("=" * 70)

def get_segment(spent):
    if spent >= 30000: return 'VIP'
    elif spent >= 15000: return 'Лояльный'
    elif spent >= 5000: return 'Обычный'
    else: return 'Новый'

dim_customers['segment'] = dim_customers['total_spent'].apply(get_segment)

fig2, axes2 = plt.subplots(1, 3, figsize=(16, 5))
fig2.suptitle('Визуализация 2: Сегментация Клиентов', fontsize=14, fontweight='bold')

seg_order  = ['VIP', 'Лояльный', 'Обычный', 'Новый']
seg_colors = {
    'VIP': '#9b59b6',
    'Лояльный': '#2ecc71',
    'Обычный': '#3498db',
    'Новый': '#95a5a6'
}

# Количество клиентов
ax3 = axes2[0]
seg_counts = dim_customers['segment'].value_counts()
seg_ordered = seg_counts.reindex(
    [s for s in seg_order if s in seg_counts.index]
)
bars3 = ax3.bar(seg_ordered.index, seg_ordered.values,
                color=[seg_colors[s] for s in seg_ordered.index],
                alpha=0.85)
for bar, val in zip(bars3, seg_ordered.values):
    ax3.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + 0.3,
             str(val), ha='center', va='bottom', fontweight='bold')
ax3.set_title('Количество клиентов по сегментам')
ax3.set_xlabel('Сегмент')
ax3.set_ylabel('Клиентов')
ax3.grid(axis='y', alpha=0.3)

# Выручка по сегментам (pie)
ax4 = axes2[1]
seg_revenue = dim_customers.groupby('segment')['total_spent'].sum()
seg_rev_ordered = seg_revenue.reindex(
    [s for s in seg_order if s in seg_revenue.index]
)
ax4.pie(seg_rev_ordered.values,
        labels=seg_rev_ordered.index,
        autopct='%1.1f%%',
        colors=[seg_colors[s] for s in seg_rev_ordered.index],
        startangle=90,
        textprops={'fontsize': 10})
ax4.set_title('Доля выручки по сегментам')

# Scatter: заказы vs LTV
ax5 = axes2[2]
for seg in seg_order:
    mask = dim_customers['segment'] == seg
    if mask.sum() > 0:
        ax5.scatter(dim_customers.loc[mask, 'total_orders'],
                    dim_customers.loc[mask, 'total_spent'],
                    label=seg, color=seg_colors[seg],
                    alpha=0.7, s=60)
ax5.set_title('Частота заказов vs LTV')
ax5.set_xlabel('Количество заказов')
ax5.set_ylabel('Сумма покупок (₽)')
ax5.legend(fontsize=8)
ax5.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('reports/viz2_segmentation.png', dpi=150, bbox_inches='tight')
plt.close()
print("Сохранено: reports/viz2_segmentation.png")


# ========================================
# ЧАСТЬ 4: ВИЗУАЛИЗАЦИЯ 3 — REVENUE TIER
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: Визуализация 3 — Revenue Tier анализ")
print("=" * 70)

fig3, axes3 = plt.subplots(1, 2, figsize=(14, 5))
fig3.suptitle('Визуализация 3: Анализ Revenue Tier', fontsize=14, fontweight='bold')

tier_order  = ['low', 'medium', 'high', 'vip']
tier_labels = ['Низкий', 'Средний', 'Высокий', 'VIP']
tier_colors = ['#95a5a6', '#3498db', '#e67e22', '#9b59b6']

# Средний чек по тиру
ax6 = axes3[0]
available_tiers = [t for t in tier_order if t in fct_orders['revenue_tier'].values]
available_labels = [tier_ru.get(t, t) for t in available_tiers]
available_colors = [tier_colors[tier_order.index(t)] for t in available_tiers]

tier_avg = (fct_orders.groupby('revenue_tier')['amount']
            .mean()
            .reindex(available_tiers))

bars6 = ax6.bar(available_labels, tier_avg.values,
                color=available_colors, alpha=0.85)
for bar, val in zip(bars6, tier_avg.values):
    ax6.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + tier_avg.max() * 0.01,
             f'{val:,.0f}₽', ha='center', va='bottom',
             fontsize=9, fontweight='bold')
ax6.set_title('Средний чек по уровню заказа')
ax6.set_xlabel('Уровень заказа')
ax6.set_ylabel('Средний чек (₽)')
ax6.grid(axis='y', alpha=0.3)

# Heatmap: тир x квартал
ax7 = axes3[1]
pivot = (fct_orders.groupby(['order_quarter', 'revenue_tier'])['amount']
         .sum()
         .unstack(fill_value=0))
pivot.columns = [tier_ru.get(c, c) for c in pivot.columns]
pivot.index   = [f'Кв.{q}' for q in pivot.index]

sns.heatmap(pivot, annot=True, fmt='.0f', cmap='YlOrRd',
            ax=ax7, linewidths=0.5)
ax7.set_title('Выручка: Квартал × Уровень заказа')
ax7.set_xlabel('Уровень заказа')
ax7.set_ylabel('Квартал')

plt.tight_layout()
plt.savefig('reports/viz3_revenue_tier.png', dpi=150, bbox_inches='tight')
plt.close()
print("Сохранено: reports/viz3_revenue_tier.png")


# ========================================
# ЧАСТЬ 5: POWER BI — ИНСТРУКЦИЯ
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: Power BI — инструкция по 3 визуализациям")
print("=" * 70)

print("""
Когда установишь Power BI Desktop:

ВИЗУАЛИЗАЦИЯ 1 — Line Chart (Тренд выручки):
  Тип: Line Chart
  Ось X: month_num
  Ось Y: [Total Revenue]
  Добавить: Analytics → Trend Line → включить

ВИЗУАЛИЗАЦИЯ 2 — Pie Chart (Сегментация клиентов):
  Тип: Pie Chart
  Легенда: segment (из dim_customers)
  Значения: total_spent
  Добавить Slicer: city — фильтр по городу

ВИЗУАЛИЗАЦИЯ 3 — Matrix (Heatmap аналог):
  Тип: Matrix
  Строки: order_quarter
  Столбцы: revenue_tier
  Значения: [Total Revenue]
  Формат: Color Scale → зелёный → красный

ИТОГО:
  3 KPI карточки: GMV, Total Orders, Avg Check
  3 визуализации: Line, Pie, Matrix
  1 Slicer: по городу
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("ДЕНЬ 26 ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Созданы 3 визуализации с русскими подписями:
1. Тренд выручки (линия + бар по кварталам) → reports/viz1_trend.png
2. Сегментация клиентов (бар + пирог + scatter) → reports/viz2_segmentation.png
3. Revenue Tier анализ (бар + heatmap) → reports/viz3_revenue_tier.png

КОМАНДЫ:
python lesson26.py
start reports\\viz1_trend.png
start reports\\viz2_segmentation.png
start reports\\viz3_revenue_tier.png

Следующий день: День 27 — Python OOP, рефакторинг ETL в классы
""")