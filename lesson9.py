"""
День 9: CTE (WITH) и подзапросы
Читаемый код для сложной аналитики
"""

import duckdb
import pandas as pd

print("=" * 70)
print(" " * 20 + "📝 ДЕНЬ 9: CTE")
print("=" * 70)

# ========================================
# ПОДГОТОВКА ДАННЫХ
# ========================================

users_df = pd.DataFrame({
    'user_id': [1, 2, 3, 4, 5],
    'name': ['Алексей', 'Мария', 'Иван', 'Анна', 'Дмитрий'],
    'city': ['Москва', 'Казань', 'Москва', 'Омск', 'Москва'],
    'segment': ['VIP', 'Regular', 'VIP', 'Regular', 'Regular']
})

orders_df = pd.DataFrame({
    'order_id': range(1, 16),
    'user_id': [1, 2, 1, 3, 2, 1, 4, 5, 1, 2, 3, 1, 2, 5, 3],
    'product_category': ['Tech', 'Tech', 'Office', 'Tech', 'Office',
                         'Tech', 'Tech', 'Office', 'Tech', 'Tech',
                         'Office', 'Tech', 'Tech', 'Office', 'Tech'],
    'amount': [1200, 25, 500, 350, 600, 1100, 400, 300, 1250, 30, 
               450, 1150, 40, 280, 380],
    'order_date': pd.date_range('2024-01-01', periods=15, freq='3D')
})

con = duckdb.connect()
con.register('users', users_df)
con.register('orders', orders_df)

print("\n✅ Данные загружены:")
print(f"  Пользователей: {len(users_df)}")
print(f"  Заказов: {len(orders_df)}")


# ========================================
# ПРИМЕР 1: ПРОСТОЙ CTE
# ========================================

print("\n" + "=" * 70)
print("📌 ПРИМЕР 1: Базовый CTE")
print("=" * 70)

query1 = """
WITH expensive_orders AS (
    SELECT * 
    FROM orders 
    WHERE amount > 500
)
SELECT 
    COUNT(*) as expensive_orders_count,
    SUM(amount) as total_expensive_revenue
FROM expensive_orders
"""

result1 = con.execute(query1).df()
print(result1.to_string(index=False))

print("""
💡 Что произошло:
1. CTE "expensive_orders" = фильтр заказов > 500₽
2. Основной запрос считает статистику по этой выборке

Преимущество: Можно переиспользовать "expensive_orders" несколько раз
""")


# ========================================
# ПРИМЕР 2: МНОЖЕСТВЕННЫЕ CTE
# ========================================

print("\n" + "=" * 70)
print("📌 ПРИМЕР 2: Цепочка CTE (Multi-step)")
print("=" * 70)

query2 = """
WITH 
-- Шаг 1: Агрегируем по пользователям
user_stats AS (
    SELECT 
        user_id,
        COUNT(*) as order_count,
        SUM(amount) as total_spent,
        AVG(amount) as avg_order
    FROM orders
    GROUP BY user_id
),
-- Шаг 2: Добавляем инфо о пользователях
enriched AS (
    SELECT 
        u.name,
        u.city,
        u.segment,
        s.order_count,
        s.total_spent,
        s.avg_order
    FROM user_stats s
    JOIN users u ON s.user_id = u.user_id
),
-- Шаг 3: Классифицируем клиентов
classified AS (
    SELECT 
        *,
        CASE 
            WHEN total_spent > 3000 THEN 'High Value'
            WHEN total_spent > 1000 THEN 'Medium Value'
            ELSE 'Low Value'
        END as value_tier
    FROM enriched
)
SELECT * FROM classified
ORDER BY total_spent DESC
"""

result2 = con.execute(query2).df()
print(result2.to_string(index=False))

print("""
💡 Что произошло:
1. user_stats: Агрегация заказов по юзерам
2. enriched: JOIN с таблицей users (добавили имена/города)
3. classified: Добавили сегментацию по LTV (Lifetime Value)

В production: Так строятся модели в dbt!
Каждый CTE = отдельная трансформация
""")


# ========================================
# ПРИМЕР 3: CTE + WINDOW FUNCTIONS
# ========================================

print("\n" + "=" * 70)
print("📌 ПРИМЕР 3: CTE + оконные функции")
print("=" * 70)

query3 = """
WITH daily_revenue AS (
    SELECT 
        DATE_TRUNC('day', order_date) as date,
        SUM(amount) as revenue
    FROM orders
    GROUP BY date
),
with_moving_avg AS (
    SELECT 
        date,
        revenue,
        AVG(revenue) OVER (
            ORDER BY date 
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS moving_avg_3days
    FROM daily_revenue
)
SELECT 
    date,
    revenue,
    ROUND(moving_avg_3days, 2) as moving_avg,
    CASE 
        WHEN revenue > moving_avg_3days THEN '📈 Выше среднего'
        ELSE '📉 Ниже среднего'
    END as trend
FROM with_moving_avg
ORDER BY date
"""

result3 = con.execute(query3).df()
print(result3.to_string(index=False))

print("""
💡 Применение:
- daily_revenue: Агрегация по дням
- with_moving_avg: Добавили скользящее среднее
- Финальный SELECT: Сравниваем с трендом

В бизнесе: Детекция аномалий.
Если выручка внезапно упала ниже тренда → алерт!
""")


# ========================================
# ПРИМЕР 4: ПОДЗАПРОСЫ В WHERE
# ========================================

