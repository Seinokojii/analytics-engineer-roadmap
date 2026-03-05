"""
День 35: EXPLAIN ANALYZE глубже — оптимизация 3 slow queries
Читаем план запроса, находим узкие места, переписываем
"""

import pandas as pd
import numpy as np
import duckdb
import time
import matplotlib.pyplot as plt
from pathlib import Path

plt.rcParams['font.family'] = 'DejaVu Sans'

print("=" * 70)
print(" " * 5 + "ДЕНЬ 35: EXPLAIN ANALYZE — ОПТИМИЗАЦИЯ ЗАПРОСОВ")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)

con = duckdb.connect(':memory:')


# ========================================
# ЧАСТЬ 1: ГЕНЕРАЦИЯ ДАННЫХ (500К строк)
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Генерация данных — 500К заказов")
print("=" * 70)

np.random.seed(42)
N = 500_000

print(f"Генерация {N:,} строк...")
t0 = time.time()

orders = pd.DataFrame({
    'order_id':    range(1, N + 1),
    'customer_id': np.random.randint(1, 10001, N),
    'product_id':  np.random.randint(1, 2001, N),
    'category':    np.random.choice(
        ['Электроника', 'Одежда', 'Дом', 'Спорт', 'Книги'], N
    ),
    'city':        np.random.choice(
        ['Москва', 'СПб', 'Казань', 'Екб', 'НСК',
         'Краснодар', 'Ростов', 'Уфа', 'Пермь', 'Волгоград'], N
    ),
    'status':      np.random.choice(
        ['completed', 'cancelled', 'refunded', 'pending'],
        N, p=[0.65, 0.20, 0.10, 0.05]
    ),
    'amount':      np.random.randint(100, 50000, N),
    'discount':    np.random.choice([0, 5, 10, 15, 20], N),
    'order_date':  pd.date_range('2022-01-01', periods=N, freq='63s'),
})
orders['total']   = orders['amount'] * (1 - orders['discount'] / 100)
orders['month']   = orders['order_date'].dt.month
orders['year']    = orders['order_date'].dt.year
orders['quarter'] = orders['order_date'].dt.quarter

con.execute("CREATE TABLE orders AS SELECT * FROM orders")
print(f"Загружено за {time.time()-t0:.1f}с | Строк: {N:,}")
print(f"Размер в памяти: {orders.memory_usage(deep=True).sum() / 1024**2:.1f} МБ")


# ========================================
# ЧАСТЬ 2: ЧИТАЕМ EXPLAIN ANALYZE
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: Читаем EXPLAIN ANALYZE")
print("=" * 70)

print("""
Как читать EXPLAIN ANALYZE:

  ┌─────────────────────────────────────────────────┐
  │ Физический план (Physical Plan):                │
  │                                                  │
  │ HASH_JOIN              ← тип операции           │
  │   SEQ_SCAN orders      ← полный скан (медленно) │
  │   SEQ_SCAN customers   ← полный скан             │
  │                                                  │
  │ Ключевые операции:                               │
  │   SEQ_SCAN   — читает всю таблицу               │
  │   FILTER     — фильтрация строк                 │
  │   HASH_JOIN  — соединение через хэш             │
  │   PROJECTION — выбор столбцов                   │
  │   AGGREGATE  — GROUP BY, COUNT, SUM             │
  │   ORDER      — сортировка                       │
  └─────────────────────────────────────────────────┘
""")

# Показываем реальный план
print("EXPLAIN реального запроса:")
plan = con.execute("""
    EXPLAIN
    SELECT city, category, SUM(total) AS выручка, COUNT(*) AS заказов
    FROM orders
    WHERE status = 'completed' AND year = 2022
    GROUP BY city, category
    ORDER BY выручка DESC
""").df()
for _, row in plan.iterrows():
    print(row.iloc[1][:500])


# ========================================
# ЧАСТЬ 3: SLOW QUERY 1 — ФУНКЦИЯ НА СТОЛБЦЕ
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: Slow Query 1 — Функция на столбце фильтрации")
print("=" * 70)

print("Проблема: функция EXTRACT() мешает оптимизатору")

