"""
День 32: Analytic Patterns — LAG/LEAD для Cohort Analysis
Retention Rate, time-between-events, first/last purchase
"""

import pandas as pd
import numpy as np
import duckdb
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

plt.rcParams['font.family'] = 'DejaVu Sans'

print("=" * 70)
print(" " * 5 + "ДЕНЬ 32: LAG/LEAD ДЛЯ COHORT ANALYSIS")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)

con = duckdb.connect(':memory:')


# ========================================
# ЧАСТЬ 1: ГЕНЕРАЦИЯ ДАННЫХ
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Генерация данных для когортного анализа")
print("=" * 70)

np.random.seed(42)

N_CUSTOMERS = 500
N_ORDERS    = 3000

# Клиенты регистрировались в течение 2024 года
reg_dates = pd.date_range('2024-01-01', '2024-12-31', freq='D')
customer_reg = {
    cid: np.random.choice(reg_dates)
    for cid in range(1, N_CUSTOMERS + 1)
}

# Генерация заказов
# Активные клиенты делают больше заказов
orders_list = []
order_id = 1

for cid, reg_date in customer_reg.items():
    # Каждый клиент делает 1-10 заказов после регистрации
    n_orders = np.random.choice(
        [1, 2, 3, 4, 5, 7, 10],
        p=[0.3, 0.25, 0.2, 0.1, 0.08, 0.05, 0.02]
    )
    for _ in range(n_orders):
        days_remaining = 365 - (reg_date - pd.Timestamp('2024-01-01')).days
        if days_remaining <= 1:
            continue
        days_after = np.random.randint(0, days_remaining)
        order_date = reg_date + pd.Timedelta(days=int(days_after))
        if order_date <= pd.Timestamp('2024-12-31'):
            orders_list.append({
                'order_id':    order_id,
                'customer_id': cid,
                'order_date':  order_date,
                'amount':      np.random.randint(500, 20000),
                'category':    np.random.choice(
                    ['Электроника', 'Одежда', 'Дом', 'Спорт']
                )
            })
            order_id += 1

orders = pd.DataFrame(orders_list)
orders['order_month'] = orders['order_date'].dt.to_period('M').astype(str)
orders['order_date']  = pd.to_datetime(orders['order_date'])

customers = pd.DataFrame([
    {'customer_id': cid, 'reg_date': reg_date}
    for cid, reg_date in customer_reg.items()
])
customers['cohort_month'] = pd.to_datetime(
    customers['reg_date']
).dt.to_period('M').astype(str)

con.register('orders', orders)
con.register('customers', customers)

print(f"Клиентов:  {len(customers)}")
print(f"Заказов:   {len(orders)}")
print(f"Период:    {orders['order_date'].min().date()} — {orders['order_date'].max().date()}")
print(f"Категории: {sorted(orders['category'].unique().tolist())}")


# ========================================
# ЧАСТЬ 2: LAG/LEAD ПАТТЕРНЫ
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: LAG/LEAD — сравнение периодов")
print("=" * 70)

# 2.1 Время между заказами (time-between-events)
q1 = """
SELECT
    customer_id,
    order_id,
    order_date,
    amount,
    LAG(order_date) OVER (
        PARTITION BY customer_id
        ORDER BY order_date
    ) AS prev_order_date,
    DATEDIFF('day',
        LAG(order_date) OVER (PARTITION BY customer_id ORDER BY order_date),
        order_date
    ) AS days_since_last_order,
    LAG(amount) OVER (
        PARTITION BY customer_id ORDER BY order_date
    ) AS prev_amount,
    ROUND((amount - LAG(amount) OVER (
        PARTITION BY customer_id ORDER BY order_date
    )) * 100.0 / NULLIF(LAG(amount) OVER (
        PARTITION BY customer_id ORDER BY order_date
    ), 0), 1) AS amount_change_pct
FROM orders
ORDER BY customer_id, order_date
"""
df_lag = con.execute(q1).df()
df_lag_clean = df_lag.dropna(subset=['days_since_last_order'])
print("Среднее время между заказами:")
print(f"  По всем клиентам: {df_lag_clean['days_since_last_order'].mean():.1f} дней")
print(f"  Медиана:          {df_lag_clean['days_since_last_order'].median():.1f} дней")
print(f"  Мин:              {df_lag_clean['days_since_last_order'].min():.0f} дней")
print(f"  Макс:             {df_lag_clean['days_since_last_order'].max():.0f} дней")

