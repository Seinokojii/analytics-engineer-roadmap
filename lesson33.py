"""
День 33: Advanced SQL — QUALIFY, PIVOT, UNPIVOT, GROUPING SETS
Продвинутые конструкции DuckDB для аналитики
"""

import pandas as pd
import numpy as np
import duckdb
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

plt.rcParams['font.family'] = 'DejaVu Sans'

print("=" * 70)
print(" " * 5 + "ДЕНЬ 33: ADVANCED SQL — QUALIFY, PIVOT, GROUPING SETS")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)

con = duckdb.connect(':memory:')


# ========================================
# ЧАСТЬ 1: ГЕНЕРАЦИЯ ДАННЫХ
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Генерация данных")
print("=" * 70)

np.random.seed(42)
N = 2000

orders = pd.DataFrame({
    'order_id':   range(1, N + 1),
    'customer_id': np.random.randint(1, 201, N),
    'category':   np.random.choice(
        ['Электроника', 'Одежда', 'Дом', 'Спорт', 'Книги'], N
    ),
    'city':       np.random.choice(
        ['Москва', 'СПб', 'Казань', 'Екб', 'НСК'], N
    ),
    'status':     np.random.choice(
        ['completed', 'cancelled', 'refunded'], N, p=[0.7, 0.2, 0.1]
    ),
    'amount':     np.random.randint(500, 30000, N),
    'quantity':   np.random.randint(1, 6, N),
    'order_date': pd.date_range('2024-01-01', periods=N, freq='4h'),
})
orders['month']   = orders['order_date'].dt.month
orders['quarter'] = orders['order_date'].dt.quarter
orders['year']    = orders['order_date'].dt.year
orders['total']   = orders['amount'] * orders['quantity']

con.register('orders', orders)
print(f"Данные: {len(orders)} заказов")
print(f"Города: {sorted(orders['city'].unique().tolist())}")
print(f"Категории: {sorted(orders['category'].unique().tolist())}")


# ========================================
# ЧАСТЬ 2: QUALIFY
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: QUALIFY — фильтр по оконным функциям")
print("=" * 70)

# 2.1 Топ-2 заказа по каждой категории
q1 = """
SELECT
    order_id,
    category,
    city,
    amount,
    RANK() OVER (PARTITION BY category ORDER BY amount DESC) AS rank_in_cat
FROM orders
WHERE status = 'completed'
QUALIFY rank_in_cat <= 2
ORDER BY category, rank_in_cat
"""
df_q1 = con.execute(q1).df()
print("Топ-2 заказа по каждой категории (QUALIFY):")
print(df_q1.to_string(index=False))

# 2.2 Первый заказ каждого клиента
q2 = """
SELECT
    customer_id,
    order_id,
    order_date,
    amount,
    category,
    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) AS order_num
FROM orders
QUALIFY order_num = 1
ORDER BY customer_id
LIMIT 8
"""
df_q2 = con.execute(q2).df()
print("\nПервый заказ каждого клиента (QUALIFY ROW_NUMBER = 1):")
print(df_q2[['customer_id', 'order_id', 'order_date',
             'amount', 'category']].to_string(index=False))

# 2.3 Клиенты чей последний заказ был в топ-10% по сумме
q3 = """
SELECT
    customer_id,
    order_date,
    amount,
    PERCENT_RANK() OVER (ORDER BY amount DESC) AS pct_rank,
    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date DESC) AS recency_rank
FROM orders
WHERE status = 'completed'
QUALIFY recency_rank = 1 AND pct_rank <= 0.1
ORDER BY amount DESC
LIMIT 10
"""
df_q3 = con.execute(q3).df()
print("\nКлиенты, чей ПОСЛЕДНИЙ заказ в топ-10% по сумме:")
print(df_q3[['customer_id', 'order_date', 'amount', 'pct_rank']].to_string(index=False))

print("\n📌 QUALIFY — фильтрует по результату оконной функции")
print("  Выполняется ПОСЛЕ SELECT, но ДО ORDER BY")
print("  Только в DuckDB, BigQuery, Snowflake (не в PostgreSQL)")


# ========================================
# ЧАСТЬ 3: GROUPING SETS, ROLLUP, CUBE
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: GROUPING SETS, ROLLUP, CUBE")
print("=" * 70)