print("\n" + "=" * 70)
print("📌 ПРИМЕР 4: Подзапросы (Subqueries)")
print("=" * 70)

query4 = """
-- Найти заказы пользователей из Москвы с заказами > средней
SELECT 
    o.order_id,
    u.name,
    o.amount
FROM orders o
JOIN users u ON o.user_id = u.user_id
WHERE u.city = 'Москва'
  AND o.amount > (SELECT AVG(amount) FROM orders)
ORDER BY o.amount DESC
"""

result4 = con.execute(query4).df()
print(result4.to_string(index=False))

print("""
💡 Подзапрос:
(SELECT AVG(amount) FROM orders) 
↑ Вычисляется 1 раз, используется как константа

Альтернатива: CTE для читаемости
""")


# ========================================
# ПРИМЕР 5: РЕКУРСИВНЫЙ CTE
# ========================================

print("\n" + "=" * 70)
print("📌 ПРИМЕР 5: Рекурсивный CTE (Иерархия)")
print("=" * 70)

# Данные: структура компании
hierarchy_df = pd.DataFrame({
    'employee_id': [1, 2, 3, 4, 5, 6],
    'name': ['CEO', 'VP Sales', 'VP Tech', 'Manager A', 'Manager B', 'Engineer'],
    'manager_id': [None, 1, 1, 2, 2, 3]
})

con.register('employees', hierarchy_df)

query5 = """
WITH RECURSIVE org_tree AS (
    -- Базовый случай: CEO (нет менеджера)
    SELECT 
        employee_id,
        name,
        manager_id,
        0 AS level,
        name AS path
    FROM employees
    WHERE manager_id IS NULL
    
    UNION ALL
    
    -- Рекурсивный шаг: подчиненные
    SELECT 
        e.employee_id,
        e.name,
        e.manager_id,
        o.level + 1,
        o.path || ' → ' || e.name AS path
    FROM employees e
    JOIN org_tree o ON e.manager_id = o.employee_id
)
SELECT 
    name,
    level,
    path
FROM org_tree
ORDER BY level, name
"""

result5 = con.execute(query5).df()
print(result5.to_string(index=False))

print("""
💡 Как работает:
1. Базовый случай: Начинаем с CEO (level 0)
2. Рекурсивный шаг: Ищем всех, у кого manager_id = CEO
3. Повторяем для каждого уровня

В бизнесе: 
- Организационные структуры
- Категории товаров (родитель → дочерняя)
- Географическая иерархия (страна → регион → город)
""")


# ========================================
# ПРАКТИЧЕСКАЯ ЗАДАЧА: RFM ANALYSIS
# ========================================

print("\n" + "=" * 70)
print("🎯 ПРАКТИЧЕСКАЯ ЗАДАЧА: RFM Analysis с CTE")
print("=" * 70)

query_rfm = """
WITH 
-- Шаг 1: Вычисляем RFM метрики
user_rfm AS (
    SELECT 
        user_id,
        MAX(order_date) AS last_order_date,
        COUNT(*) AS frequency,
        SUM(amount) AS monetary
    FROM orders
    GROUP BY user_id
),
-- Шаг 2: Добавляем Recency (дней с последнего заказа)
with_recency AS (
    SELECT 
        *,
        DATE_DIFF('day', last_order_date, CURRENT_DATE) AS recency_days
    FROM user_rfm
),
-- Шаг 3: Присваиваем баллы (1-5)
with_scores AS (
    SELECT 
        *,
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency ASC) AS f_score,
        NTILE(5) OVER (ORDER BY monetary ASC) AS m_score
    FROM with_recency
),
-- Шаг 4: Классифицируем
final AS (
    SELECT 
        u.name,
        s.*,
        CASE 
            WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Champions'
            WHEN r_score >= 3 AND f_score >= 3 THEN 'Loyal Customers'
            WHEN r_score >= 3 AND f_score <= 2 THEN 'Potential Loyalists'
            WHEN r_score <= 2 THEN 'At Risk'
            ELSE 'Others'
        END AS segment
    FROM with_scores s
    JOIN users u ON s.user_id = u.user_id
)
SELECT 
    name,
    recency_days,
    frequency,
    monetary,
    r_score,
    f_score,
    m_score,
    segment
FROM final
ORDER BY monetary DESC
"""

result_rfm = con.execute(query_rfm).df()
print(result_rfm.to_string(index=False))

print("""
💡 RFM Analysis:
- Recency: Как давно последний заказ (меньше = лучше)
- Frequency: Как часто покупает (больше = лучше)
- Monetary: Сколько тратит (больше = лучше)

Сегменты:
- Champions: R=5, F=5, M=5 → Лучшие клиенты!
- At Risk: R=1-2 → Давно не покупали, нужна реактивация
- Loyal: Высокая частота, но не супер-выручка

В маркетинге: Основа для персонализации кампаний
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 9 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил:
1. ✅ CTE (WITH) - читаемые запросы
2. ✅ Множественные CTE - пошаговые трансформации
3. ✅ CTE + Window Functions - продвинутая аналитика
4. ✅ Подзапросы в WHERE
5. ✅ Рекурсивный CTE - иерархии и графы
6. ✅ RFM Analysis - реальная бизнес-задача

Это уровень Middle Analytics Engineer!
Следующий шаг: День 10 - Оптимизация SQL
""")

con.close()