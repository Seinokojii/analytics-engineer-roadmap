"""
День 14: Checkpoint Недели 2
Комплексный проект: API → ETL → RFM Analysis → Метрики
"""

import pandas as pd
import numpy as np
import requests
import duckdb
from datetime import datetime, timedelta
import json

print("=" * 80)
print(" " * 20 + "🎯 CHECKPOINT НЕДЕЛИ 2")
print(" " * 15 + "RFM ANALYSIS & ETL PIPELINE PROJECT")
print("=" * 80)

# ========================================
# ЭТАП 1: EXTRACT - ПОЛУЧЕНИЕ ДАННЫХ
# ========================================

print("\n" + "=" * 80)
print("1️⃣ EXTRACT: Получение данных из API")
print("=" * 80)

def extract_from_api():
    """Получает данные из публичного API"""
    # Используем JSONPlaceholder для имитации реальных данных
    users_url = "https://jsonplaceholder.typicode.com/users"
    posts_url = "https://jsonplaceholder.typicode.com/posts"
    
    print("📡 Загрузка пользователей...")
    users_response = requests.get(users_url, timeout=10)
    users = users_response.json()
    
    print("📡 Загрузка активности (posts)...")
    posts_response = requests.get(posts_url, timeout=10)
    posts = posts_response.json()
    
    print(f"✅ Получено: {len(users)} пользователей, {len(posts)} постов")
    
    return users, posts

users_raw, posts_raw = extract_from_api()

# ========================================
# ЭТАП 2: TRANSFORM - ОЧИСТКА И ТРАНСФОРМАЦИЯ
# ========================================

print("\n" + "=" * 80)
print("2️⃣ TRANSFORM: Очистка и подготовка данных")
print("=" * 80)

# Создаем синтетические данные о заказах на основе posts
# (имитируем реальную ситуацию)
np.random.seed(42)

orders_data = []
order_id = 1

for post in posts_raw:
    user_id = post['userId']
    
    # Генерируем 1-3 заказа на пост
    num_orders = np.random.randint(1, 4)
    
    for _ in range(num_orders):
        order = {
            'order_id': order_id,
            'user_id': user_id,
            'amount': np.random.randint(50, 5000),
            'order_date': datetime(2024, 1, 1) + timedelta(
                days=np.random.randint(0, 365)
            ),
            'product_category': np.random.choice(['Tech', 'Office', 'Home']),
            'status': np.random.choice(['completed', 'completed', 'completed', 'cancelled'])
        }
        orders_data.append(order)
        order_id += 1

# Конвертируем в DataFrame
df_orders = pd.DataFrame(orders_data)
df_users = pd.DataFrame(users_raw)

print(f"✅ Создано заказов: {len(df_orders)}")
print(f"📊 Период: {df_orders['order_date'].min().date()} - {df_orders['order_date'].max().date()}")

# Очистка: только завершенные заказы
df_orders_clean = df_orders[df_orders['status'] == 'completed'].copy()
print(f"✅ После фильтрации (только completed): {len(df_orders_clean)} заказов")

# ========================================
# ЭТАП 3: RFM АНАЛИЗ
# ========================================

print("\n" + "=" * 80)
print("3️⃣ RFM ANALYSIS: Сегментация клиентов")
print("=" * 80)

# Текущая дата для расчета Recency
analysis_date = datetime(2025, 1, 1)

# Вычисляем RFM метрики
rfm_df = df_orders_clean.groupby('user_id').agg({
    'order_date': lambda x: (analysis_date - x.max()).days,  # Recency
    'order_id': 'count',  # Frequency
    'amount': 'sum'  # Monetary
}).reset_index()

rfm_df.columns = ['user_id', 'recency_days', 'frequency', 'monetary']

print("📊 RFM метрики (пример):")
print(rfm_df.head(10).to_string(index=False))

