"""
День 31: Window Functions — продвинутые паттерны
Running totals, Moving averages, Cumulative %, Frames
"""

import pandas as pd
import numpy as np
import duckdb
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from pathlib import Path

plt.rcParams['font.family'] = 'DejaVu Sans'

print("=" * 70)
print(" " * 5 + "ДЕНЬ 31: WINDOW FUNCTIONS — ПРОДВИНУТЫЕ ПАТТЕРНЫ")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)

con = duckdb.connect(':memory:')

# ========================================
# ЧАСТЬ 1: ГЕНЕРАЦИЯ ДАННЫХ
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Генерация тестовых данных")
print("=" * 70)

np.random.seed(42)
N = 365

dates = pd.date_range('2024-01-01', periods=N, freq='D')
categories = np.random.choice(['Электроника', 'Одежда', 'Дом', 'Спорт'], N)
amounts = (
    np.random.randint(5000, 50000, N)
    + np.sin(np.arange(N) * 2 * np.pi / 30) * 5000  # сезонность
    + np.arange(N) * 50                               # тренд роста
).astype(int)

sales = pd.DataFrame({
    'sale_date':  dates,
    'category':   categories,
    'amount':     amounts,
    'orders':     np.random.randint(10, 100, N),
    'customers':  np.random.randint(5, 80, N),
})

con.register('sales', sales)
print(f"Данные: {len(sales)} строк, период {sales['sale_date'].min().date()} — {sales['sale_date'].max().date()}")
print(f"Категории: {sorted(sales['category'].unique().tolist())}")
print(f"Выручка: мин={sales['amount'].min():,} ₽, макс={sales['amount'].max():,} ₽")


# ========================================
# ЧАСТЬ 2: RUNNING TOTALS
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: Running Totals — нарастающий итог")
print("=" * 70)

# 2.1 Простой running total
q1 = """
SELECT
    sale_date,
    amount,
    SUM(amount) OVER (
        ORDER BY sale_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_total,
    ROUND(
        SUM(amount) OVER (ORDER BY sale_date) * 100.0
        / SUM(amount) OVER (), 2
    ) AS cumulative_pct
FROM sales
ORDER BY sale_date
"""
df_running = con.execute(q1).df()
print("Running Total (первые 7 дней):")
print(df_running.head(7)[['sale_date', 'amount', 'running_total', 'cumulative_pct']].to_string(index=False))

# 2.2 Running total по категориям (PARTITION BY)
q2 = """
SELECT
    sale_date,
    category,
    amount,
    SUM(amount) OVER (
        PARTITION BY category
        ORDER BY sale_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS category_running_total,
    ROW_NUMBER() OVER (
        PARTITION BY category
        ORDER BY sale_date
    ) AS day_num
FROM sales
ORDER BY category, sale_date
"""
df_cat_running = con.execute(q2).df()
print("\nRunning Total по категориям (первые 3 дня каждой):")
print(df_cat_running[df_cat_running['day_num'] <= 3]
      [['category', 'sale_date', 'amount', 'category_running_total']]
      .to_string(index=False))

print("\n📌 Ключевые паттерны Running Total:")
print("  UNBOUNDED PRECEDING — с самого начала")
print("  PARTITION BY — отдельный счётчик для каждой группы")
print("  cumulative_pct — % накопленного от общего")


# ========================================
# ЧАСТЬ 3: MOVING AVERAGES
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: Moving Averages — скользящее среднее")
print("=" * 70)