def run(query, runs=3):
    times = []
    for _ in range(runs):
        t = time.time()
        con.execute(query).df()
        times.append(time.time() - t)
    return round(sum(times)/len(times)*1000, 1)


# МЕДЛЕННО
slow_q1 = """
SELECT COUNT(*), SUM(total)
FROM orders
WHERE EXTRACT(YEAR FROM order_date) = 2022
  AND EXTRACT(MONTH FROM order_date) = 6
  AND status = 'completed'
"""

# БЫСТРО
fast_q1 = """
SELECT COUNT(*), SUM(total)
FROM orders
WHERE order_date >= '2022-06-01'
  AND order_date <  '2022-07-01'
  AND status = 'completed'
"""

t_slow1 = run(slow_q1)
t_fast1 = run(fast_q1)

print(f"\n  Медленно (EXTRACT):        {t_slow1:.0f}мс")
print(f"  Быстро  (диапазон дат):    {t_fast1:.0f}мс")
print(f"  Ускорение:                 {t_slow1/t_fast1:.1f}x")

print("""
  Было:   WHERE EXTRACT(YEAR FROM order_date) = 2022
  Стало:  WHERE order_date >= '2022-01-01' AND order_date < '2023-01-01'

  Почему: EXTRACT() вычисляется для КАЖДОЙ строки → нельзя использовать
          индекс. Прямое сравнение дат — SARGable запрос.
""")


# ========================================
# ЧАСТЬ 4: SLOW QUERY 2 — HAVING ВМЕСТО WHERE
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: Slow Query 2 — HAVING вместо WHERE")
print("=" * 70)

print("Проблема: HAVING фильтрует ПОСЛЕ агрегации — обрабатывает лишние данные")

# МЕДЛЕННО — фильтр статуса в HAVING
slow_q2 = """
SELECT city, SUM(total) AS выручка, COUNT(*) AS заказов
FROM orders
GROUP BY city
HAVING SUM(CASE WHEN status = 'completed' THEN total ELSE 0 END) > 0
   AND city IN ('Москва', 'СПб', 'Казань')
"""

# БЫСТРО — фильтр статуса в WHERE
fast_q2 = """
SELECT city, SUM(total) AS выручка, COUNT(*) AS заказов
FROM orders
WHERE status = 'completed'
  AND city IN ('Москва', 'СПб', 'Казань')
GROUP BY city
"""

t_slow2 = run(slow_q2)
t_fast2 = run(fast_q2)

print(f"\n  Медленно (HAVING фильтр):  {t_slow2:.0f}мс")
print(f"  Быстро  (WHERE фильтр):    {t_fast2:.0f}мс")
print(f"  Ускорение:                 {t_slow2/t_fast2:.1f}x")

print("""
  Было:   GROUP BY city HAVING SUM(CASE WHEN status='completed' ...)
  Стало:  WHERE status = 'completed' GROUP BY city

  Почему: WHERE убирает строки ДО агрегации (меньше данных в GROUP BY)
          HAVING работает ПОСЛЕ — агрегирует ВСЁ, потом фильтрует
""")


# ========================================
# ЧАСТЬ 5: SLOW QUERY 3 — SELECT * + DISTINCT
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: Slow Query 3 — SELECT * и лишний DISTINCT")
print("=" * 70)

print("Проблема: тащим все столбцы + DISTINCT вместо GROUP BY")

# МЕДЛЕННО
slow_q3 = """
SELECT DISTINCT customer_id, city, category
FROM orders
WHERE status = 'completed'
ORDER BY customer_id
"""

# БЫСТРО
fast_q3 = """
SELECT customer_id, city, category
FROM orders
WHERE status = 'completed'
GROUP BY customer_id, city, category
ORDER BY customer_id
"""

# Ещё быстрее — только нужные столбцы без ORDER BY (при отладке)
fastest_q3 = """
SELECT customer_id, city, category
FROM orders
WHERE status = 'completed'
GROUP BY customer_id, city, category
LIMIT 1000
"""

t_slow3    = run(slow_q3)
t_fast3    = run(fast_q3)
t_fastest3 = run(fastest_q3)