# Присваиваем RFM scores (1-5)
# Recency: меньше = лучше → инвертируем
rfm_df['r_score'] = pd.qcut(rfm_df['recency_days'], q=5, labels=[5,4,3,2,1], duplicates='drop')
rfm_df['f_score'] = pd.qcut(rfm_df['frequency'].rank(method='first'), q=5, labels=[1,2,3,4,5], duplicates='drop')
rfm_df['m_score'] = pd.qcut(rfm_df['monetary'].rank(method='first'), q=5, labels=[1,2,3,4,5], duplicates='drop')

# Конвертируем в int
rfm_df['r_score'] = rfm_df['r_score'].astype(int)
rfm_df['f_score'] = rfm_df['f_score'].astype(int)
rfm_df['m_score'] = rfm_df['m_score'].astype(int)

# RFM Score (комбинированный)
rfm_df['rfm_score'] = (rfm_df['r_score'] + rfm_df['f_score'] + rfm_df['m_score']) / 3

print("\n📊 RFM Scores:")
print(rfm_df.head(10).to_string(index=False))

# Сегментация
def rfm_segment(row):
    """Определяет сегмент клиента на основе RFM scores"""
    r, f, m = row['r_score'], row['f_score'], row['m_score']
    
    # Champions: высокие R, F, M
    if r >= 4 and f >= 4 and m >= 4:
        return 'Champions'
    
    # Loyal Customers: высокие F и M
    elif f >= 4 and m >= 4:
        return 'Loyal Customers'
    
    # Potential Loyalists: высокий R, средние F и M
    elif r >= 4 and f >= 3 and m >= 3:
        return 'Potential Loyalists'
    
    # New Customers: высокий R, низкие F и M
    elif r >= 4 and f <= 2:
        return 'New Customers'
    
    # At Risk: низкий R, высокие F и M (были активными)
    elif r <= 2 and f >= 3 and m >= 3:
        return 'At Risk'
    
    # Hibernating: низкие R, F, M
    elif r <= 2 and f <= 2 and m <= 2:
        return 'Hibernating'
    
    # Lost Customers: самый низкий R
    elif r == 1:
        return 'Lost Customers'
    
    else:
        return 'Others'

rfm_df['segment'] = rfm_df.apply(rfm_segment, axis=1)

print("\n🏷️ Распределение по сегментам:")
segment_counts = rfm_df['segment'].value_counts()
print(segment_counts)

# ========================================
# ЭТАП 4: SQL АНАЛИЗ
# ========================================

print("\n" + "=" * 80)
print("4️⃣ SQL ANALYSIS: Углубленная аналитика")
print("=" * 80)

con = duckdb.connect()
con.register('orders', df_orders_clean)
con.register('rfm', rfm_df)
con.register('users', df_users)

# Запрос 1: Топ-10 клиентов по выручке
query1 = """
WITH user_revenue AS (
    SELECT 
        user_id,
        SUM(amount) as total_revenue,
        COUNT(*) as order_count,
        AVG(amount) as avg_order_value
    FROM orders
    GROUP BY user_id
)
SELECT 
    u.name,
    ur.total_revenue,
    ur.order_count,
    ROUND(ur.avg_order_value, 2) as avg_order_value,
    r.segment
FROM user_revenue ur
JOIN users u ON ur.user_id = u.id
JOIN rfm r ON ur.user_id = r.user_id
ORDER BY ur.total_revenue DESC
LIMIT 10
"""

top_customers = con.execute(query1).df()
print("💰 ТОП-10 клиентов по выручке:")
print(top_customers.to_string(index=False))

# Запрос 2: Метрики по сегментам
query2 = """
SELECT 
    r.segment,
    COUNT(DISTINCT r.user_id) as customer_count,
    ROUND(AVG(r.monetary), 2) as avg_ltv,
    ROUND(AVG(r.frequency), 1) as avg_frequency,
    ROUND(AVG(r.recency_days), 1) as avg_recency_days
FROM rfm r
GROUP BY r.segment
ORDER BY avg_ltv DESC
"""

