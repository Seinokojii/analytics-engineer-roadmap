"""
День 16: Advanced Pandas - Performance & Optimization
Работа с большими данными эффективно
"""

import pandas as pd
import numpy as np
import time

print("=" * 70)
print(" " * 10 + "🐼 ДЕНЬ 16: ADVANCED PANDAS PERFORMANCE")
print("=" * 70)

# ========================================
# ЧАСТЬ 1: ОПТИМИЗАЦИЯ ПАМЯТИ
# ========================================

print("\n" + "=" * 70)
print("💾 ЧАСТЬ 1: Оптимизация использования памяти")
print("=" * 70)

# Создаем большой DataFrame
np.random.seed(42)
n_rows = 1_000_000

df_large = pd.DataFrame({
    'user_id': np.random.randint(1, 100000, n_rows),
    'product_id': np.random.randint(1, 10000, n_rows),
    'amount': np.random.randint(10, 5000, n_rows),
    'status': np.random.choice(['active', 'inactive', 'pending'], n_rows),
    'category': np.random.choice(['Tech', 'Office', 'Home', 'Fashion'], n_rows),
    'timestamp': pd.date_range('2024-01-01', periods=n_rows, freq='30s')
})

print(f"📊 Создан DataFrame: {len(df_large):,} строк")

# Проверяем исходное использование памяти
memory_before = df_large.memory_usage(deep=True).sum() / 1024**2
print(f"\n💾 Память ДО оптимизации: {memory_before:.2f} MB")
print("\nТипы данных ДО:")
print(df_large.dtypes)

# Оптимизация
def optimize_dtypes(df):
    """Оптимизирует типы данных для экономии памяти"""
    df_opt = df.copy()
    
    # Целочисленные колонки → int32 (вместо int64)
    for col in df_opt.select_dtypes(include=['int64']).columns:
        col_min = df_opt[col].min()
        col_max = df_opt[col].max()
        
        if col_min >= 0:  # Unsigned
            if col_max < 256:
                df_opt[col] = df_opt[col].astype('uint8')
            elif col_max < 65536:
                df_opt[col] = df_opt[col].astype('uint16')
            else:
                df_opt[col] = df_opt[col].astype('uint32')
        else:  # Signed
            if col_min > -128 and col_max < 127:
                df_opt[col] = df_opt[col].astype('int8')
            elif col_min > -32768 and col_max < 32767:
                df_opt[col] = df_opt[col].astype('int16')
            else:
                df_opt[col] = df_opt[col].astype('int32')
    
    # Строковые колонки с низкой кардинальностью → category
    for col in df_opt.select_dtypes(include=['object']).columns:
        num_unique = df_opt[col].nunique()
        num_total = len(df_opt)
        
        if num_unique / num_total < 0.5:  # Если < 50% уникальных
            df_opt[col] = df_opt[col].astype('category')
    
    return df_opt

df_optimized = optimize_dtypes(df_large)

memory_after = df_optimized.memory_usage(deep=True).sum() / 1024**2
print(f"\n💾 Память ПОСЛЕ оптимизации: {memory_after:.2f} MB")
print(f"📉 Экономия: {memory_before - memory_after:.2f} MB ({(memory_before-memory_after)/memory_before*100:.1f}%)")

print("\nТипы данных ПОСЛЕ:")
print(df_optimized.dtypes)

# ========================================
# ЧАСТЬ 2: QUERY OPTIMIZATION
# ========================================

print("\n" + "=" * 70)
print("⚡ ЧАСТЬ 2: Оптимизация запросов")
print("=" * 70)

# ❌ Медленный способ: последовательные операции
start = time.time()
result_slow = df_large[df_large['status'] == 'active']
result_slow = result_slow[result_slow['amount'] > 1000]
result_slow = result_slow.groupby('category')['amount'].sum()
t_slow = time.time() - start

print(f"❌ Последовательные операции: {t_slow:.4f} сек")

# ✅ Быстрый способ: .query() + method chaining
start = time.time()
result_fast = (df_large
    .query('status == "active" and amount > 1000')
    .groupby('category')['amount']
    .sum()
)
t_fast = time.time() - start

print(f"✅ .query() + chaining: {t_fast:.4f} сек")
print(f"🚀 Ускорение: {t_slow/t_fast:.2f}x")

# ========================================
# ЧАСТЬ 3: EVAL ДЛЯ ВЫЧИСЛЕНИЙ
# ========================================

print("\n" + "=" * 70)
print("🧮 ЧАСТЬ 3: pd.eval() для быстрых вычислений")
print("=" * 70)

