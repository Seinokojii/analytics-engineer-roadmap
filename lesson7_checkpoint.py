"""
День 7: Checkpoint Недели 1
Проверка всех навыков: SQL, Pandas, Python
"""

import pandas as pd
import duckdb

print("=" * 70)
print(" " * 15 + "🎯 CHECKPOINT НЕДЕЛИ 1 🎯")
print("=" * 70)

# ========================================
# ПОДГОТОВКА ДАННЫХ
# ========================================

# Создаем тестовые данные (имитация реальной БД)
users_df = pd.DataFrame({
    'user_id': [1, 2, 3, 4, 5],
    'name': ['Алексей', 'Мария', 'Иван', 'Анна', 'Дмитрий'],
    'city': ['Москва', 'Казань', 'Омск', 'Москва', 'Казань'],
    'registration_date': ['2024-01-10', '2024-01-15', '2024-02-01', 
                          '2024-02-05', '2024-01-20']
})

orders_df = pd.DataFrame({
    'order_id': [101, 102, 103, 104, 105, 106, 107],
    'user_id': [1, 2, 1, 3, 2, 1, 5],
    'product': ['Ноутбук', 'Мышь', 'Клавиатура', 'Монитор', 
                'Принтер', 'Монитор', 'Клавиатура'],
    'category': ['Tech', 'Tech', 'Tech', 'Tech', 'Office', 'Tech', 'Tech'],
    'amount': [1200, 25, 80, 350, 500, 400, 80],
    'order_date': ['2024-01-20', '2024-01-22', '2024-02-05', 
                   '2024-02-10', '2024-02-12', '2024-02-15', '2024-02-18']
})

# Сохраняем в CSV (для SQL)
users_df.to_csv('users_checkpoint.csv', index=False)
orders_df.to_csv('orders_checkpoint.csv', index=False)

con = duckdb.connect()

print("\n✅ Данные подготовлены:")
print(f"  Пользователей: {len(users_df)}")
print(f"  Заказов: {len(orders_df)}")


# ========================================
# БЛОК 1: SQL-ЗАПРОСЫ (5 штук)
# ========================================

print("\n" + "=" * 70)
print(" " * 20 + "📊 БЛОК 1: SQL")
print("=" * 70)

print("\n--- SQL Запрос 1: Базовая выборка с фильтром ---")
query1 = """
SELECT product, amount 
FROM 'orders_checkpoint.csv'
WHERE amount > 100
ORDER BY amount DESC
"""
result1 = con.execute(query1).df()
print(result1.to_string(index=False))

print("\n--- SQL Запрос 2: Группировка и агрегация ---")
query2 = """
SELECT 
    category,
    COUNT(*) as orders_count,
    SUM(amount) as total_revenue,
    AVG(amount) as avg_order
FROM 'orders_checkpoint.csv'
GROUP BY category
ORDER BY total_revenue DESC
"""
result2 = con.execute(query2).df()
print(result2.to_string(index=False))

print("\n--- SQL Запрос 3: JOIN пользователей и заказов ---")
query3 = """
SELECT 
    u.name,
    u.city,
    o.product,
    o.amount
FROM 'users_checkpoint.csv' u
LEFT JOIN 'orders_checkpoint.csv' o ON u.user_id = o.user_id
ORDER BY u.name, o.order_date
"""
result3 = con.execute(query3).df()
print(result3.to_string(index=False))

print("\n--- SQL Запрос 4: Оконные функции (ранжирование) ---")
query4 = """
SELECT 
    product,
    amount,
    category,
    RANK() OVER (PARTITION BY category ORDER BY amount DESC) as rank_in_category
FROM 'orders_checkpoint.csv'
ORDER BY category, rank_in_category
"""
result4 = con.execute(query4).df()
print(result4.to_string(index=False))

print("\n--- SQL Запрос 5: Комплексный (JOIN + GROUP BY + HAVING) ---")
query5 = """
SELECT 
    u.city,
    COUNT(o.order_id) as orders_count,
    SUM(o.amount) as total_spent
FROM 'users_checkpoint.csv' u
LEFT JOIN 'orders_checkpoint.csv' o ON u.user_id = o.user_id
GROUP BY u.city
HAVING total_spent > 500
ORDER BY total_spent DESC
"""
result5 = con.execute(query5).df()
print(result5.to_string(index=False))