# 2.2 LEAD — следующий заказ
q2 = """
SELECT
    customer_id,
    order_date,
    amount,
    LEAD(order_date) OVER (
        PARTITION BY customer_id ORDER BY order_date
    ) AS next_order_date,
    LEAD(amount) OVER (
        PARTITION BY customer_id ORDER BY order_date
    ) AS next_amount,
    DATEDIFF('day', order_date,
        LEAD(order_date) OVER (PARTITION BY customer_id ORDER BY order_date)
    ) AS days_to_next_order,
    CASE
        WHEN LEAD(order_date) OVER (
            PARTITION BY customer_id ORDER BY order_date
        ) IS NULL THEN 'Последний заказ'
        ELSE 'Есть следующий'
    END AS order_status
FROM orders
ORDER BY customer_id, order_date
"""
df_lead = con.execute(q2).df()
status_counts = df_lead['order_status'].value_counts()
print("\nСтатус заказов (LEAD):")
print(status_counts.to_string())

# 2.3 FIRST_VALUE / LAST_VALUE — первая и последняя покупка
q3 = """
SELECT DISTINCT
    customer_id,
    FIRST_VALUE(order_date) OVER (
        PARTITION BY customer_id
        ORDER BY order_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    ) AS first_purchase,
    LAST_VALUE(order_date) OVER (
        PARTITION BY customer_id
        ORDER BY order_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    ) AS last_purchase,
    FIRST_VALUE(amount) OVER (
        PARTITION BY customer_id
        ORDER BY order_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    ) AS first_amount,
    MAX(amount) OVER (PARTITION BY customer_id) AS max_amount,
    COUNT(*) OVER (PARTITION BY customer_id) AS total_orders,
    SUM(amount) OVER (PARTITION BY customer_id) AS lifetime_value,
    DATEDIFF('day',
        FIRST_VALUE(order_date) OVER (
            PARTITION BY customer_id ORDER BY order_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ),
        LAST_VALUE(order_date) OVER (
            PARTITION BY customer_id ORDER BY order_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        )
    ) AS customer_lifespan_days
FROM orders
ORDER BY lifetime_value DESC
"""
df_customer = con.execute(q3).df()
print("\nТоп-5 клиентов по LTV:")
print(df_customer.head(5)[
    ['customer_id', 'first_purchase', 'last_purchase',
     'total_orders', 'lifetime_value', 'customer_lifespan_days']
].to_string(index=False))

print("\n📌 Ключевые паттерны LAG/LEAD:")
print("  LAG(date) — дата предыдущего заказа")
print("  LEAD(date) — дата следующего заказа")
print("  DATEDIFF — дней между событиями")
print("  FIRST_VALUE / LAST_VALUE — первая / последняя покупка")


# ========================================
# ЧАСТЬ 3: КОГОРТНЫЙ АНАЛИЗ
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: Когортный анализ — Retention Rate")
print("=" * 70)

# Шаг 1: Определяем когорту каждого клиента
q4 = """
WITH customer_cohorts AS (
    -- Первый заказ = когорта
    SELECT
        customer_id,
        MIN(DATE_TRUNC('month', order_date)) AS cohort_date
    FROM orders
    GROUP BY customer_id
),
order_months AS (
    SELECT
        o.customer_id,
        DATE_TRUNC('month', o.order_date) AS order_month,
        c.cohort_date,
        DATEDIFF('month', c.cohort_date, DATE_TRUNC('month', o.order_date)) AS month_number
    FROM orders o
    JOIN customer_cohorts c ON o.customer_id = c.customer_id
    GROUP BY o.customer_id, DATE_TRUNC('month', o.order_date), c.cohort_date
),
cohort_sizes AS (
    SELECT cohort_date, COUNT(DISTINCT customer_id) AS cohort_size
    FROM customer_cohorts
    GROUP BY cohort_date
),
retention_raw AS (
    SELECT
        om.cohort_date,
        om.month_number,
        COUNT(DISTINCT om.customer_id) AS retained_customers
    FROM order_months om
    GROUP BY om.cohort_date, om.month_number
)
SELECT
    r.cohort_date::VARCHAR AS cohort,
    r.month_number          AS месяц,
    cs.cohort_size          AS размер_когорты,
    r.retained_customers    AS вернулось,
    ROUND(r.retained_customers * 100.0 / cs.cohort_size, 1) AS retention_pct
FROM retention_raw r
JOIN cohort_sizes cs ON r.cohort_date = cs.cohort_date
WHERE r.month_number <= 5
ORDER BY r.cohort_date, r.month_number
"""
df_retention = con.execute(q4).df()

# Pivot для heatmap
pivot_retention = df_retention.pivot_table(
    index='cohort',
    columns='месяц',
    values='retention_pct',
    aggfunc='mean'
)
pivot_retention.columns = [f'М+{int(c)}' for c in pivot_retention.columns]

print("Retention Rate по когортам (% вернувшихся):")
print(pivot_retention.round(1).to_string())