q3 = """
SELECT
    sale_date,
    amount,

    -- 7-дневное скользящее среднее
    ROUND(AVG(amount) OVER (
        ORDER BY sale_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 0) AS ma_7d,

    -- 30-дневное скользящее среднее
    ROUND(AVG(amount) OVER (
        ORDER BY sale_date
        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ), 0) AS ma_30d,

    -- Центрированное скользящее среднее (3 дня)
    ROUND(AVG(amount) OVER (
        ORDER BY sale_date
        ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
    ), 0) AS ma_3d_centered,

    -- Скользящий максимум (7 дней)
    MAX(amount) OVER (
        ORDER BY sale_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_max_7d,

    -- Скользящий минимум (7 дней)
    MIN(amount) OVER (
        ORDER BY sale_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_min_7d

FROM sales
ORDER BY sale_date
"""
df_ma = con.execute(q3).df()
print("Скользящие средние (дни 8-12, когда MA7 уже полная):")
print(df_ma.iloc[7:12][['sale_date', 'amount', 'ma_7d', 'ma_30d', 'ma_3d_centered']].to_string(index=False))

# Отклонение от MA
q4 = """
SELECT
    sale_date,
    amount,
    ROUND(AVG(amount) OVER (
        ORDER BY sale_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 0) AS ma_7d,
    ROUND(amount - AVG(amount) OVER (
        ORDER BY sale_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 0) AS deviation_from_ma,
    ROUND((amount - AVG(amount) OVER (
        ORDER BY sale_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )) * 100.0 / NULLIF(AVG(amount) OVER (
        ORDER BY sale_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 0), 1) AS deviation_pct
FROM sales
ORDER BY ABS(amount - AVG(amount) OVER (
    ORDER BY sale_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
)) DESC
LIMIT 5
"""
df_dev = con.execute(q4).df()
print("\nТоп-5 дней с наибольшим отклонением от MA7:")
print(df_dev.to_string(index=False))

print("\n📌 Ключевые паттерны Moving Average:")
print("  MA7  = 6 PRECEDING AND CURRENT ROW (7 строк)")
print("  MA30 = 29 PRECEDING AND CURRENT ROW (30 строк)")
print("  Центрированная MA = 1 PRECEDING AND 1 FOLLOWING")
print("  Отклонение от MA — выявляет аномалии")


# ========================================
# ЧАСТЬ 4: ПРОДВИНУТЫЕ ПАТТЕРНЫ
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: Продвинутые паттерны")
print("=" * 70)

# 4.1 Доля выручки по категориям с накоплением
q5 = """
WITH category_totals AS (
    SELECT
        category,
        SUM(amount) AS total_revenue,
        ROUND(SUM(amount) * 100.0 / SUM(SUM(amount)) OVER (), 2) AS pct_of_total
    FROM sales
    GROUP BY category
),
ranked AS (
    SELECT
        category,
        total_revenue,
        pct_of_total,
        RANK() OVER (ORDER BY total_revenue DESC) AS rank,
        SUM(pct_of_total) OVER (
            ORDER BY total_revenue DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_pct
    FROM category_totals
)
SELECT * FROM ranked ORDER BY rank
"""
df_share = con.execute(q5).df()
print("Доля выручки по категориям (с накопленным %):")
print(df_share.to_string(index=False))

# 4.2 День-к-дню и неделя-к-неделе
q6 = """
WITH daily AS (
    SELECT
        sale_date,
        SUM(amount) AS daily_revenue
    FROM sales
    GROUP BY sale_date
)
SELECT
    sale_date,
    daily_revenue,
    LAG(daily_revenue, 1) OVER (ORDER BY sale_date) AS prev_day,
    ROUND((daily_revenue - LAG(daily_revenue, 1) OVER (ORDER BY sale_date))
          * 100.0 / NULLIF(LAG(daily_revenue, 1) OVER (ORDER BY sale_date), 0), 1
    ) AS dod_pct,
    LAG(daily_revenue, 7) OVER (ORDER BY sale_date) AS prev_week_same_day,
    ROUND((daily_revenue - LAG(daily_revenue, 7) OVER (ORDER BY sale_date))
          * 100.0 / NULLIF(LAG(daily_revenue, 7) OVER (ORDER BY sale_date), 0), 1
    ) AS wow_pct
FROM daily
ORDER BY sale_date
LIMIT 15
"""
df_dod = con.execute(q6).df()
print("\nДень-к-дню (DoD) и Неделя-к-неделе (WoW):")
print(df_dod.dropna().head(7).to_string(index=False))

