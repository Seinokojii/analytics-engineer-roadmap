"""
День 11: Pandas Deep Dive
Продвинутые техники работы с данными
"""

import pandas as pd
import numpy as np
import time

print("=" * 70)
print(" " * 18 + "🐼 ДЕНЬ 11: PANDAS PRO")
print("=" * 70)

# ========================================
# ЧАСТЬ 1: VECTORIZATION VS LOOPS
# ========================================

print("\n" + "=" * 70)
print("⚡ ЧАСТЬ 1: Векторизация vs Циклы")
print("=" * 70)

# Создаем тестовый DataFrame
np.random.seed(42)
df_test = pd.DataFrame({
    'price': np.random.randint(10, 1000, size=50000),
    'quantity': np.random.randint(1, 10, size=50000)
})

print(f"📊 Данных: {len(df_test):,} строк\n")

# ❌ Метод 1: Цикл с iterrows (ОЧЕНЬ МЕДЛЕННО)
start = time.time()
totals_loop = []
for index, row in df_test.iterrows():
    totals_loop.append(row['price'] * row['quantity'])
df_test['total_loop'] = totals_loop
t_loop = time.time() - start
print(f"❌ Цикл (iterrows): {t_loop:.4f} сек")

# ❌ Метод 2: Apply (МЕДЛЕННО)
start = time.time()
df_test['total_apply'] = df_test.apply(
    lambda row: row['price'] * row['quantity'], axis=1
)
t_apply = time.time() - start
print(f"⚠️  Apply: {t_apply:.4f} сек")

# ✅ Метод 3: Векторизация (БЫСТРО!)
start = time.time()
df_test['total_vectorized'] = df_test['price'] * df_test['quantity']
t_vectorized = time.time() - start
print(f"✅ Векторизация: {t_vectorized:.4f} сек")

print(f"\n🚀 Ускорение:")
print(f"  - Векторизация vs Цикл: {t_loop/t_vectorized:.0f}x быстрее")
print(f"  - Векторизация vs Apply: {t_apply/t_vectorized:.0f}x быстрее")

print("""
💡 Правило: ВСЕГДА используй векторизацию!
Циклы - только если векторизация невозможна.
""")


# ========================================
# ЧАСТЬ 2: ТИПЫ MERGE (JOIN)
# ========================================

print("\n" + "=" * 70)
print("🔗 ЧАСТЬ 2: Типы JOIN в pandas")
print("=" * 70)

# Данные
users = pd.DataFrame({
    'user_id': [1, 2, 3, 4],
    'name': ['Алексей', 'Мария', 'Иван', 'Анна']
})

orders = pd.DataFrame({
    'order_id': [101, 102, 103, 104, 105],
    'user_id': [1, 2, 1, 5, 2],  # user_id=5 нет в users!
    'amount': [1200, 25, 80, 350, 500]
})

print("👥 Пользователи:")
print(users.to_string(index=False))
print("\n🛒 Заказы:")
print(orders.to_string(index=False))

# INNER JOIN - только совпадения
print("\n--- INNER JOIN (how='inner') ---")
inner = pd.merge(users, orders, on='user_id', how='inner')
print(inner.to_string(index=False))
print(f"📊 Строк: {len(inner)} (заказы с существующими юзерами)")

# LEFT JOIN - все пользователи
print("\n--- LEFT JOIN (how='left') ---")
left = pd.merge(users, orders, on='user_id', how='left')
print(left.to_string(index=False))
print(f"📊 Строк: {len(left)} (все юзеры, даже без заказов)")

# RIGHT JOIN - все заказы
print("\n--- RIGHT JOIN (how='right') ---")
right = pd.merge(users, orders, on='user_id', how='right')
print(right.to_string(index=False))
print(f"📊 Строк: {len(right)} (все заказы, даже от несуществующих юзеров)")

# OUTER JOIN - все данные
print("\n--- OUTER JOIN (how='outer') ---")
outer = pd.merge(users, orders, on='user_id', how='outer')
print(outer.to_string(index=False))
print(f"📊 Строк: {len(outer)} (все юзеры + все заказы)")