# ========================================
# БЛОК 2: PANDAS-СКРИПТЫ (3 штуки)
# ========================================

print("\n" + "=" * 70)
print(" " * 18 + "🐼 БЛОК 2: PANDAS")
print("=" * 70)

print("\n--- Pandas Скрипт 1: Фильтрация и группировка ---")
# Задача: Найти пользователей из Москвы с заказами > 100₽
moscow_users = users_df[users_df['city'] == 'Москва']['user_id']
expensive_orders = orders_df[
    (orders_df['user_id'].isin(moscow_users)) & 
    (orders_df['amount'] > 100)
]
print(expensive_orders[['user_id', 'product', 'amount']].to_string(index=False))

print("\n--- Pandas Скрипт 2: Merge (аналог SQL JOIN) ---")
# Задача: Объединить пользователей и заказы, добавить имя и город
merged_data = pd.merge(
    orders_df,
    users_df[['user_id', 'name', 'city']],
    on='user_id',
    how='left'
)
print(merged_data[['name', 'city', 'product', 'amount']].head().to_string(index=False))

print("\n--- Pandas Скрипт 3: Агрегация с группировкой ---")
# Задача: Топ-3 пользователя по сумме покупок
user_totals = orders_df.groupby('user_id').agg({
    'amount': ['sum', 'count', 'mean']
}).round(2)
user_totals.columns = ['total_spent', 'orders_count', 'avg_order']
user_totals = user_totals.sort_values('total_spent', ascending=False).head(3)
print(user_totals)


# ========================================
# БЛОК 3: PYTHON (Бонус)
# ========================================

print("\n" + "=" * 70)
print(" " * 18 + "🐍 БЛОК 3: PYTHON")
print("=" * 70)

def calculate_user_stats(orders: pd.DataFrame) -> dict[int, dict[str, float]]:
    """
    Вычисляет статистику по каждому пользователю
    
    Returns:
        Словарь {user_id: {total, count, avg}}
    """
    stats: dict[int, dict[str, float]] = {}
    
    for user_id in orders['user_id'].unique():
        user_orders = orders[orders['user_id'] == user_id]
        
        stats[user_id] = {
            'total': float(user_orders['amount'].sum()),
            'count': len(user_orders),
            'avg': float(user_orders['amount'].mean())
        }
    
    return stats

print("\n--- Статистика по пользователям (через Python) ---")
user_stats = calculate_user_stats(orders_df)
for user_id, stat in user_stats.items():
    print(f"Пользователь {user_id}: {stat['count']} заказов, "
          f"сумма {stat['total']:.0f}₽, средний чек {stat['avg']:.0f}₽")


# ========================================
# ИТОГОВАЯ СТАТИСТИКА
# ========================================

print("\n" + "=" * 70)
print(" " * 15 + "📈 ИТОГОВАЯ СТАТИСТИКА")
print("=" * 70)

total_revenue = orders_df['amount'].sum()
total_orders = len(orders_df)
avg_order_value = orders_df['amount'].mean()
unique_users = orders_df['user_id'].nunique()

print(f"""
✅ Общая выручка: {total_revenue}₽
✅ Всего заказов: {total_orders}
✅ Средний чек: {avg_order_value:.2f}₽
✅ Активных пользователей: {unique_users} из {len(users_df)}
✅ Конверсия: {unique_users/len(users_df)*100:.1f}%
""")


# ========================================
# CHECKPOINT ПРОЙДЕН!
# ========================================

print("=" * 70)
print(" " * 15 + "🎉 CHECKPOINT ПРОЙДЕН!")
print("=" * 70)
print("""
Ты продемонстрировал знание:
1. ✅ SQL: SELECT, WHERE, JOIN, GROUP BY, HAVING, оконные функции
2. ✅ Pandas: фильтрация, merge, groupby, агрегации
3. ✅ Python: функции, type hints, словари, обработка данных

НЕДЕЛЯ 1 ЗАВЕРШЕНА! 🚀
Готов к Неделе 2: Advanced SQL и Data Quality!
""")

# Закрываем соединение
con.close()