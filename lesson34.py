"""
День 34: SQL Оптимизация запросов
EXPLAIN, медленные vs быстрые запросы, паттерны оптимизации
"""

import pandas as pd
import numpy as np
import duckdb
import time
import matplotlib.pyplot as plt
from pathlib import Path

plt.rcParams['font.family'] = 'DejaVu Sans'

print("=" * 70)
print(" " * 10 + "ДЕНЬ 34: SQL ОПТИМИЗАЦИЯ ЗАПРОСОВ")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)

con = duckdb.connect(':memory:')


# ========================================
# ЧАСТЬ 1: ГЕНЕРАЦИЯ БОЛЬШИХ ДАННЫХ
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Генерация данных (1М заказов)")
print("=" * 70)

np.random.seed(42)
N = 1_000_000

print(f"Генерация {N:,} заказов...")
start = time.time()

orders_big = pd.DataFrame({
    'order_id':   range(1, N + 1),
    'customer_id': np.random.randint(1, 10001, N),
    'product_id':  np.random.randint(1, 1001, N),
    'category':   np.random.choice(
        ['Электроника', 'Одежда', 'Дом', 'Спорт', 'Книги'], N
    ),
    'city':       np.random.choice(
        ['Москва', 'СПб', 'Казань', 'Екб', 'НСК',
         'Краснодар', 'Ростов', 'Уфа', 'Пермь', 'Волгоград'], N
    ),
    'status':     np.random.choice(
        ['completed', 'cancelled', 'refunded'], N, p=[0.7, 0.2, 0.1]
    ),
    'amount':     np.random.randint(100, 50000, N),
    'order_date': pd.date_range('2022-01-01', periods=N, freq='31s'),
})
orders_big['month']   = orders_big['order_date'].dt.month
orders_big['year']    = orders_big['order_date'].dt.year
orders_big['quarter'] = orders_big['order_date'].dt.quarter

elapsed = time.time() - start
print(f"Сгенерировано за {elapsed:.1f}с")

con.execute("CREATE TABLE orders AS SELECT * FROM orders_big")
print(f"Таблица загружена: {con.execute('SELECT COUNT(*) FROM orders').fetchone()[0]:,} строк")


# ========================================
# ЧАСТЬ 2: EXPLAIN — ЧИТАЕМ ПЛАН ЗАПРОСА
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: EXPLAIN — план выполнения запроса")
print("=" * 70)

print("EXPLAIN простого запроса:")
plan = con.execute("""
    EXPLAIN SELECT city, SUM(amount) AS выручка
    FROM orders
    WHERE status = 'completed'
    GROUP BY city
    ORDER BY выручка DESC
""").df()
print(plan.to_string(index=False))

print("\nEXPLAIN ANALYZE (с реальными метриками):")
plan_analyze = con.execute("""
    EXPLAIN ANALYZE SELECT city, SUM(amount)
    FROM orders
    WHERE city = 'Москва' AND status = 'completed'
    GROUP BY city
""").df()
# Показываем первые строки плана
print(plan_analyze.head(10).to_string(index=False))


# ========================================
# ЧАСТЬ 3: МЕДЛЕННЫЕ VS БЫСТРЫЕ ЗАПРОСЫ
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: Медленные vs быстрые запросы")
print("=" * 70)

def benchmark(name: str, query: str, runs: int = 3) -> float:
    """Замер времени выполнения запроса (среднее из N запусков)"""
    times = []
    for _ in range(runs):
        t = time.time()
        con.execute(query).df()
        times.append(time.time() - t)
    avg = sum(times) / len(times)
    print(f"  {name}: {avg*1000:.1f}мс")
    return avg


print("\n--- ПАТТЕРН 1: SELECT * vs SELECT нужных столбцов ---")
t1 = benchmark("SELECT *",
    "SELECT * FROM orders WHERE status = 'completed' LIMIT 1000")
t2 = benchmark("SELECT нужных",
    "SELECT order_id, amount, city FROM orders WHERE status = 'completed' LIMIT 1000")
print(f"  Ускорение: {t1/t2:.1f}x")

print("\n--- ПАТТЕРН 2: SARGable условия ---")
t3 = benchmark("Не SARGable (LOWER)",
    "SELECT COUNT(*) FROM orders WHERE LOWER(city) = 'москва'")
t4 = benchmark("SARGable (прямое сравнение)",
    "SELECT COUNT(*) FROM orders WHERE city = 'Москва'")
print(f"  Ускорение: {t3/t4:.1f}x")

print("\n--- ПАТТЕРН 3: EXISTS vs IN vs JOIN ---")
con.execute("""
    CREATE TABLE vip_customers AS
    SELECT DISTINCT customer_id FROM orders
    WHERE amount > 40000
""")

