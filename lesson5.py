import duckdb
import pandas as pd

# Подключаемся к DuckDB
con = duckdb.connect()

print("🚀 День 5: Даты и оконные функции!")
print("=" * 60)

# ========================================
# СОЗДАЕМ ТЕСТОВЫЕ ДАННЫЕ
# ========================================
sales_data = pd.DataFrame({
    'sale_id': [1, 2, 3, 4, 5, 6, 7, 8],
    'product': ['Ноутбук', 'Мышь', 'Клавиатура', 'Монитор', 
                'Ноутбук', 'Принтер', 'Мышь', 'Монитор'],
    'category': ['Tech', 'Tech', 'Tech', 'Tech', 
                 'Tech', 'Office', 'Tech', 'Tech'],
    'sale_date': ['2024-01-15', '2024-01-20', '2024-02-05', 
                  '2024-02-10', '2024-01-25', '2024-02-15',
                  '2024-01-30', '2024-02-20'],
    'amount': [1200, 25, 80, 350, 1200, 500, 30, 400]
})

# Преобразуем даты в правильный формат
sales_data['sale_date'] = pd.to_datetime(sales_data['sale_date'])

# Регистрируем как SQL таблицу
con.register('sales', sales_data)

print("\n✅ Таблица создана:")
print(sales_data.to_string(index=False))

# ========================================
# ЗАДАЧА 1: РАБОТА С ДАТАМИ
# ========================================
print("\n" + "=" * 60)
print("📅 ЗАДАЧА 1: Сколько дней прошло с продажи?")
print("=" * 60)

query1 = """
SELECT 
    product,
    sale_date,
    current_date AS сегодня,
    current_date - sale_date AS дней_прошло
FROM sales
ORDER BY sale_date
"""

result1 = con.execute(query1).df()
print(result1.to_string(index=False))

# ========================================
# ЗАДАЧА 2: ФИЛЬТРАЦИЯ ПО МЕСЯЦУ
# ========================================
print("\n" + "=" * 60)
print("📅 ЗАДАЧА 2: Продажи за январь 2024")
print("=" * 60)

query2 = """
SELECT 
    product,
    sale_date,
    amount
FROM sales
WHERE EXTRACT(MONTH FROM sale_date) = 1
  AND EXTRACT(YEAR FROM sale_date) = 2024
ORDER BY sale_date
"""

result2 = con.execute(query2).df()
print(result2.to_string(index=False))

# ========================================
# ЗАДАЧА 3: ROW_NUMBER - ПРОСТАЯ НУМЕРАЦИЯ
# ========================================
print("\n" + "=" * 60)
print("🪟 ОКНО 1: Нумерация всех продаж по дате")
print("=" * 60)

query3 = """
SELECT 
    product,
    sale_date,
    amount,
    ROW_NUMBER() OVER (ORDER BY sale_date) AS номер_продажи
FROM sales
"""

result3 = con.execute(query3).df()
print(result3.to_string(index=False))

# ========================================
# ЗАДАЧА 4: PARTITION BY - НУМЕРАЦИЯ ПО ГРУППАМ
# ========================================
print("\n" + "=" * 60)
print("🪟 ОКНО 2: Рейтинг внутри каждого месяца")
print("=" * 60)

query4 = """
SELECT 
    product,
    sale_date,
    EXTRACT(MONTH FROM sale_date) AS месяц,
    amount,
    ROW_NUMBER() OVER (
        PARTITION BY EXTRACT(MONTH FROM sale_date)
        ORDER BY amount DESC
    ) AS место_в_месяце
FROM sales
ORDER BY месяц, место_в_месяце
"""

result4 = con.execute(query4).df()
print(result4.to_string(index=False))

# ========================================
# ЗАДАЧА 5: RANK vs ROW_NUMBER vs DENSE_RANK
# ========================================
print("\n" + "=" * 60)
print("🪟 ОКНО 3: Три вида ранжирования")
print("=" * 60)

query5 = """
SELECT 
    product,
    amount,
    ROW_NUMBER() OVER (ORDER BY amount DESC) AS row_num,
    RANK() OVER (ORDER BY amount DESC) AS rank,
    DENSE_RANK() OVER (ORDER BY amount DESC) AS dense_rank
FROM sales
ORDER BY amount DESC
"""

result5 = con.execute(query5).df()
print(result5.to_string(index=False))

# ========================================
# ЗАДАНИЕ СО ЗВЕЗДОЧКОЙ ⭐
# ========================================
print("\n" + "=" * 60)
print("⭐ ЗАДАНИЕ: ТОП-3 самых дорогих товара")
print("=" * 60)

query_top3 = """
SELECT * FROM (
    SELECT 
        product,
        amount,
        sale_date,
        RANK() OVER (ORDER BY amount DESC) AS ранг
    FROM sales
) ranked
WHERE ранг <= 3
ORDER BY ранг
"""

result_top3 = con.execute(query_top3).df()
print(result_top3.to_string(index=False))

# ========================================
# ДОПОЛНИТЕЛЬНО: LAG и LEAD (Бонус для продвинутых)
# ========================================
print("\n" + "=" * 60)
print("🎁 БОНУС: Разница с предыдущей продажей")
print("=" * 60)

query_bonus = """
SELECT 
    product,
    sale_date,
    amount,
    LAG(amount) OVER (ORDER BY sale_date) AS предыдущая_цена,
    amount - LAG(amount) OVER (ORDER BY sale_date) AS разница
FROM sales
ORDER BY sale_date
"""

result_bonus = con.execute(query_bonus).df()
print(result_bonus.to_string(index=False))

# ========================================
# ИТОГИ
# ========================================
print("\n" + "=" * 60)
print("✅ ДЕНЬ 5 ЗАВЕРШЕН!")
print("=" * 60)
print("""
Ты освоил:
1. ✅ Работу с датами (EXTRACT, разница дат)
2. ✅ ROW_NUMBER() - простую нумерацию
3. ✅ PARTITION BY - деление на группы
4. ✅ RANK() и DENSE_RANK() - умное ранжирование
5. ✅ Подзапросы с оконными функциями

Следующий шаг: git add, commit, push!
""")

# Закрываем соединение
con.close()