# 4.3 NTILE — квартили выручки
q7 = """
SELECT
    sale_date,
    category,
    amount,
    NTILE(4) OVER (ORDER BY amount DESC) AS quartile,
    NTILE(10) OVER (ORDER BY amount DESC) AS decile,
    PERCENT_RANK() OVER (ORDER BY amount) AS percent_rank,
    CUME_DIST() OVER (ORDER BY amount) AS cume_dist
FROM sales
ORDER BY amount DESC
LIMIT 10
"""
df_ntile = con.execute(q7).df()
print("\nNTILE, PERCENT_RANK, CUME_DIST (топ-10 по выручке):")
print(df_ntile.to_string(index=False))

print("\n📌 Ключевые паттерны:")
print("  DoD = LAG(amount, 1) — предыдущий день")
print("  WoW = LAG(amount, 7) — та же дата прошлой недели")
print("  NTILE(4) — деление на квартили")
print("  PERCENT_RANK — позиция в процентах (0.0 — 1.0)")
print("  CUME_DIST — накопленная доля строк")


# ========================================
# ЧАСТЬ 5: ВИЗУАЛИЗАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: Визуализация")
print("=" * 70)

fig, axes = plt.subplots(2, 2, figsize=(16, 10))
fig.suptitle('День 31: Window Functions — Продвинутые паттерны',
             fontsize=15, fontweight='bold')

# График 1: Running Total
ax1 = axes[0, 0]
ax1.plot(df_running['sale_date'], df_running['running_total'] / 1_000_000,
         color='#2ecc71', linewidth=2)
ax1.fill_between(df_running['sale_date'],
                 df_running['running_total'] / 1_000_000,
                 alpha=0.15, color='#2ecc71')
ax1.set_title('Нарастающий итог выручки (Running Total)', fontweight='bold')
ax1.set_xlabel('Дата')
ax1.set_ylabel('Выручка (млн ₽)')
ax1.grid(True, alpha=0.3)
ax1.tick_params(axis='x', rotation=30)

# График 2: Moving Averages
ax2 = axes[0, 1]
ax2.plot(df_ma['sale_date'], df_ma['amount'] / 1000,
         color='#bdc3c7', linewidth=1, alpha=0.6, label='Факт')
ax2.plot(df_ma['sale_date'], df_ma['ma_7d'] / 1000,
         color='#3498db', linewidth=2, label='MA 7 дней')
ax2.plot(df_ma['sale_date'], df_ma['ma_30d'] / 1000,
         color='#e74c3c', linewidth=2.5, label='MA 30 дней')
ax2.set_title('Скользящие средние (MA7 и MA30)', fontweight='bold')
ax2.set_xlabel('Дата')
ax2.set_ylabel('Выручка (тыс. ₽)')
ax2.legend(fontsize=9)
ax2.grid(True, alpha=0.3)
ax2.tick_params(axis='x', rotation=30)

# График 3: Доля категорий (накопленный %)
ax3 = axes[1, 0]
colors_cat = ['#2ecc71', '#3498db', '#e67e22', '#9b59b6']
bars = ax3.bar(df_share['category'],
               df_share['pct_of_total'],
               color=colors_cat[:len(df_share)], alpha=0.85)
ax3_twin = ax3.twinx()
ax3_twin.plot(df_share['category'],
              df_share['cumulative_pct'],
              color='red', marker='o', linewidth=2, markersize=7,
              label='Накопленный %')
ax3_twin.set_ylabel('Накопленный %', color='red')
ax3_twin.set_ylim(0, 120)
for bar, val in zip(bars, df_share['pct_of_total']):
    ax3.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + 0.3,
             f'{val:.1f}%', ha='center', va='bottom',
             fontsize=9, fontweight='bold')
ax3.set_title('Доля выручки по категориям (Pareto)', fontweight='bold')
ax3.set_xlabel('Категория')
ax3.set_ylabel('Доля выручки (%)')
ax3.grid(axis='y', alpha=0.3)