segment_metrics = con.execute(query2).df()
print("\n📊 Метрики по сегментам:")
print(segment_metrics.to_string(index=False))

# Запрос 3: Тренд по месяцам
query3 = """
SELECT 
    DATE_TRUNC('month', order_date) as month,
    COUNT(*) as orders_count,
    SUM(amount) as revenue,
    ROUND(AVG(amount), 2) as avg_order_value
FROM orders
GROUP BY month
ORDER BY month
"""

monthly_trend = con.execute(query3).df()
print("\n📈 Тренд по месяцам:")
print(monthly_trend.to_string(index=False))

# ========================================
# ЭТАП 5: СОХРАНЕНИЕ РЕЗУЛЬТАТОВ
# ========================================

print("\n" + "=" * 80)
print("5️⃣ LOAD: Сохранение результатов")
print("=" * 80)

# Добавляем метаданные
rfm_df['analysis_date'] = analysis_date.strftime('%Y-%m-%d')
rfm_df['created_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Сохраняем в разных форматах
rfm_df.to_parquet('rfm_analysis.parquet', index=False)
rfm_df.to_csv('rfm_analysis.csv', index=False)
segment_metrics.to_csv('segment_metrics.csv', index=False)
monthly_trend.to_csv('monthly_trend.csv', index=False)

print("💾 Сохранено:")
print("  ✅ rfm_analysis.parquet (основные данные)")
print("  ✅ rfm_analysis.csv (для Excel)")
print("  ✅ segment_metrics.csv (метрики по сегментам)")
print("  ✅ monthly_trend.csv (тренд)")

# ========================================
# ЭТАП 6: ВИЗУАЛИЗАЦИЯ МЕТРИК
# ========================================

print("\n" + "=" * 80)
print("6️⃣ METRICS: Ключевые показатели")
print("=" * 80)

# Общие метрики
total_customers = len(rfm_df)
total_revenue = rfm_df['monetary'].sum()
avg_ltv = rfm_df['monetary'].mean()
avg_frequency = rfm_df['frequency'].mean()

champions_count = len(rfm_df[rfm_df['segment'] == 'Champions'])
at_risk_count = len(rfm_df[rfm_df['segment'] == 'At Risk'])
lost_count = len(rfm_df[rfm_df['segment'] == 'Lost Customers'])

print(f"""
📊 ОБЩИЕ МЕТРИКИ:
─────────────────────────────────────────
Всего клиентов:           {total_customers}
Общая выручка:            {total_revenue:,.0f}₽
Средний LTV:              {avg_ltv:,.0f}₽
Средняя частота покупок:  {avg_frequency:.1f}

🏆 СЕГМЕНТАЦИЯ:
─────────────────────────────────────────
Champions:                {champions_count} ({champions_count/total_customers*100:.1f}%)
At Risk:                  {at_risk_count} ({at_risk_count/total_customers*100:.1f}%)
Lost Customers:           {lost_count} ({lost_count/total_customers*100:.1f}%)

💡 РЕКОМЕНДАЦИИ:
─────────────────────────────────────────
1. Champions ({champions_count}) → VIP программа, реферальная программа
2. At Risk ({at_risk_count}) → Персонализированные предложения, скидки
3. Lost ({lost_count}) → Win-back кампания с агрессивными акциями
""")

# ========================================
# ЭТАП 7: ГЕНЕРАЦИЯ ОТЧЕТА
# ========================================

print("\n" + "=" * 80)
print("7️⃣ REPORT: Бизнес-отчет")
print("=" * 80)

report = f"""
╔══════════════════════════════════════════════════════════════════════╗
║                    RFM ANALYSIS REPORT                               ║
║                    Дата анализа: {analysis_date.date()}                           ║
╚══════════════════════════════════════════════════════════════════════╝

EXECUTIVE SUMMARY
─────────────────────────────────────────────────────────────────────
Проведен RFM анализ {total_customers} клиентов за период с {df_orders_clean['order_date'].min().date()} 
по {df_orders_clean['order_date'].max().date()}.

KEY FINDINGS
─────────────────────────────────────────────────────────────────────
1. Champions составляют {champions_count/total_customers*100:.1f}% клиентской базы, но генерируют
   {rfm_df[rfm_df['segment']=='Champions']['monetary'].sum()/total_revenue*100:.1f}% выручки.

2. {at_risk_count} клиентов ({at_risk_count/total_customers*100:.1f}%) находятся в зоне риска ухода.
   Необходима срочная реактивация.

3. Средний LTV клиента: {avg_ltv:,.0f}₽
   Средняя частота покупок: {avg_frequency:.1f} заказов

RECOMMENDED ACTIONS
─────────────────────────────────────────────────────────────────────
HIGH PRIORITY:
- Запустить win-back кампанию для {lost_count} потерянных клиентов
- Предложить персонализированные скидки {at_risk_count} клиентам "At Risk"

MEDIUM PRIORITY:
- Развивать VIP-программу для {champions_count} Champions
- Конвертировать Potential Loyalists в Loyal (up-sell)

LOW PRIORITY:
- Отслеживать New Customers на предмет быстрого роста

NEXT STEPS
─────────────────────────────────────────────────────────────────────
1. Передать сегменты в CRM для персонализации
2. Настроить автоматические триггеры для At Risk
3. Повторить анализ через 30 дней

──────────────────────────────────────────────────────────────────────
Файлы: rfm_analysis.parquet, segment_metrics.csv
Analyst: Analytics Engineer Roadmap Project
"""

print(report)

# Сохраняем отчет
with open('rfm_report.txt', 'w', encoding='utf-8') as f:
    f.write(report)

print("✅ Отчет сохранен: rfm_report.txt")

# ========================================
# ИТОГИ CHECKPOINT
# ========================================

print("\n" + "=" * 80)
print("✅ CHECKPOINT НЕДЕЛИ 2 ЗАВЕРШЕН!")
print("=" * 80)

print("""
🎉 ПОЗДРАВЛЯЮ! Ты создал полноценный проект для портфолио!

ЧТО ТЫ СДЕЛАЛ:
1. ✅ Extract: Получил данные из API
2. ✅ Transform: Очистил и трансформировал данные
3. ✅ RFM Analysis: Провел сегментацию клиентов
4. ✅ SQL Analytics: Написал сложные аналитические запросы
5. ✅ Load: Сохранил результаты в Parquet/CSV
6. ✅ Metrics: Вычислил ключевые бизнес-метрики
7. ✅ Report: Создал бизнес-отчет с рекомендациями

НАВЫКИ ПРОДЕМОНСТРИРОВАНЫ:
- ETL Pipeline (Extract-Transform-Load)
- RFM Analysis для сегментации
- SQL (CTE, JOIN, GROUP BY, Window Functions)
- Python (pandas, numpy, requests)
- Работа с API
- Бизнес-аналитика
- Генерация отчетов

ФАЙЛЫ ДЛЯ ПОРТФОЛИО:
- lesson14_checkpoint_week2.py (исходный код)
- rfm_analysis.parquet (результаты анализа)
- rfm_report.txt (бизнес-отчет)
- segment_metrics.csv (метрики)

ЭТО МОЖНО ПОКАЗЫВАТЬ РАБОТОДАТЕЛЮ! 💼

НЕДЕЛЯ 2 ЗАВЕРШЕНА НА 100%! 🚀
Готов к Неделе 3?
""")

# Закрываем соединение
con.close()

# Очистка (опционально)
import os
print("\nℹ️  Файлы сохранены. Для просмотра:")
print("  - rfm_analysis.csv (открой в Excel)")
print("  - rfm_report.txt (открой в Блокноте)")