# 3.1 GROUPING SETS — выборочные группировки
q4 = """
SELECT
    city,
    category,
    SUM(total)   AS выручка,
    COUNT(*)     AS заказов,
    GROUPING(city)     AS is_city_total,
    GROUPING(category) AS is_cat_total
FROM orders
WHERE status = 'completed'
GROUP BY GROUPING SETS (
    (city, category),  -- город + категория
    (city),            -- только город
    (category),        -- только категория
    ()                 -- общий итог
)
ORDER BY is_city_total, is_cat_total, city, category
"""
df_gs = con.execute(q4).df()
print("GROUPING SETS — итоги на разных уровнях:")
print(f"  Всего строк: {len(df_gs)}")
print(f"  Город + категория: {len(df_gs[(df_gs['is_city_total']==0) & (df_gs['is_cat_total']==0)])}")
print(f"  Только город:      {len(df_gs[(df_gs['is_city_total']==0) & (df_gs['is_cat_total']==1)])}")
print(f"  Только категория:  {len(df_gs[(df_gs['is_city_total']==1) & (df_gs['is_cat_total']==0)])}")
print(f"  Общий итог:        {len(df_gs[(df_gs['is_city_total']==1) & (df_gs['is_cat_total']==1)])}")

# Показываем итоговые строки
totals = df_gs[df_gs['is_city_total'] == 1][['category', 'выручка', 'заказов']].dropna(subset=['category'])
print("\nИтоги по категориям:")
print(totals.sort_values('выручка', ascending=False).to_string(index=False))

# 3.2 ROLLUP — иерархия год → квартал → месяц
q5 = """
SELECT
    year,
    quarter,
    month,
    SUM(total)   AS выручка,
    COUNT(*)     AS заказов
FROM orders
WHERE status = 'completed'
GROUP BY ROLLUP (year, quarter, month)
HAVING year IS NOT NULL
ORDER BY year, quarter NULLS LAST, month NULLS LAST
"""
df_rollup = con.execute(q5).df()
print("\nROLLUP — иерархия год → квартал → месяц:")
# Показываем квартальные итоги
quarterly = df_rollup[df_rollup['month'].isna() & df_rollup['quarter'].notna()]
print(quarterly[['year', 'quarter', 'выручка', 'заказов']].to_string(index=False))

# 3.3 CUBE — все комбинации
q6 = """
SELECT
    city,
    status,
    SUM(total)  AS выручка,
    COUNT(*)    AS заказов
FROM orders
GROUP BY CUBE (city, status)
HAVING city IS NOT NULL AND status IS NOT NULL
ORDER BY city, status
"""
df_cube = con.execute(q6).df()
print("\nCUBE — выручка по городу и статусу:")
print(df_cube.to_string(index=False))

print("\n📌 GROUPING SETS vs ROLLUP vs CUBE:")
print("  GROUPING SETS — явно задаёшь нужные группировки")
print("  ROLLUP(a,b,c) — (a,b,c), (a,b), (a), () — иерархия")
print("  CUBE(a,b)     — (a,b), (a), (b), () — все комбинации")


# ========================================
# ЧАСТЬ 4: PIVOT / UNPIVOT
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: PIVOT / UNPIVOT")
print("=" * 70)

# 4.1 PIVOT — выручка по месяцам в столбцы
q7 = """
SELECT *
FROM (
    SELECT category, month, SUM(total) AS revenue
    FROM orders
    WHERE status = 'completed' AND month <= 6
    GROUP BY category, month
)
PIVOT (SUM(revenue) FOR month IN (1, 2, 3, 4, 5, 6))
ORDER BY category
"""
df_pivot = con.execute(q7).df()
df_pivot.columns = ['Категория', 'Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн']
print("PIVOT — выручка по категориям и месяцам:")
print(df_pivot.fillna(0).astype({c: int for c in df_pivot.columns[1:]}).to_string(index=False))

# 4.2 PIVOT по городам
q8 = """
SELECT *
FROM (
    SELECT city, category, COUNT(*) AS cnt
    FROM orders
    WHERE status = 'completed'
    GROUP BY city, category
)
PIVOT (SUM(cnt) FOR city IN ('Москва', 'СПб', 'Казань', 'Екб', 'НСК'))
ORDER BY category
"""
df_pivot2 = con.execute(q8).df()
print("\nPIVOT — количество заказов: категория × город:")
print(df_pivot2.fillna(0).to_string(index=False))