# ========================================
# ЧАСТЬ 3: GROUPBY - ПРОДВИНУТОЕ
# ========================================

print("\n" + "=" * 70)
print("📊 ЧАСТЬ 3: GroupBy - продвинутые техники")
print("=" * 70)

sales_data = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=100, freq='D'),
    'product': np.random.choice(['Ноутбук', 'Мышь', 'Клавиатура'], 100),
    'region': np.random.choice(['Москва', 'Казань', 'Омск'], 100),
    'revenue': np.random.randint(100, 5000, 100)
})

# Множественные агрегации
print("--- Множественные агрегации ---")
agg_result = sales_data.groupby('product').agg({
    'revenue': ['sum', 'mean', 'count', 'std']
}).round(2)
print(agg_result)

# Группировка по нескольким колонкам
print("\n--- Группировка по региону + продукту ---")
multi_group = sales_data.groupby(['region', 'product'])['revenue'].sum().unstack(fill_value=0)
print(multi_group)

# Named aggregation (pandas >= 1.0)
print("\n--- Named aggregation (читаемо!) ---")
named_agg = sales_data.groupby('product').agg(
    total_revenue=('revenue', 'sum'),
    avg_revenue=('revenue', 'mean'),
    sales_count=('revenue', 'count')
).round(2)
print(named_agg)


# ========================================
# ЧАСТЬ 4: PIVOT И MELT
# ========================================

print("\n" + "=" * 70)
print("🔄 ЧАСТЬ 4: Pivot (широкий) и Melt (длинный)")
print("=" * 70)

# Исходные данные (длинный формат)
long_data = pd.DataFrame({
    'date': ['2024-01-01', '2024-01-01', '2024-01-02', '2024-01-02'],
    'product': ['Ноутбук', 'Мышь', 'Ноутбук', 'Мышь'],
    'revenue': [1200, 25, 1100, 30]
})

print("📊 Длинный формат (long):")
print(long_data.to_string(index=False))

# PIVOT: Длинный → Широкий
print("\n--- PIVOT: Широкий формат ---")
wide_data = long_data.pivot(index='date', columns='product', values='revenue')
print(wide_data)

# MELT: Широкий → Длинный
print("\n--- MELT: Обратно в длинный ---")
melted = wide_data.reset_index().melt(id_vars='date', var_name='product', value_name='revenue')
print(melted.to_string(index=False))

print("""
💡 Когда использовать:
- PIVOT: Для отчетов (Excel-стиль), визуализаций
- MELT: Для анализа (SQL-стиль), машинного обучения
""")


# ========================================
# ЧАСТЬ 5: РАБОТА С БОЛЬШИМИ ФАЙЛАМИ
# ========================================

print("\n" + "=" * 70)
print("💾 ЧАСТЬ 5: Чтение больших файлов по частям")
print("=" * 70)

# Создаем большой CSV
print("📝 Создаем тестовый большой файл...")
big_df = pd.DataFrame({
    'user_id': np.random.randint(1, 10000, 500000),
    'amount': np.random.randint(10, 5000, 500000),
    'date': pd.date_range('2020-01-01', periods=500000, freq='min')
})
big_df.to_csv('big_file.csv', index=False)
print(f"✅ Создан файл: 500,000 строк\n")

# ❌ Плохо: Читаем весь файл (много памяти)
print("❌ Читаем весь файл сразу:")
start = time.time()
df_full = pd.read_csv('big_file.csv')
t_full = time.time() - start
print(f"  Время: {t_full:.4f} сек")
print(f"  Память: ~{df_full.memory_usage(deep=True).sum() / 1024**2:.2f} MB")

# ✅ Хорошо: Читаем по частям (chunks)
print("\n✅ Читаем по частям (chunks):")
start = time.time()
chunk_size = 50000
totals = []

for chunk in pd.read_csv('big_file.csv', chunksize=chunk_size):
    # Обрабатываем только нужное
    chunk_total = chunk[chunk['amount'] > 1000]['amount'].sum()
    totals.append(chunk_total)

total_revenue = sum(totals)
t_chunks = time.time() - start

