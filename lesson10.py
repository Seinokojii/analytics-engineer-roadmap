"""
День 10: Оптимизация SQL
Профилирование, индексы, оптимизация запросов
"""

import duckdb
import pandas as pd
import time

print("=" * 70)
print(" " * 15 + "⚡ ДЕНЬ 10: SQL ОПТИМИЗАЦИЯ")
print("=" * 70)

# ========================================
# ПОДГОТОВКА ДАННЫХ (Большая таблица)
# ========================================

print("\n📊 Генерируем тестовые данные...")

# Создаем большую таблицу: 100,000 заказов
import random
random.seed(42)

large_orders = pd.DataFrame({
    'order_id': range(1, 100001),
    'user_id': [random.randint(1, 10000) for _ in range(100000)],
    'product_id': [random.randint(1, 500) for _ in range(100000)],
    'amount': [random.randint(10, 5000) for _ in range(100000)],
    'order_date': pd.date_range('2023-01-01', periods=100000, freq='8s')
})

users = pd.DataFrame({
    'user_id': range(1, 10001),
    'name': [f'User_{i}' for i in range(1, 10001)],
    'city': [random.choice(['Москва', 'Казань', 'Омск', 'Екатеринбург']) 
             for _ in range(10000)],
    'segment': [random.choice(['VIP', 'Regular', 'New']) for _ in range(10000)]
})

print(f"✅ Создано:")
print(f"  - Заказов: {len(large_orders):,}")
print(f"  - Пользователей: {len(users):,}")

con = duckdb.connect()
con.register('orders', large_orders)
con.register('users', users)


# ========================================
# ПАТТЕРН 1: ИЗМЕРЕНИЕ ПРОИЗВОДИТЕЛЬНОСТИ
# ========================================

print("\n" + "=" * 70)
print("⏱️ ПАТТЕРН 1: Измерение времени выполнения")
print("=" * 70)

def measure_query(query, description):
    """Измеряет время выполнения запроса"""
    start = time.time()
    result = con.execute(query).df()
    duration = time.time() - start
    print(f"\n{description}")
    print(f"⏱️  Время: {duration:.4f} сек")
    print(f"📊 Строк: {len(result)}")
    return result, duration

# Тест 1: Простая фильтрация
query1 = "SELECT * FROM orders WHERE user_id = 1234"
r1, t1 = measure_query(query1, "❌ Плохо: SELECT * (все колонки)")

# Тест 2: Выбор только нужных колонок
query2 = "SELECT order_id, amount FROM orders WHERE user_id = 1234"
r2, t2 = measure_query(query2, "✅ Хорошо: SELECT только нужные колонки")

print(f"\n💡 Ускорение: {t1/t2:.2f}x (выбор колонок)")


# ========================================
# ПАТТЕРН 2: ОПТИМИЗАЦИЯ WHERE
# ========================================

print("\n" + "=" * 70)
print("🔍 ПАТТЕРН 2: Оптимизация фильтров WHERE")
print("=" * 70)

# ❌ Плохо: Функция в WHERE блокирует индексы
query_bad = """
SELECT COUNT(*) as orders_count
FROM orders 
WHERE EXTRACT(YEAR FROM order_date) = 2023
"""
r_bad, t_bad = measure_query(query_bad, "❌ Плохо: Функция в WHERE")

# ✅ Хорошо: Прямое сравнение дат
query_good = """
SELECT COUNT(*) as orders_count
FROM orders 
WHERE order_date >= '2023-01-01' AND order_date < '2024-01-01'
"""
r_good, t_good = measure_query(query_good, "✅ Хорошо: Прямое сравнение")

print(f"\n💡 Ускорение: {t_bad/t_good:.2f}x (избегание функций в WHERE)")


# ========================================
# ПАТТЕРН 3: ОПТИМИЗАЦИЯ JOIN
# ========================================

print("\n" + "=" * 70)
print("🔗 ПАТТЕРН 3: Оптимизация JOIN")
print("=" * 70)

# ❌ Плохо: JOIN без фильтрации → обрабатываем все 100k строк
query_join_bad = """
SELECT 
    u.name,
    o.order_id,
    o.amount
FROM orders o
JOIN users u ON o.user_id = u.user_id
WHERE u.city = 'Москва'
"""
r_join_bad, t_join_bad = measure_query(query_join_bad, "❌ Плохо: Фильтр ПОСЛЕ JOIN")

# ✅ Хорошо: Фильтруем ДО JOIN
query_join_good = """
WITH moscow_users AS (
    SELECT user_id, name 
    FROM users 
    WHERE city = 'Москва'
)
SELECT 
    u.name,
    o.order_id,
    o.amount
FROM orders o
JOIN moscow_users u ON o.user_id = u.user_id
"""
r_join_good, t_join_good = measure_query(query_join_good, "✅ Хорошо: Фильтр ДО JOIN (CTE)")

print(f"\n💡 Ускорение: {t_join_bad/t_join_good:.2f}x (ранняя фильтрация)")


# ========================================
# ПАТТЕРН 4: АГРЕГАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("📊 ПАТТЕРН 4: Эффективная агрегация")
print("=" * 70)

# ❌ Плохо: Множественные подзапросы
query_agg_bad = """
SELECT 
    user_id,
    (SELECT COUNT(*) FROM orders o2 WHERE o2.user_id = o1.user_id) as order_count,
    (SELECT SUM(amount) FROM orders o3 WHERE o3.user_id = o1.user_id) as total_spent
FROM orders o1
GROUP BY user_id
LIMIT 100
"""
r_agg_bad, t_agg_bad = measure_query(query_agg_bad, "❌ Плохо: Множественные подзапросы")