# Создаем тестовые колонки
df_test = pd.DataFrame({
    'A': np.random.randn(100000),
    'B': np.random.randn(100000),
    'C': np.random.randn(100000),
    'D': np.random.randn(100000)
})

# ❌ Обычный способ
start = time.time()
result1 = df_test['A'] + df_test['B'] * df_test['C'] - df_test['D']
t1 = time.time() - start

# ✅ С pd.eval()
start = time.time()
result2 = df_test.eval('A + B * C - D')
t2 = time.time() - start

print(f"❌ Обычные операции: {t1:.4f} сек")
print(f"✅ pd.eval(): {t2:.4f} сек")
print(f"🚀 Ускорение: {t1/t2:.2f}x")

# ========================================
# ЧАСТЬ 4: CHUNK PROCESSING
# ========================================

print("\n" + "=" * 70)
print("📦 ЧАСТЬ 4: Обработка по частям (chunks)")
print("=" * 70)

# Сохраняем большой файл
df_large.to_csv('large_file.csv', index=False)
print("💾 Создан large_file.csv (~100 MB)")

# Обработка по частям
chunk_size = 100000
results = []

print(f"\n📦 Обработка файла chunks по {chunk_size:,} строк...")
start = time.time()

for i, chunk in enumerate(pd.read_csv('large_file.csv', chunksize=chunk_size), 1):
    # Фильтруем и агрегируем каждый chunk
    chunk_result = chunk[chunk['amount'] > 1000].groupby('category')['amount'].sum()
    results.append(chunk_result)
    print(f"  ✅ Chunk {i} обработан")

# Объединяем результаты
final_result = pd.concat(results).groupby(level=0).sum()
t_chunks = time.time() - start

print(f"\n⏱️ Время обработки: {t_chunks:.4f} сек")
print(f"📊 Результат:")
print(final_result)

# ========================================
# ЧАСТЬ 5: APPLY VS VECTORIZATION
# ========================================

print("\n" + "=" * 70)
print("⚡ ЧАСТЬ 5: apply() vs векторизация (повтор)")
print("=" * 70)

df_sample = df_large.head(50000).copy()

# Задача: классифицировать amount
def classify_amount(x):
    if x < 1000:
        return 'low'
    elif x < 3000:
        return 'medium'
    else:
        return 'high'

# ❌ С apply
try:
    start = time.time()
    df_sample['tier_apply'] = df_sample['amount'].apply(classify_amount)
    t_apply = time.time() - start
    
    # ✅ С np.select (векторизация)
    start = time.time()
    conditions = [
        df_sample['amount'] < 1000,
        (df_sample['amount'] >= 1000) & (df_sample['amount'] < 3000),
        df_sample['amount'] >= 3000
    ]
    choices = ['low', 'medium', 'high']
    df_sample['tier_vectorized'] = np.select(conditions, choices, default='unknown')
    t_vectorized = time.time() - start
    
    print(f"❌ apply(): {t_apply:.4f} сек")
    print(f"✅ np.select(): {t_vectorized:.4f} сек")
    print(f"🚀 Ускорение: {t_apply/t_vectorized:.2f}x")
    
except Exception as e:
    print(f"⚠️ Ошибка в ЧАСТИ 5: {e}")
    print("Пропускаем эту часть и продолжаем...")
# ========================================
# ЧАСТЬ 6: MULTI-INDEX
# ========================================

print("\n" + "=" * 70)
print("📊 ЧАСТЬ 6: Multi-Index для иерархических данных")
print("=" * 70)

# Создаем multi-index DataFrame
df_multi = df_large.head(1000).set_index(['category', 'status'])

print("📊 Multi-Index DataFrame:")
print(df_multi.head(10))

# Быстрый доступ по multi-index
print("\n🔍 Фильтрация: category='Tech' и status='active'")
result = df_multi.loc[('Tech', 'active')]
print(result.head())

# Агрегация по уровням
print("\n📊 Агрегация по первому уровню (category):")
agg_result = df_multi.groupby(level=0)['amount'].sum()
print(agg_result)

# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 16 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил Advanced Pandas:
1. ✅ Оптимизация типов данных (экономия памяти ~70%)
2. ✅ .query() для быстрых фильтров
3. ✅ pd.eval() для вычислений (2-3x быстрее)
4. ✅ Chunk processing для огромных файлов
5. ✅ np.select вместо apply (10-100x быстрее)
6. ✅ Multi-Index для иерархических данных

НЕДЕЛЯ 3 НАЧАЛАСЬ! 🚀
Эти техники позволяют работать с датасетами в 10+ GB!
""")

# Очистка
import os
if os.path.exists('large_file.csv'):
    os.remove('large_file.csv')
print("\n🗑️ Тестовый файл удален")