# Средний retention по месяцам
print("\nСредний Retention Rate:")
for col in pivot_retention.columns:
    avg = pivot_retention[col].mean()
    print(f"  {col}: {avg:.1f}%")


# ========================================
# ЧАСТЬ 4: ПРОДВИНУТЫЕ ПАТТЕРНЫ
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: Продвинутые паттерны с LAG/LEAD")
print("=" * 70)

# 4.1 Сессионный анализ — группировка событий в сессии
q5 = """
WITH order_gaps AS (
    SELECT
        customer_id,
        order_date,
        amount,
        DATEDIFF('day',
            LAG(order_date) OVER (PARTITION BY customer_id ORDER BY order_date),
            order_date
        ) AS days_gap,
        -- Новая сессия если пауза > 30 дней
        CASE
            WHEN DATEDIFF('day',
                LAG(order_date) OVER (PARTITION BY customer_id ORDER BY order_date),
                order_date
            ) > 30 OR LAG(order_date) OVER (
                PARTITION BY customer_id ORDER BY order_date
            ) IS NULL
            THEN 1 ELSE 0
        END AS is_new_session
    FROM orders
),
sessions AS (
    SELECT
        customer_id,
        order_date,
        amount,
        days_gap,
        SUM(is_new_session) OVER (
            PARTITION BY customer_id
            ORDER BY order_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS session_number
    FROM order_gaps
)
SELECT
    customer_id,
    session_number          AS номер_сессии,
    COUNT(*)                AS заказов_в_сессии,
    SUM(amount)             AS выручка_сессии,
    MIN(order_date)         AS начало_сессии,
    MAX(order_date)         AS конец_сессии
FROM sessions
GROUP BY customer_id, session_number
ORDER BY выручка_сессии DESC
LIMIT 10
"""
df_sessions = con.execute(q5).df()
print("Топ-10 сессий по выручке (пауза > 30 дней = новая сессия):")
print(df_sessions.to_string(index=False))

# 4.2 Churned users — клиенты без заказов > 60 дней
q6 = """
WITH last_orders AS (
    SELECT
        customer_id,
        MAX(order_date) AS last_order_date,
        COUNT(*)        AS total_orders,
        SUM(amount)     AS total_spent
    FROM orders
    GROUP BY customer_id
)
SELECT
    customer_id,
    last_order_date,
    total_orders,
    total_spent,
    DATEDIFF('day', last_order_date, DATE '2024-12-31') AS days_since_last,
    CASE
        WHEN DATEDIFF('day', last_order_date, DATE '2024-12-31') > 90
            THEN 'Отток (>90 дней)'
        WHEN DATEDIFF('day', last_order_date, DATE '2024-12-31') > 60
            THEN 'Риск оттока (>60 дней)'
        WHEN DATEDIFF('day', last_order_date, DATE '2024-12-31') > 30
            THEN 'Предупреждение (>30 дней)'
        ELSE 'Активный'
    END AS churn_status
FROM last_orders
ORDER BY days_since_last DESC
"""
df_churn = con.execute(q6).df()
churn_counts = df_churn['churn_status'].value_counts()
print("\nАнализ оттока (Churn Analysis):")
print(churn_counts.to_string())

total = len(df_churn)
for status, count in churn_counts.items():
    print(f"  {status}: {count} клиентов ({count/total*100:.1f}%)")

# 4.3 Повторные покупки в той же категории
q7 = """
SELECT
    customer_id,
    category,
    order_date,
    amount,
    LAG(category) OVER (
        PARTITION BY customer_id ORDER BY order_date
    ) AS prev_category,
    CASE
        WHEN category = LAG(category) OVER (
            PARTITION BY customer_id ORDER BY order_date
        ) THEN 'Та же категория'
        ELSE 'Другая категория'
    END AS repeat_category
FROM orders
ORDER BY customer_id, order_date
"""
df_repeat = con.execute(q7).df()
repeat_counts = df_repeat.dropna(subset=['prev_category'])['repeat_category'].value_counts()
total_repeat = repeat_counts.sum()
print("\nПовторные покупки в той же категории:")
for status, count in repeat_counts.items():
    print(f"  {status}: {count} ({count/total_repeat*100:.1f}%)")

con.close()


# ========================================
# ЧАСТЬ 5: ВИЗУАЛИЗАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: Визуализация когортного анализа")
print("=" * 70)

fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('День 32: LAG/LEAD — Cohort Analysis',
             fontsize=15, fontweight='bold')