# ✅ Хорошо: Одна агрегация
query_agg_good = """
SELECT 
    user_id,
    COUNT(*) as order_count,
    SUM(amount) as total_spent
FROM orders
GROUP BY user_id
LIMIT 100
"""
r_agg_good, t_agg_good = measure_query(query_agg_good, "✅ Хорошо: Одна GROUP BY")

print(f"\n💡 Ускорение: {t_agg_bad/t_agg_good:.2f}x (оптимизация агрегации)")


# ========================================
# ПАТТЕРН 5: EXPLAIN ANALYZE
# ========================================

print("\n" + "=" * 70)
print("🔬 ПАТТЕРН 5: EXPLAIN - План выполнения")
print("=" * 70)

query_explain = """
EXPLAIN 
SELECT 
    u.city,
    COUNT(*) as orders_count,
    SUM(o.amount) as total_revenue
FROM orders o
JOIN users u ON o.user_id = u.user_id
WHERE o.amount > 1000
GROUP BY u.city
"""

explain_result = con.execute(query_explain).df()
print("\n📋 План выполнения:")
print(explain_result.to_string(index=False))

print("""
💡 Как читать EXPLAIN:
- HASH_JOIN: Эффективный алгоритм соединения
- FILTER: Применение WHERE условия
- AGGREGATE: Группировка GROUP BY
- SEQ_SCAN: Последовательное чтение (если таблица маленькая - ОК)

В production: Ищем "Seq Scan" на больших таблицах → нужен индекс!
""")


# ========================================
# ПАТТЕРН 6: ОПТИМИЗАЦИЯ DISTINCT
# ========================================

print("\n" + "=" * 70)
print("🎯 ПАТТЕРН 6: DISTINCT vs GROUP BY")
print("=" * 70)

# DISTINCT
query_distinct = """
SELECT DISTINCT user_id 
FROM orders 
WHERE amount > 500
"""
r_distinct, t_distinct = measure_query(query_distinct, "DISTINCT")

# GROUP BY
query_groupby = """
SELECT user_id 
FROM orders 
WHERE amount > 500
GROUP BY user_id
"""
r_groupby, t_groupby = measure_query(query_groupby, "GROUP BY")

print(f"\n💡 Разница: {abs(t_distinct - t_groupby):.4f} сек")
print("В DuckDB часто эквивалентны, но GROUP BY более гибкий (можно добавить COUNT)")


# ========================================
# ПРАКТИЧЕСКАЯ ЗАДАЧА: ДО/ПОСЛЕ ОПТИМИЗАЦИИ
# ========================================

print("\n" + "=" * 70)
print("🎯 ПРАКТИЧЕСКАЯ ЗАДАЧА: Оптимизация реального запроса")
print("=" * 70)

# ❌ НЕОПТИМИЗИРОВАННЫЙ запрос
query_before = """
SELECT 
    u.name,
    u.city,
    COUNT(*) as order_count,
    SUM(o.amount) as total_spent,
    AVG(o.amount) as avg_order,
    (SELECT MAX(amount) FROM orders WHERE user_id = u.user_id) as max_order
FROM users u
LEFT JOIN orders o ON u.user_id = o.user_id
WHERE EXTRACT(YEAR FROM o.order_date) = 2023
GROUP BY u.user_id, u.name, u.city
HAVING COUNT(*) > 5
ORDER BY total_spent DESC
LIMIT 10
"""

print("\n⏱️ НЕОПТИМИЗИРОВАННЫЙ запрос:")
r_before, t_before = measure_query(query_before, "❌ До оптимизации")

# ✅ ОПТИМИЗИРОВАННЫЙ запрос
query_after = """
WITH orders_2023 AS (
    SELECT 
        user_id,
        amount
    FROM orders
    WHERE order_date >= '2023-01-01' AND order_date < '2024-01-01'
),
user_stats AS (
    SELECT 
        user_id,
        COUNT(*) as order_count,
        SUM(amount) as total_spent,
        AVG(amount) as avg_order,
        MAX(amount) as max_order
    FROM orders_2023
    GROUP BY user_id
    HAVING COUNT(*) > 5
)
SELECT 
    u.name,
    u.city,
    s.order_count,
    s.total_spent,
    s.avg_order,
    s.max_order
FROM user_stats s
JOIN users u ON s.user_id = u.user_id
ORDER BY s.total_spent DESC
LIMIT 10
"""

print("\n⏱️ ОПТИМИЗИРОВАННЫЙ запрос:")
r_after, t_after = measure_query(query_after, "✅ После оптимизации")

print(f"\n🚀 ИТОГОВОЕ УСКОРЕНИЕ: {t_before/t_after:.2f}x")

print("""
🔧 Примененные техники:
1. ✅ Заменили EXTRACT на прямое сравнение дат
2. ✅ Предфильтрация через CTE (orders_2023)
3. ✅ Убрали коррелированный подзапрос в SELECT
4. ✅ Агрегация в одном месте (user_stats)
5. ✅ HAVING перенесли ближе к GROUP BY
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 10 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил оптимизацию SQL:
1. ✅ Измерение производительности (time.time())
2. ✅ SELECT только нужные колонки (не *)
3. ✅ Избегание функций в WHERE
4. ✅ Ранняя фильтрация ДО JOIN
5. ✅ Оптимизация агрегаций
6. ✅ EXPLAIN - чтение планов выполнения
7. ✅ Реальный кейс: 3-5x ускорение запроса

💡 Главное правило: "Обрабатывай меньше данных как можно раньше!"

Следующий шаг: День 11 - Pandas Deep Dive!
""")

con.close()