# 4.3 UNPIVOT — обратная операция (столбцы в строки)
monthly_wide = pd.DataFrame({
    'category':    ['Электроника', 'Одежда', 'Дом', 'Спорт', 'Книги'],
    'jan_revenue': [120000, 80000, 60000, 45000, 20000],
    'feb_revenue': [135000, 75000, 70000, 50000, 22000],
    'mar_revenue': [110000, 90000, 65000, 55000, 18000],
})
con.register('monthly_wide', monthly_wide)

q9 = """
SELECT category, month, revenue
FROM monthly_wide
UNPIVOT (revenue FOR month IN (jan_revenue, feb_revenue, mar_revenue))
ORDER BY category, month
"""
df_unpivot = con.execute(q9).df()
df_unpivot['month'] = df_unpivot['month'].map({
    'jan_revenue': 'Январь',
    'feb_revenue': 'Февраль',
    'mar_revenue': 'Март'
})
print("\nUNPIVOT — столбцы в строки:")
print(df_unpivot.to_string(index=False))

print("\n📌 PIVOT / UNPIVOT:")
print("  PIVOT   — строки → столбцы (для отчётов и дашбордов)")
print("  UNPIVOT — столбцы → строки (нормализация для анализа)")
print("  В DuckDB PIVOT встроен — не нужен сложный CASE WHEN")


# ========================================
# ЧАСТЬ 5: ПРОДВИНУТЫЕ ПАТТЕРНЫ
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: Продвинутые паттерны")
print("=" * 70)

# 5.1 Медиана и перцентили
q10 = """
SELECT
    category,
    COUNT(*)                                    AS заказов,
    ROUND(AVG(amount), 0)                       AS среднее,
    MEDIAN(amount)                              AS медиана,
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY amount) AS p25,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY amount) AS p75,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY amount) AS p90,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY amount) AS p99
FROM orders
WHERE status = 'completed'
GROUP BY category
ORDER BY среднее DESC
"""
df_perc = con.execute(q10).df()
print("Перцентили выручки по категориям:")
print(df_perc.to_string(index=False))

# 5.2 STRING_AGG — объединение строк
q11 = """
SELECT
    customer_id,
    COUNT(*)                                         AS заказов,
    SUM(total)                                       AS ltv,
    STRING_AGG(DISTINCT category, ', ' ORDER BY category) AS категории,
    STRING_AGG(DISTINCT city, ', ')                  AS города
FROM orders
WHERE status = 'completed'
GROUP BY customer_id
HAVING COUNT(*) >= 5
ORDER BY ltv DESC
LIMIT 8
"""
df_agg = con.execute(q11).df()
print("\nКлиенты с 5+ заказами (STRING_AGG категорий):")
print(df_agg.to_string(index=False))

# 5.3 ASOF JOIN — ближайшее совпадение по времени (DuckDB)
prices = pd.DataFrame({
    'category':    ['Электроника', 'Электроника', 'Одежда', 'Одежда'],
    'valid_from':  pd.to_datetime(['2024-01-01', '2024-07-01',
                                   '2024-01-01', '2024-07-01']),
    'discount':    [5, 10, 3, 7],
})
con.register('prices', prices)

q12 = """
SELECT
    o.order_id,
    o.category,
    o.order_date,
    o.amount,
    p.discount,
    ROUND(o.amount * (1 - p.discount / 100.0), 0) AS amount_with_discount
FROM orders o
ASOF JOIN prices p
    ON o.category = p.category
    AND o.order_date >= p.valid_from
WHERE o.status = 'completed' AND o.category IN ('Электроника', 'Одежда')
ORDER BY o.order_date
LIMIT 8
"""
df_asof = con.execute(q12).df()
print("\nASOF JOIN — применение скидки по дате:")
print(df_asof.to_string(index=False))

print("\n📌 Продвинутые функции DuckDB:")
print("  MEDIAN()            — медиана")
print("  PERCENTILE_CONT()   — произвольный перцентиль")
print("  STRING_AGG()        — склейка строк")
print("  ASOF JOIN           — ближайшее значение по времени")


# ========================================
# ЧАСТЬ 6: ВИЗУАЛИЗАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("6  ЧАСТЬ 6: Визуализация")
print("=" * 70)

fig, axes = plt.subplots(2, 2, figsize=(16, 10))
fig.suptitle('День 33: Advanced SQL — QUALIFY, PIVOT, GROUPING SETS',
             fontsize=14, fontweight='bold')

