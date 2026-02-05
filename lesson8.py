"""
День 8: Продвинутые оконные функции
Running totals, moving averages, percentiles
"""

import duckdb
import pandas as pd

print("=" * 70)
print(" " * 15 + "📊 ДЕНЬ 8: ADVANCED WINDOWS")
print("=" * 70)

# ========================================
# ПОДГОТОВКА ДАННЫХ
# ========================================

# Продажи по дням (имитация реальных данных)
sales_df = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=20, freq='D'),
    'product': ['Ноутбук', 'Мышь', 'Клавиатура', 'Монитор'] * 5,
    'daily_revenue': [1200, 25, 80, 350, 1100, 30, 75, 400,
                      1300, 20, 85, 380, 1250, 35, 70, 420,
                      1150, 40, 90, 360]
})

con = duckdb.connect()
con.register('sales', sales_df)

print("\n✅ Данные: 20 дней продаж")
print(sales_df.head(10).to_string(index=False))


# ========================================
# ПАТТЕРН 1: RUNNING TOTAL (Нарастающий итог)
# ========================================

print("\n" + "=" * 70)
print("📈 ПАТТЕРН 1: Running Total (Накопительный итог)")
print("=" * 70)

query1 = """
SELECT 
    date,
    product,
    daily_revenue,
    SUM(daily_revenue) OVER (
        ORDER BY date 
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_revenue
FROM sales
ORDER BY date
LIMIT 10
"""

result1 = con.execute(query1).df()
print(result1.to_string(index=False))

print("""
💡 Интерпретация:
- День 1: дневная выручка = 1200, накопительная = 1200
- День 2: дневная выручка = 25, накопительная = 1200 + 25 = 1225
- И так далее...

В бизнесе: Отслеживание выполнения месячного плана.
Пример: План 20,000₽/месяц, на 10-й день накопили 3,755₽ → 18.8% выполнено
""")


# ========================================
# ПАТТЕРН 2: MOVING AVERAGE (Скользящее среднее)
# ========================================

print("\n" + "=" * 70)
print("📉 ПАТТЕРН 2: Moving Average (Скользящее среднее за 3 дня)")
print("=" * 70)

query2 = """
SELECT 
    date,
    daily_revenue,
    AVG(daily_revenue) OVER (
        ORDER BY date 
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ) AS moving_avg_3days
FROM sales
ORDER BY date
LIMIT 10
"""

result2 = con.execute(query2).df()
print(result2.to_string(index=False))

print("""
💡 Интерпретация:
- День 1-2: Недостаточно данных для 3-дневного среднего → берется что есть
- День 3: (1200 + 25 + 80) / 3 = 435
- День 4: (25 + 80 + 350) / 3 = 151.67
- И так далее...

В бизнесе: Сглаживание колебаний для прогнозирования.
Если moving_avg растет → тренд вверх, падает → тренд вниз
""")


# ========================================
# ПАТТЕРН 3: LAG/LEAD (Сравнение с предыдущими/следующими)
# ========================================

print("\n" + "=" * 70)
print("⏮️⏭️ ПАТТЕРН 3: LAG/LEAD (Сравнение периодов)")
print("=" * 70)

query3 = """
SELECT 
    date,
    daily_revenue,
    LAG(daily_revenue, 1) OVER (ORDER BY date) AS prev_day_revenue,
    daily_revenue - LAG(daily_revenue, 1) OVER (ORDER BY date) AS day_over_day_change,
    LEAD(daily_revenue, 1) OVER (ORDER BY date) AS next_day_revenue
FROM sales
ORDER BY date
LIMIT 10
"""

result3 = con.execute(query3).df()
print(result3.to_string(index=False))

print("""
💡 Интерпретация:
- LAG(1) = предыдущий день
- LEAD(1) = следующий день
- Изменение = текущий - предыдущий

В бизнесе: Day-over-Day (DoD) анализ.
Пример: Выручка упала на 1175₽ в День 2 → нужно разобраться почему!
""")


# ========================================
# ПАТТЕРН 4: PERCENTILES (Процентили)
# ========================================