print(f"  Время: {t_chunks:.4f} сек")
print(f"  Общая выручка (amount > 1000): {total_revenue:,.0f}₽")
print(f"  Экономия памяти: ~10x (обрабатываем по 50k строк)")


# ========================================
# ЧАСТЬ 6: КАТЕГОРИАЛЬНЫЕ ДАННЫЕ
# ========================================

print("\n" + "=" * 70)
print("🏷️ ЧАСТЬ 6: Категориальные данные (экономия памяти)")
print("=" * 70)

# Данные с повторяющимися строками
df_cat = pd.DataFrame({
    'product': ['Ноутбук'] * 10000 + ['Мышь'] * 10000 + ['Клавиатура'] * 10000,
    'price': np.random.randint(100, 5000, 30000)
})

print("📊 Обычный string:")
print(f"  Память: {df_cat['product'].memory_usage(deep=True) / 1024:.2f} KB")

# Конвертируем в categorical
df_cat['product'] = df_cat['product'].astype('category')
print("\n🏷️ Categorical:")
print(f"  Память: {df_cat['product'].memory_usage(deep=True) / 1024:.2f} KB")
print(f"  Экономия: ~90% для повторяющихся значений!")

print("""
💡 Используй categorical для:
- Колонок с небольшим числом уникальных значений
- Статусов (Active/Inactive), категорий, регионов
""")


# ========================================
# ПРАКТИЧЕСКАЯ ЗАДАЧА: ЧИСТКА ДАННЫХ
# ========================================

print("\n" + "=" * 70)
print("🎯 ПРАКТИЧЕСКАЯ ЗАДАЧА: Полный pipeline очистки")
print("=" * 70)

# Грязные данные (как из реального API)
dirty_df = pd.DataFrame({
    'user_id': [1, 2, 3, None, 5, 6],
    'name': ['  Алексей  ', 'МАРИЯ', None, 'Иван', '  анна', 'Дмитрий  '],
    'email': ['alex@mail.ru', 'maria@', 'ivan@test.com', 
              'invalid', 'anna@test.com', None],
    'age': [25, 30, 'тридцать пять', 28, 22, 40],
    'revenue': ['1200', '2500.50', None, '3000', 'N/A', '1500']
})

print("📊 Грязные данные:")
print(dirty_df)

# Pipeline очистки
def clean_pipeline(df):
    """Полный pipeline очистки данных"""
    df = df.copy()
    
    # 1. Убираем пробелы из строк
    for col in df.select_dtypes(include='object').columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    
    # 2. Приводим имена к Title Case
    if 'name' in df.columns:
        df['name'] = df[col].str.title()
    
    # 3. Конвертируем revenue в числа
    if 'revenue' in df.columns:
        df['revenue'] = pd.to_numeric(df['revenue'], errors='coerce')
    
    # 4. Заполняем пропуски
    df['revenue'] = df['revenue'].fillna(0)
    
    # 5. Удаляем строки с критичными пропусками
    df = df.dropna(subset=['user_id'])
    
    # 6. Валидация email (простая)
    if 'email' in df.columns:
        df['email_valid'] = df['email'].str.contains('@', na=False) & \
                            df['email'].str.contains(r'\..+', regex=True, na=False)
    
    return df

cleaned_df = clean_pipeline(dirty_df)

print("\n✅ Очищенные данные:")
print(cleaned_df.to_string(index=False))

print(f"\n📊 Было строк: {len(dirty_df)}, стало: {len(cleaned_df)}")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 11 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил pandas на продвинутом уровне:
1. ✅ Векторизация vs циклы (100x ускорение!)
2. ✅ 4 типа JOIN (inner, left, right, outer)
3. ✅ GroupBy с множественными агрегациями
4. ✅ Pivot/Melt для трансформации данных
5. ✅ Чтение больших файлов по частям (chunks)
6. ✅ Categorical для экономии памяти (90%!)
7. ✅ Полный pipeline очистки данных

Это уровень Middle Data Engineer!
Следующий шаг: День 12 - NumPy основы
""")

# Очистка
import os
os.remove('big_file.csv')
print("\n🗑️ Тестовый файл удален")