print(f"\n  Медленно (DISTINCT + ORDER):   {t_slow3:.0f}мс")
print(f"  Быстро   (GROUP BY + ORDER):   {t_fast3:.0f}мс")
print(f"  Быстрее  (GROUP BY + LIMIT):   {t_fastest3:.0f}мс")
print(f"  Ускорение DISTINCT→GROUP BY:   {t_slow3/t_fast3:.1f}x")

print("""
  Было:   SELECT DISTINCT customer_id, city, category
  Стало:  SELECT customer_id, city, category GROUP BY ...

  Почему: DISTINCT сортирует все строки для дедупликации
          GROUP BY может использовать хэш — быстрее
          ORDER BY без LIMIT — читает все строки и сортирует
""")


# ========================================
# ЧАСТЬ 6: ДОПОЛНИТЕЛЬНЫЕ ТЕХНИКИ
# ========================================

print("\n" + "=" * 70)
print("6  ЧАСТЬ 6: Дополнительные техники оптимизации")
print("=" * 70)

# Предагрегация в CTE
print("--- Предагрегация в CTE ---")
slow_q4 = """
SELECT
    o1.customer_id,
    COUNT(o1.order_id) AS заказов,
    SUM(o1.total)      AS ltv
FROM orders o1
JOIN orders o2 ON o1.customer_id = o2.customer_id
WHERE o1.status = 'completed' AND o2.status = 'completed'
GROUP BY o1.customer_id
HAVING COUNT(DISTINCT o1.order_id) > 3
LIMIT 100
"""

fast_q4 = """
WITH customer_stats AS (
    SELECT customer_id,
           COUNT(*)  AS заказов,
           SUM(total) AS ltv
    FROM orders
    WHERE status = 'completed'
    GROUP BY customer_id
    HAVING COUNT(*) > 3
)
SELECT * FROM customer_stats
ORDER BY ltv DESC
LIMIT 100
"""

t_slow4 = run(slow_q4)
t_fast4 = run(fast_q4)
print(f"  Self-JOIN:      {t_slow4:.0f}мс")
print(f"  CTE агрегация:  {t_fast4:.0f}мс")
print(f"  Ускорение:      {t_slow4/t_fast4:.1f}x")

# Partial aggregation — предфильтрация
print("\n--- Columnar pushdown — читаем только нужные столбцы ---")
slow_q5 = "SELECT AVG(total), COUNT(*) FROM orders WHERE status = 'completed'"
fast_q5 = "SELECT AVG(total), COUNT(*) FROM (SELECT total FROM orders WHERE status = 'completed')"
t_slow5 = run(slow_q5)
t_fast5 = run(fast_q5)
print(f"  SELECT *:              {t_slow5:.0f}мс")
print(f"  Только нужные столбцы: {t_fast5:.0f}мс")


# ========================================
# ЧАСТЬ 7: ШПАРГАЛКА EXPLAIN ANALYZE
# ========================================

print("\n" + "=" * 70)
print("7  ЧАСТЬ 7: Шпаргалка — как читать план")
print("=" * 70)

print("""
┌──────────────────────┬────────────────────────────────────────────┐
│ Операция             │ Что означает                               │
├──────────────────────┼────────────────────────────────────────────┤
│ SEQ_SCAN             │ Читает ВСЕ строки — ок для малых таблиц   │
│ FILTER               │ Применяет WHERE условие                    │
│ HASH_JOIN            │ JOIN через хэш-таблицу — O(N+M)           │
│ NESTED_LOOP          │ JOIN через цикл — O(N×M), медленно        │
│ HASH_GROUP_BY        │ GROUP BY через хэш                         │
│ STREAMING_WINDOW     │ Оконная функция                            │
│ ORDER                │ Сортировка — дорого без LIMIT              │
│ PROJECTION           │ SELECT нужных столбцов                     │
│ AGGREGATE            │ Агрегация (SUM, COUNT, AVG)                │
├──────────────────────┼────────────────────────────────────────────┤
│ На что смотреть:                                                   │
│  • Большой SEQ_SCAN на огромной таблице → нужен фильтр раньше    │
│  • NESTED_LOOP на больших таблицах → переписать JOIN              │
│  • ORDER без LIMIT → добавить LIMIT при разработке               │
│  • Функция в FILTER → убрать функцию с индексного столбца        │
└──────────────────────────────────────────────────────────────────┘
""")