print("\n" + "=" * 70)
print("📊 ПАТТЕРН 4: Percentiles (Распределение)")
print("=" * 70)

query4 = """
SELECT 
    product,
    daily_revenue,
    PERCENT_RANK() OVER (ORDER BY daily_revenue) AS percentile,
    NTILE(4) OVER (ORDER BY daily_revenue) AS quartile
FROM sales
ORDER BY daily_revenue DESC
LIMIT 10
"""

result4 = con.execute(query4).df()
print(result4.to_string(index=False))

print("""
💡 Интерпретация:
- PERCENT_RANK: От 0 (минимум) до 1 (максимум)
  0.95 = топ-5%, 0.50 = медиана
- NTILE(4): Разбивает на 4 квартиля
  4 = топ-25%, 1 = нижние 25%

В бизнесе: Сегментация товаров/клиентов.
Квартиль 4 = премиум-сегмент, квартиль 1 = low-end
""")


# ========================================
# ПАТТЕРН 5: FIRST_VALUE / LAST_VALUE
# ========================================

print("\n" + "=" * 70)
print("🥇🥉 ПАТТЕРН 5: First/Last Value")
print("=" * 70)

query5 = """
SELECT 
    date,
    daily_revenue,
    FIRST_VALUE(daily_revenue) OVER (ORDER BY date) AS first_day_revenue,
    LAST_VALUE(daily_revenue) OVER (
        ORDER BY date 
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    ) AS last_day_revenue,
    daily_revenue - FIRST_VALUE(daily_revenue) OVER (ORDER BY date) AS change_from_start
FROM sales
ORDER BY date
LIMIT 10
"""

result5 = con.execute(query5).df()
print(result5.to_string(index=False))

print("""
💡 Интерпретация:
- FIRST_VALUE: Первое значение в окне (начало периода)
- LAST_VALUE: Последнее значение в окне (конец периода)

В бизнесе: Сравнение с baseline.
Пример: Первый день месяца = 1200₽, сегодня = 350₽ → падение на 850₽
""")


# ========================================
# ПРАКТИЧЕСКАЯ ЗАДАЧА: COHORT ANALYSIS
# ========================================

print("\n" + "=" * 70)
print("🎯 ПРАКТИЧЕСКАЯ ЗАДАЧА: Retention по когортам")
print("=" * 70)

# Данные пользователей по когортам
cohort_df = pd.DataFrame({
    'cohort_month': ['2024-01', '2024-01', '2024-01', '2024-02', '2024-02', '2024-02'],
    'month': ['2024-01', '2024-02', '2024-03', '2024-02', '2024-03', '2024-04'],
    'active_users': [100, 75, 60, 120, 95, 80]
})

con.register('cohorts', cohort_df)

query_cohort = """
SELECT 
    cohort_month,
    month,
    active_users,
    FIRST_VALUE(active_users) OVER (
        PARTITION BY cohort_month 
        ORDER BY month
    ) AS cohort_size,
    ROUND(100.0 * active_users / FIRST_VALUE(active_users) OVER (
        PARTITION BY cohort_month 
        ORDER BY month
    ), 1) AS retention_rate
FROM cohorts
ORDER BY cohort_month, month
"""

result_cohort = con.execute(query_cohort).df()
print(result_cohort.to_string(index=False))

print("""
💡 Интерпретация:
- Когорта 2024-01 (100 пользователей):
  - Месяц 1: 100 активных (100% retention)
  - Месяц 2: 75 активных (75% retention)
  - Месяц 3: 60 активных (60% retention)

В бизнесе: Ключевая метрика для продуктов (SaaS, мобильные приложения).
Retention < 40% через 3 месяца = проблема с продуктом!
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 8 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил продвинутые паттерны:
1. ✅ Running Total - накопительные итоги
2. ✅ Moving Average - скользящие средние для трендов
3. ✅ LAG/LEAD - сравнение периодов (DoD, WoW)
4. ✅ Percentiles - сегментация и распределение
5. ✅ FIRST_VALUE/LAST_VALUE - сравнение с baseline
6. ✅ Cohort Analysis - retention по когортам

Следующий шаг: День 9 - CTE и подзапросы!
""")

con.close()