t5 = benchmark("IN (подзапрос)",
    "SELECT COUNT(*) FROM orders WHERE customer_id IN (SELECT customer_id FROM vip_customers)")
t6 = benchmark("EXISTS",
    "SELECT COUNT(*) FROM orders o WHERE EXISTS (SELECT 1 FROM vip_customers v WHERE v.customer_id = o.customer_id)")
t7 = benchmark("JOIN",
    "SELECT COUNT(*) FROM orders o JOIN vip_customers v ON o.customer_id = v.customer_id")
print(f"  IN vs EXISTS: {t5/t6:.1f}x | IN vs JOIN: {t5/t7:.1f}x")

print("\n--- ПАТТЕРН 4: DISTINCT vs GROUP BY ---")
t8 = benchmark("DISTINCT",
    "SELECT DISTINCT city FROM orders")
t9 = benchmark("GROUP BY",
    "SELECT city FROM orders GROUP BY city")
print(f"  Разница: {t8/t9:.1f}x")

print("\n--- ПАТТЕРН 5: Фильтрация до vs после агрегации ---")
t10 = benchmark("HAVING (фильтр после агрегации)",
    """SELECT city, SUM(amount) AS rev FROM orders
       GROUP BY city HAVING city = 'Москва'""")
t11 = benchmark("WHERE (фильтр до агрегации)",
    """SELECT city, SUM(amount) AS rev FROM orders
       WHERE city = 'Москва' GROUP BY city""")
print(f"  Ускорение WHERE vs HAVING: {t10/t11:.1f}x")

print("\n--- ПАТТЕРН 6: Подзапрос vs CTE ---")
t12 = benchmark("Подзапрос",
    """SELECT city, avg_amount FROM (
       SELECT city, AVG(amount) AS avg_amount FROM orders
       WHERE status = 'completed' GROUP BY city
    ) WHERE avg_amount > 10000""")
t13 = benchmark("CTE",
    """WITH city_avg AS (
       SELECT city, AVG(amount) AS avg_amount FROM orders
       WHERE status = 'completed' GROUP BY city
    ) SELECT city, avg_amount FROM city_avg WHERE avg_amount > 10000""")
print(f"  Разница CTE vs подзапрос: {t12/t13:.2f}x (обычно одинаково)")


# ========================================
# ЧАСТЬ 4: ПРАВИЛА ОПТИМИЗАЦИИ
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: Правила оптимизации — шпаргалка")
print("=" * 70)

optimizations = [
    ("1. Ранняя фильтрация",
     "WHERE перед JOIN снижает объём данных",
     "WHERE status='completed' перед JOIN"),
    ("2. SARGable условия",
     "Не применяй функции к столбцу в WHERE",
     "city = 'Москва' вместо LOWER(city) = 'москва'"),
    ("3. SELECT нужных столбцов",
     "Не SELECT * в аналитических запросах",
     "SELECT id, amount вместо SELECT *"),
    ("4. WHERE вместо HAVING",
     "HAVING фильтрует после агрегации — медленно",
     "WHERE city = 'X' вместо HAVING city = 'X'"),
    ("5. EXISTS вместо IN с подзапросом",
     "EXISTS останавливается на первом совпадении",
     "WHERE EXISTS (SELECT 1 FROM ...)"),
    ("6. LIMIT при отладке",
     "Всегда добавляй LIMIT при разработке запроса",
     "LIMIT 1000 во время тестирования"),
    ("7. Избегай SELECT DISTINCT",
     "GROUP BY часто быстрее DISTINCT",
     "GROUP BY вместо DISTINCT"),
    ("8. Материализуй тяжёлые CTE",
     "В DuckDB CTE выполняется каждый раз если используется несколько раз",
     "CREATE TEMP TABLE вместо CTE при многократном использовании"),
]

for rule, desc, example in optimizations:
    print(f"\n  {rule}")
    print(f"  → {desc}")
    print(f"  ✓ {example}")


# ========================================
# ЧАСТЬ 5: АНТИПАТТЕРНЫ
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: SQL антипаттерны")
print("=" * 70)

antipatterns = {
    "N+1 запрос": {
        "плохо": "for customer in customers: SELECT orders WHERE customer_id = X",
        "хорошо": "SELECT * FROM orders WHERE customer_id IN (SELECT customer_id FROM customers)"
    },
    "Избыточный DISTINCT": {
        "плохо": "SELECT DISTINCT a.id FROM a JOIN b ON a.id = b.a_id",
        "хорошо": "SELECT a.id FROM a WHERE EXISTS (SELECT 1 FROM b WHERE b.a_id = a.id)"
    },
    "Функция на индексном столбце": {
        "плохо": "WHERE YEAR(order_date) = 2024",
        "хорошо": "WHERE order_date >= '2024-01-01' AND order_date < '2025-01-01'"
    },
    "LIKE с ведущим %": {
        "плохо": "WHERE city LIKE '%осква'  -- не использует индекс",
        "хорошо": "WHERE city LIKE 'Мос%'   -- использует индекс"
    },
    "Неявное преобразование типов": {
        "плохо": "WHERE customer_id = '123'  -- строка вместо числа",
        "хорошо": "WHERE customer_id = 123   -- правильный тип"
    },
}