# ========================================
# ЧАСТЬ 8: ВИЗУАЛИЗАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("8  ЧАСТЬ 8: Визуализация ускорений")
print("=" * 70)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle('День 35: EXPLAIN ANALYZE — Ускорение запросов',
             fontsize=14, fontweight='bold')

# График 1: Медленные vs быстрые
ax1 = axes[0]
queries = [
    'EXTRACT()\nвс диапазон дат',
    'HAVING\nвс WHERE',
    'DISTINCT\nвс GROUP BY',
    'Self-JOIN\nвс CTE',
]
slow_times = [t_slow1, t_slow2, t_slow3, t_slow4]
fast_times = [t_fast1, t_fast2, t_fast3, t_fast4]

x = np.arange(len(queries))
w = 0.35
b1 = ax1.bar(x - w/2, slow_times, w, label='До оптимизации',
             color='#e74c3c', alpha=0.85)
b2 = ax1.bar(x + w/2, fast_times, w, label='После оптимизации',
             color='#2ecc71', alpha=0.85)
for bar, val in zip(b1, slow_times):
    ax1.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
             f'{val:.0f}', ha='center', va='bottom', fontsize=8)
for bar, val in zip(b2, fast_times):
    ax1.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
             f'{val:.0f}', ha='center', va='bottom', fontsize=8)
ax1.set_title('Время выполнения (мс): до и после', fontweight='bold')
ax1.set_ylabel('Время (мс)')
ax1.set_xticks(x)
ax1.set_xticklabels(queries, fontsize=8)
ax1.legend()
ax1.grid(axis='y', alpha=0.3)

# График 2: Коэффициент ускорения
ax2 = axes[1]
speedups = [t_slow1/t_fast1, t_slow2/t_fast2,
            t_slow3/t_fast3, t_slow4/t_fast4]
labels = ['EXTRACT\n→ диапазон', 'HAVING\n→ WHERE',
          'DISTINCT\n→ GROUP BY', 'Self-JOIN\n→ CTE']
colors = ['#e74c3c' if s < 1.5 else '#f39c12' if s < 3 else '#2ecc71'
          for s in speedups]
bars = ax2.bar(labels, speedups, color=colors, alpha=0.85)
ax2.axhline(y=1, color='black', linewidth=1, linestyle='--')
for bar, val in zip(bars, speedups):
    ax2.text(bar.get_x()+bar.get_width()/2,
             bar.get_height()+0.05,
             f'{val:.1f}x', ha='center', va='bottom',
             fontsize=12, fontweight='bold')
ax2.set_title('Коэффициент ускорения', fontweight='bold')
ax2.set_ylabel('Во сколько раз быстрее')
ax2.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig('reports/day35_explain_analyze.png', dpi=150, bbox_inches='tight')
plt.close()
print("График сохранён: reports/day35_explain_analyze.png")

con.close()

print("\n" + "=" * 70)
print("ДЕНЬ 35 ЗАВЕРШЁН!")
print("=" * 70)
print("""
3 slow query оптимизированы:

1. EXTRACT(YEAR FROM date) = 2022
   → date >= '2022-01-01' AND date < '2023-01-01'
   Почему: SARGable условия позволяют использовать индекс

2. GROUP BY ... HAVING status = 'completed'
   → WHERE status = 'completed' GROUP BY ...
   Почему: WHERE фильтрует ДО агрегации — меньше данных

3. SELECT DISTINCT ... ORDER BY
   → SELECT ... GROUP BY ... (+ LIMIT при отладке)
   Почему: GROUP BY через хэш быстрее сортировки DISTINCT

4. Self-JOIN для агрегации
   → CTE с предагрегацией
   Почему: декартово произведение vs однопроходная агрегация

Шпаргалка EXPLAIN:
  SEQ_SCAN — полный скан (норма для малых таблиц)
  NESTED_LOOP — опасно на больших таблицах
  ORDER без LIMIT — всегда добавляй LIMIT при разработке

График: reports/day35_explain_analyze.png
Следующий день: День 36 — Pandas vs Polars performance
""")