# График 1: PIVOT — тепловая карта выручки (категория × месяц)
ax1 = axes[0, 0]
pivot_heat = df_pivot.set_index('Категория').fillna(0)
sns.heatmap(pivot_heat / 1000, annot=True, fmt='.0f',
            cmap='YlOrRd', ax=ax1, linewidths=0.5,
            cbar_kws={'label': 'Выручка (тыс. ₽)'})
ax1.set_title('PIVOT: Выручка по категориям и месяцам (тыс. ₽)', fontweight='bold')
ax1.set_xlabel('Месяц')
ax1.set_ylabel('Категория')

# График 2: GROUPING SETS — сравнение городов
ax2 = axes[0, 1]
city_totals = df_gs[
    (df_gs['is_city_total'] == 0) & (df_gs['is_cat_total'] == 1)
][['city', 'выручка']].dropna()
colors_city = ['#3498db', '#2ecc71', '#e67e22', '#9b59b6', '#e74c3c']
bars = ax2.bar(city_totals['city'], city_totals['выручка'] / 1_000_000,
               color=colors_city, alpha=0.85)
for bar, val in zip(bars, city_totals['выручка'] / 1_000_000):
    ax2.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + 0.01,
             f'{val:.2f}М', ha='center', va='bottom',
             fontsize=9, fontweight='bold')
ax2.set_title('GROUPING SETS: Выручка по городам', fontweight='bold')
ax2.set_xlabel('Город')
ax2.set_ylabel('Выручка (млн ₽)')
ax2.grid(axis='y', alpha=0.3)

# График 3: Перцентили по категориям (box-like)
ax3 = axes[1, 0]
categories = df_perc['category'].tolist()
x = range(len(categories))
ax3.bar(x, df_perc['p75'] / 1000, color='#3498db', alpha=0.4, label='P75')
ax3.bar(x, df_perc['p25'] / 1000, color='white', alpha=1.0)
ax3.bar(x, df_perc['p25'] / 1000, color='#3498db', alpha=0.8, label='P25')
ax3.plot(x, df_perc['медиана'] / 1000, 'ro', markersize=8, label='Медиана', zorder=5)
ax3.plot(x, df_perc['p90'] / 1000, 'g^', markersize=8, label='P90', zorder=5)
ax3.set_title('Перцентили суммы заказа по категориям', fontweight='bold')
ax3.set_xlabel('Категория')
ax3.set_ylabel('Сумма (тыс. ₽)')
ax3.set_xticks(x)
ax3.set_xticklabels(categories, rotation=15)
ax3.legend(fontsize=8)
ax3.grid(axis='y', alpha=0.3)

# График 4: CUBE — heatmap город × статус
ax4 = axes[1, 1]
pivot_cube = df_cube.pivot(index='city', columns='status', values='выручка').fillna(0)
sns.heatmap(pivot_cube / 1000, annot=True, fmt='.0f',
            cmap='Blues', ax=ax4, linewidths=0.5,
            cbar_kws={'label': 'Выручка (тыс. ₽)'})
ax4.set_title('CUBE: Выручка — Город × Статус (тыс. ₽)', fontweight='bold')
ax4.set_xlabel('Статус заказа')
ax4.set_ylabel('Город')

plt.tight_layout()
plt.savefig('reports/day33_advanced_sql.png', dpi=150, bbox_inches='tight')
plt.close()
print("График сохранён: reports/day33_advanced_sql.png")

con.close()


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("ДЕНЬ 33 ЗАВЕРШЁН!")
print("=" * 70)
print("""
Изученные конструкции Advanced SQL:

1. QUALIFY
   Фильтр по оконным функциям без подзапроса
   QUALIFY RANK() OVER (...) <= 3

2. GROUPING SETS
   Несколько группировок в одном запросе
   GROUP BY GROUPING SETS ((city), (category), ())

3. ROLLUP
   Иерархические итоги (год → квартал → месяц)
   GROUP BY ROLLUP (year, quarter, month)

4. CUBE
   Все возможные комбинации GROUP BY
   GROUP BY CUBE (city, status)

5. PIVOT / UNPIVOT
   Трансформация строк в столбцы и обратно
   PIVOT (SUM(amount) FOR month IN (1,2,3))

6. PERCENTILE_CONT, MEDIAN
   Статистические функции

7. STRING_AGG
   Объединение строк в одну

8. ASOF JOIN
   Ближайшее совпадение по времени

График: reports/day33_advanced_sql.png

Следующий день: День 34 — SQL оптимизация запросов
""")