# График 1: Retention Heatmap
ax1 = axes[0, 0]
pivot_plot = pivot_retention.head(8)  # первые 8 когорт
sns.heatmap(
    pivot_plot,
    annot=True, fmt='.1f', cmap='RdYlGn',
    ax=ax1, linewidths=0.5,
    vmin=0, vmax=100,
    cbar_kws={'label': 'Retention %'}
)
ax1.set_title('Retention Rate по когортам (%)', fontweight='bold')
ax1.set_xlabel('Месяц после первой покупки')
ax1.set_ylabel('Когорта (месяц первой покупки)')
ax1.tick_params(axis='x', rotation=0)
ax1.tick_params(axis='y', rotation=0)

# График 2: Retention Curve (средняя)
ax2 = axes[0, 1]
avg_retention = pivot_retention.mean()
months_labels = [c.replace('М', 'M') for c in avg_retention.index]
ax2.plot(range(len(avg_retention)), avg_retention.values,
         marker='o', color='#3498db', linewidth=2.5, markersize=8)
ax2.fill_between(range(len(avg_retention)), avg_retention.values,
                 alpha=0.15, color='#3498db')
for i, val in enumerate(avg_retention.values):
    ax2.annotate(f'{val:.1f}%',
                 xy=(i, val), xytext=(0, 10),
                 textcoords='offset points',
                 ha='center', fontsize=9, fontweight='bold')
ax2.set_title('Средняя Retention Curve', fontweight='bold')
ax2.set_xlabel('Месяц после первой покупки')
ax2.set_ylabel('Retention Rate (%)')
ax2.set_xticks(range(len(avg_retention)))
ax2.set_xticklabels(avg_retention.index)
ax2.set_ylim(0, 110)
ax2.grid(True, alpha=0.3)

# График 3: Churn Distribution
ax3 = axes[1, 0]
churn_df = df_churn['churn_status'].value_counts().reset_index()
churn_df.columns = ['status', 'count']
churn_colors = {
    'Активный': '#2ecc71',
    'Предупреждение (>30 дней)': '#f39c12',
    'Риск оттока (>60 дней)': '#e67e22',
    'Отток (>90 дней)': '#e74c3c'
}
bars = ax3.bar(
    churn_df['status'], churn_df['count'],
    color=[churn_colors.get(s, '#95a5a6') for s in churn_df['status']],
    alpha=0.85
)
for bar, val in zip(bars, churn_df['count']):
    ax3.text(bar.get_x() + bar.get_width() / 2,
             bar.get_height() + 1,
             str(val), ha='center', va='bottom', fontweight='bold')
ax3.set_title('Анализ оттока клиентов (Churn)', fontweight='bold')
ax3.set_xlabel('Статус')
ax3.set_ylabel('Количество клиентов')
ax3.tick_params(axis='x', rotation=15)
ax3.grid(axis='y', alpha=0.3)

# График 4: Распределение времени между заказами
ax4 = axes[1, 1]
df_lag_plot = df_lag_clean[df_lag_clean['days_since_last_order'] <= 180]
ax4.hist(df_lag_plot['days_since_last_order'], bins=30,
         color='#9b59b6', alpha=0.75, edgecolor='white')
ax4.axvline(df_lag_plot['days_since_last_order'].mean(),
            color='red', linestyle='--', linewidth=2,
            label=f"Среднее: {df_lag_plot['days_since_last_order'].mean():.0f} дней")
ax4.axvline(df_lag_plot['days_since_last_order'].median(),
            color='orange', linestyle='--', linewidth=2,
            label=f"Медиана: {df_lag_plot['days_since_last_order'].median():.0f} дней")
ax4.set_title('Распределение времени между заказами', fontweight='bold')
ax4.set_xlabel('Дней между заказами')
ax4.set_ylabel('Количество случаев')
ax4.legend(fontsize=9)
ax4.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('reports/day32_cohort_analysis.png', dpi=150, bbox_inches='tight')
plt.close()
print("График сохранён: reports/day32_cohort_analysis.png")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("ДЕНЬ 32 ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Изученные паттерны LAG/LEAD и Cohort Analysis:

1. LAG/LEAD — базовые паттерны
   LAG(col, 1)  — предыдущая строка
   LEAD(col, 1) — следующая строка
   DATEDIFF     — дней между событиями

2. Time-between-events
   Среднее время между заказами клиента

3. FIRST_VALUE / LAST_VALUE
   Первая и последняя покупка клиента
   LTV, lifespan_days

4. Когортный анализ (Retention Rate)
   Определение когорты = месяц первого заказа
   Retention M+0, M+1, M+2...
   Heatmap когорт — визуализация retention

5. Сессионный анализ
   Группировка событий через SUM(is_new_session) OVER (...)

6. Churn Analysis
   Клиенты без заказов > N дней = отток

7. Повторные покупки в той же категории

Графики:
  reports/day32_cohort_analysis.png

Следующий день: День 33 — Advanced SQL (QUALIFY, PIVOT, UNPIVOT)
""")
