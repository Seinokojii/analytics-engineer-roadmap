import duckdb
import pandas as pd

# 1. Подключаемся к DuckDB (база данных прямо в оперативной памяти)
con = duckdb.connect()

# 2. Создаем тренировочные данные
users_df = pd.DataFrame({
    'id': [1, 2, 3],
    'name': ['Алексей', 'Мария', 'Иван']
})

orders_df = pd.DataFrame({
    'user_id': [1, 1, 2],
    'amount': [500, 300, 1200]
})

# 3. Регистрируем их как таблицы SQL
con.register('users', users_df)
con.register('orders', orders_df)

# 4. Пишем SQL-запрос (Сердце твоего дня!)
# Мы соединяем таблицы и считаем сумму покупок для каждого
sql_query = """
SELECT 
    u.name, 
    SUM(o.amount) as total_spent,
    COUNT(o.user_id) as order_count
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.name
"""

print("--- Итоговый отчет по клиентам ---")
print(con.execute(sql_query).df())