for name, examples in antipatterns.items():
    print(f"\n  ❌ {name}:")
    print(f"     Плохо:  {examples['плохо']}")
    print(f"     Хорошо: {examples['хорошо']}")


# ========================================
# ЧАСТЬ 6: ВИЗУАЛИЗАЦИЯ БЕНЧМАРКОВ
# ========================================

print("\n" + "=" * 70)
print("6  ЧАСТЬ 6: Визуализация результатов бенчмарков")
print("=" * 70)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle('День 34: SQL Оптимизация — Сравнение запросов',
             fontsize=14, fontweight='bold')

# График 1: Сравнение времён
ax1 = axes[0]
patterns = [
    'SELECT *\nvс SELECT нужных',
    'Не SARGable\nvс SARGable',
    'HAVING\nvс WHERE',
]
slow_times = [t1*1000, t3*1000, t10*1000]
fast_times = [t2*1000, t4*1000, t11*1000]

x = np.arange(len(patterns))
width = 0.35
bars1 = ax1.bar(x - width/2, slow_times, width,
                label='Медленный запрос', color='#e74c3c', alpha=0.8)
bars2 = ax1.bar(x + width/2, fast_times, width,
                label='Быстрый запрос', color='#2ecc71', alpha=0.8)

for bar, val in zip(bars1, slow_times):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
             f'{val:.0f}мс', ha='center', va='bottom', fontsize=8)
for bar, val in zip(bars2, fast_times):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
             f'{val:.0f}мс', ha='center', va='bottom', fontsize=8)

ax1.set_title('Медленные vs Быстрые запросы', fontweight='bold')
ax1.set_ylabel('Время выполнения (мс)')
ax1.set_xticks(x)
ax1.set_xticklabels(patterns, fontsize=9)
ax1.legend()
ax1.grid(axis='y', alpha=0.3)

# График 2: Коэффициенты ускорения
ax2 = axes[1]
speedups = {
    'SELECT нужных\nвс SELECT *': t1/t2,
    'SARGable\nвс LOWER()': t3/t4,
    'WHERE\nвс HAVING': t10/t11,
    'JOIN\nвс IN': t5/t7,
}
colors_spd = ['#2ecc71' if v > 1 else '#e74c3c' for v in speedups.values()]
bars3 = ax2.bar(speedups.keys(), speedups.values(),
                color=colors_spd, alpha=0.85)
ax2.axhline(y=1, color='black', linewidth=1, linestyle='--')
for bar, val in zip(bars3, speedups.values()):
    ax2.text(bar.get_x() + bar.get_width()/2,
             bar.get_height() + 0.02,
             f'{val:.1f}x', ha='center', va='bottom',
             fontsize=10, fontweight='bold')
ax2.set_title('Коэффициент ускорения', fontweight='bold')
ax2.set_ylabel('Ускорение (во сколько раз быстрее)')
ax2.tick_params(axis='x', rotation=10)
ax2.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig('reports/day34_sql_optimization.png', dpi=150, bbox_inches='tight')
plt.close()
print("График сохранён: reports/day34_sql_optimization.png")

con.close()


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("ДЕНЬ 34 ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Изученные техники SQL оптимизации:

1. EXPLAIN / EXPLAIN ANALYZE
   Читаем план запроса — находим узкие места

2. SARGable условия
   city = 'Москва' быстрее LOWER(city) = 'москва'

3. WHERE раньше HAVING
   Фильтруй до агрегации — меньше данных обрабатывается

4. SELECT нужных столбцов
   Не тащи ненужные данные из хранилища

5. EXISTS vs IN
   EXISTS останавливается на первом совпадении

6. DISTINCT vs GROUP BY
   GROUP BY часто эффективнее

7. Функции на индексных столбцах — антипаттерн
   YEAR(date) = 2024 → date BETWEEN '2024-01-01' AND '2024-12-31'

8. LIMIT при разработке
   Всегда ограничивай объём при тестировании

5 антипаттернов:
  N+1 запрос, избыточный DISTINCT,
  функция на индексном столбце, LIKE с ведущим %,
  неявное преобразование типов

График: reports/day34_sql_optimization.png

Следующий день: День 35 — Week 5 Checkpoint
""")