# График 4: DoD изменение
ax4 = axes[1, 1]
df_dod_clean = df_dod.dropna(subset=['dod_pct'])
colors_dod = ['#2ecc71' if v >= 0 else '#e74c3c'
              for v in df_dod_clean['dod_pct']]
ax4.bar(range(len(df_dod_clean)), df_dod_clean['dod_pct'],
        color=colors_dod, alpha=0.8)
ax4.axhline(y=0, color='black', linewidth=0.8)
ax4.set_title('День-к-дню изменение выручки (DoD %)', fontweight='bold')
ax4.set_xlabel('День')
ax4.set_ylabel('Изменение (%)')
ax4.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig('reports/day31_window_functions.png', dpi=150, bbox_inches='tight')
plt.close()
print("График сохранён: reports/day31_window_functions.png")


# ========================================
# ЧАСТЬ 6: БИЗНЕС-ЗАДАЧИ
# ========================================

print("\n" + "=" * 70)
print("6  ЧАСТЬ 6: Бизнес-задачи на Window Functions")
print("=" * 70)

# Задача 1: Выявить дни выше среднего за последние 30 дней
q8 = """
SELECT
    sale_date,
    amount,
    ROUND(AVG(amount) OVER (
        ORDER BY sale_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    ), 0) AS ma_30d,
    CASE
        WHEN amount > AVG(amount) OVER (
            ORDER BY sale_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        ) * 1.2 THEN 'Пик продаж'
        WHEN amount < AVG(amount) OVER (
            ORDER BY sale_date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        ) * 0.8 THEN 'Падение продаж'
        ELSE 'Норма'
    END AS signal
FROM sales
ORDER BY sale_date
"""
df_signals = con.execute(q8).df()
signal_counts = df_signals['signal'].value_counts()
print("Сигналы аномалий (отклонение > 20% от MA30):")
print(signal_counts.to_string())

# Задача 2: Топ дней по выручке в каждой категории
q9 = """
SELECT
    category,
    sale_date,
    amount,
    RANK() OVER (PARTITION BY category ORDER BY amount DESC) AS rank_in_category
FROM sales
QUALIFY RANK() OVER (PARTITION BY category ORDER BY amount DESC) <= 3
ORDER BY category, rank_in_category
"""
df_top = con.execute(q9).df()
print("\nТоп-3 дня по выручке в каждой категории:")
print(df_top.to_string(index=False))

# Задача 3: Процент от максимума за последние 7 дней
q10 = """
SELECT
    sale_date,
    category,
    amount,
    MAX(amount) OVER (
        PARTITION BY category
        ORDER BY sale_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_max_7d,
    ROUND(amount * 100.0 / MAX(amount) OVER (
        PARTITION BY category
        ORDER BY sale_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 1) AS pct_of_7d_max
FROM sales
ORDER BY sale_date DESC
LIMIT 12
"""
df_pct_max = con.execute(q10).df()
print("\n% от максимума за последние 7 дней (последние 12 записей):")
print(df_pct_max.to_string(index=False))

con.close()


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("ДЕНЬ 31 ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Изученные паттерны Window Functions:

1. Running Total
   SUM() OVER (ORDER BY date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)

2. Running Total по группам (PARTITION BY)
   SUM() OVER (PARTITION BY category ORDER BY date ...)

3. Moving Average
   AVG() OVER (ORDER BY date ROWS BETWEEN N PRECEDING AND CURRENT ROW)

4. Cumulative % от общего
   SUM() / SUM() OVER () * 100

5. День-к-дню (DoD) и Неделя-к-неделе (WoW)
   LAG(amount, 1) и LAG(amount, 7)

6. NTILE, PERCENT_RANK, CUME_DIST
   Ранжирование и процентили

7. QUALIFY — фильтр по оконным функциям (DuckDB)
   QUALIFY RANK() OVER (...) <= 3

8. Сигналы аномалий через CASE + MA

График: reports/day31_window_functions.png

Следующий день: День 32 — LAG/LEAD для Cohort Analysis
""")