"""
День 36: Pandas vs Polars — сравнение производительности
vectorization, categorical dtypes, Parquet, lazy evaluation
"""

import pandas as pd
import numpy as np
import time
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

plt.rcParams['font.family'] = 'DejaVu Sans'

print("=" * 70)
print(" " * 5 + "ДЕНЬ 36: PANDAS VS POLARS — PERFORMANCE")
print("=" * 70)

Path('reports').mkdir(exist_ok=True)
Path('data/perf').mkdir(parents=True, exist_ok=True)

# Проверяем наличие Polars
try:
    import polars as pl
    POLARS_AVAILABLE = True
    print(f"Polars версия: {pl.__version__} ✓")
except ImportError:
    POLARS_AVAILABLE = False
    print("Polars не установлен. Устанавливаем...")
    import subprocess, sys
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'polars',
                    '--quiet', '--break-system-packages'])
    import polars as pl
    POLARS_AVAILABLE = True
    print(f"Polars {pl.__version__} установлен ✓")

print(f"Pandas версия: {pd.__version__} ✓")


# ========================================
# ЧАСТЬ 1: ГЕНЕРАЦИЯ ДАННЫХ
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Генерация данных — 2М строк")
print("=" * 70)

N = 2_000_000
np.random.seed(42)

print(f"Генерация {N:,} строк...")
t0 = time.time()

raw_data = {
    'order_id':    np.arange(1, N + 1),
    'customer_id': np.random.randint(1, 50001, N),
    'category':    np.random.choice(
        ['Электроника', 'Одежда', 'Дом', 'Спорт', 'Книги'], N
    ),
    'city':        np.random.choice(
        ['Москва', 'СПб', 'Казань', 'Екб', 'НСК',
         'Краснодар', 'Ростов', 'Уфа', 'Пермь', 'Волгоград'], N
    ),
    'status':      np.random.choice(
        ['completed', 'cancelled', 'refunded'], N, p=[0.7, 0.2, 0.1]
    ),
    'amount':      np.random.randint(100, 50000, N),
    'quantity':    np.random.randint(1, 6, N),
    'discount':    np.random.choice([0, 5, 10, 15, 20], N).astype(float),
    'order_date':  pd.date_range('2022-01-01', periods=N, freq='16s'),
}

df_pandas = pd.DataFrame(raw_data)
print(f"Создан DataFrame за {time.time()-t0:.1f}с")
print(f"Размер (object dtype):    {df_pandas.memory_usage(deep=True).sum()/1024**2:.0f} МБ")

# Оптимизация типов
df_pandas_opt = df_pandas.copy()
for col in ['category', 'city', 'status']:
    df_pandas_opt[col] = df_pandas_opt[col].astype('category')
print(f"Размер (category dtype):  {df_pandas_opt.memory_usage(deep=True).sum()/1024**2:.0f} МБ")
print(f"Экономия памяти:          {(1 - df_pandas_opt.memory_usage(deep=True).sum()/df_pandas.memory_usage(deep=True).sum())*100:.0f}%")

# Создаём Polars DataFrame
df_polars = pl.DataFrame({
    'order_id':    raw_data['order_id'],
    'customer_id': raw_data['customer_id'],
    'category':    raw_data['category'],
    'city':        raw_data['city'],
    'status':      raw_data['status'],
    'amount':      raw_data['amount'],
    'quantity':    raw_data['quantity'],
    'discount':    raw_data['discount'],
})


# ========================================
# ЧАСТЬ 2: BENCHMARK — ФИЛЬТРАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: Benchmark — Фильтрация и агрегация")
print("=" * 70)

results = {}

def bench(name, fn, runs=3):
    times = []
    for _ in range(runs):
        t = time.time()
        fn()
        times.append(time.time() - t)
    avg = sum(times) / len(times)
    results[name] = avg
    return avg

# --- Тест 1: Фильтрация ---
print("\n--- Тест 1: Фильтрация (status='completed') ---")

t1 = bench("Pandas object",
    lambda: df_pandas[df_pandas['status'] == 'completed'])
t2 = bench("Pandas category",
    lambda: df_pandas_opt[df_pandas_opt['status'] == 'completed'])
t3 = bench("Polars",
    lambda: df_polars.filter(pl.col('status') == 'completed'))

print(f"  Pandas (object):   {t1*1000:.0f}мс")
print(f"  Pandas (category): {t2*1000:.0f}мс  ({t1/t2:.1f}x быстрее Pandas)")
print(f"  Polars:            {t3*1000:.0f}мс  ({t1/t3:.1f}x быстрее Pandas)")

# --- Тест 2: Агрегация ---
print("\n--- Тест 2: GROUP BY агрегация ---")

t4 = bench("Pandas groupby",
    lambda: df_pandas.groupby('category')['amount'].agg(['sum', 'mean', 'count']))
t5 = bench("Pandas category groupby",
    lambda: df_pandas_opt.groupby('category', observed=True)['amount'].agg(['sum', 'mean', 'count']))
t6 = bench("Polars groupby",
    lambda: df_polars.group_by('category').agg([
        pl.col('amount').sum().alias('sum'),
        pl.col('amount').mean().alias('mean'),
        pl.col('amount').count().alias('count'),
    ]))

print(f"  Pandas (object):   {t4*1000:.0f}мс")
print(f"  Pandas (category): {t5*1000:.0f}мс  ({t4/t5:.1f}x быстрее Pandas)")
print(f"  Polars:            {t6*1000:.0f}мс  ({t4/t6:.1f}x быстрее Pandas)")

# --- Тест 3: Вычисляемые поля (векторизация) ---
print("\n--- Тест 3: Вычисляемые поля ---")

def pandas_calc_loop():
    """Плохо — цикл"""
    result = []
    sample = df_pandas.head(100_000)
    for _, row in sample.iterrows():
        result.append(row['amount'] * (1 - row['discount'] / 100) * row['quantity'])
    return result

def pandas_calc_vec():
    """Хорошо — векторизация"""
    return df_pandas['amount'] * (1 - df_pandas['discount'] / 100) * df_pandas['quantity']

def polars_calc():
    return df_polars.with_columns(
        (pl.col('amount') * (1 - pl.col('discount') / 100) * pl.col('quantity'))
        .alias('total')
    )

print("  Pandas цикл (100К строк):", end=' ')
t_loop = bench("Pandas loop", pandas_calc_loop, runs=1)
print(f"{t_loop*1000:.0f}мс")

t7 = bench("Pandas vectorized", pandas_calc_vec)
t8 = bench("Polars", polars_calc)

print(f"  Pandas векторизация (2М): {t7*1000:.0f}мс")
print(f"  Polars (2М):              {t8*1000:.0f}мс  ({t7/t8:.1f}x быстрее Pandas)")
print(f"  Цикл vs векторизация:     {t_loop/t7:.0f}x разница!")

# --- Тест 4: Sort ---
print("\n--- Тест 4: Сортировка ---")

t9  = bench("Pandas sort",
    lambda: df_pandas.sort_values(['city', 'amount'], ascending=[True, False]))
t10 = bench("Polars sort",
    lambda: df_polars.sort(['city', 'amount'], descending=[False, True]))

print(f"  Pandas: {t9*1000:.0f}мс")
print(f"  Polars: {t10*1000:.0f}мс  ({t9/t10:.1f}x быстрее)")

# --- Тест 5: Фильтр + GroupBy + Sort (сложный запрос) ---
print("\n--- Тест 5: Сложный запрос (filter + groupby + sort) ---")

def pandas_complex():
    return (df_pandas_opt[df_pandas_opt['status'] == 'completed']
            .groupby(['city', 'category'], observed=True)['amount']
            .sum()
            .reset_index()
            .sort_values('amount', ascending=False)
            .head(20))

def polars_complex():
    return (df_polars
            .filter(pl.col('status') == 'completed')
            .group_by(['city', 'category'])
            .agg(pl.col('amount').sum())
            .sort('amount', descending=True)
            .head(20))

t11 = bench("Pandas complex", pandas_complex)
t12 = bench("Polars complex", polars_complex)

print(f"  Pandas: {t11*1000:.0f}мс")
print(f"  Polars: {t12*1000:.0f}мс  ({t11/t12:.1f}x быстрее)")


# ========================================
# ЧАСТЬ 3: POLARS LAZY API
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: Polars Lazy API — отложенное выполнение")
print("=" * 70)

print("""
Polars Lazy API:
  df.lazy()       — переходим в lazy режим
  .filter(...)    — добавляем операции (НЕ выполняем)
  .group_by(...)  — добавляем
  .collect()      — ВЫПОЛНЯЕМ всё сразу (оптимизированный план)

Polars оптимизирует весь pipeline перед выполнением:
  - Pushdown предикатов (фильтры применяются как можно раньше)
  - Projection pushdown (читает только нужные столбцы)
  - Параллельное выполнение
""")

def polars_eager():
    return (df_polars
            .filter(pl.col('status') == 'completed')
            .filter(pl.col('amount') > 5000)
            .group_by(['city', 'category'])
            .agg([
                pl.col('amount').sum().alias('выручка'),
                pl.col('order_id').count().alias('заказов'),
                pl.col('amount').mean().alias('средний_чек'),
            ])
            .sort('выручка', descending=True))

def polars_lazy():
    return (df_polars.lazy()
            .filter(pl.col('status') == 'completed')
            .filter(pl.col('amount') > 5000)
            .group_by(['city', 'category'])
            .agg([
                pl.col('amount').sum().alias('выручка'),
                pl.col('order_id').count().alias('заказов'),
                pl.col('amount').mean().alias('средний_чек'),
            ])
            .sort('выручка', descending=True)
            .collect())

t13 = bench("Polars Eager", polars_eager)
t14 = bench("Polars Lazy",  polars_lazy)

print(f"  Polars Eager: {t13*1000:.0f}мс")
print(f"  Polars Lazy:  {t14*1000:.0f}мс  ({t13/t14:.1f}x)")

# Показываем результат
result = polars_lazy()
print("\nТоп-10 город × категория по выручке:")
print(result.head(10))


# ========================================
# ЧАСТЬ 4: PARQUET — БЫСТРОЕ ЧТЕНИЕ/ЗАПИСЬ
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: Parquet — читаем и пишем")
print("=" * 70)

csv_path     = Path('data/perf/orders.csv')
parquet_path = Path('data/perf/orders.parquet')

# Сохраняем CSV
print("Запись CSV и Parquet (500К строк)...")
df_sample = df_pandas.head(500_000)

t_csv_write = time.time()
df_sample.to_csv(csv_path, index=False)
t_csv_write = time.time() - t_csv_write

t_parquet_write = time.time()
df_sample.to_parquet(parquet_path, index=False, compression='snappy')
t_parquet_write = time.time() - t_parquet_write

csv_size     = csv_path.stat().st_size / 1024**2
parquet_size = parquet_path.stat().st_size / 1024**2

print(f"\n  CSV:     {t_csv_write:.2f}с | {csv_size:.1f} МБ")
print(f"  Parquet: {t_parquet_write:.2f}с | {parquet_size:.1f} МБ")
print(f"  Размер: Parquet в {csv_size/parquet_size:.1f}x меньше CSV")

# Чтение
t_csv_read = bench("CSV read",
    lambda: pd.read_csv(csv_path), runs=2)
t_parquet_pd = bench("Parquet Pandas",
    lambda: pd.read_parquet(parquet_path), runs=2)
t_parquet_pl = bench("Parquet Polars",
    lambda: pl.read_parquet(parquet_path), runs=2)

print(f"\n  Чтение CSV (Pandas):    {t_csv_read:.2f}с")
print(f"  Чтение Parquet (Pandas): {t_parquet_pd:.2f}с  ({t_csv_read/t_parquet_pd:.1f}x быстрее)")
print(f"  Чтение Parquet (Polars): {t_parquet_pl:.2f}с  ({t_csv_read/t_parquet_pl:.1f}x быстрее)")

# Column pruning — читаем только нужные столбцы
t_all_cols = bench("Все столбцы",
    lambda: pl.read_parquet(parquet_path), runs=2)
t_few_cols = bench("2 столбца",
    lambda: pl.read_parquet(parquet_path, columns=['order_id', 'amount']), runs=2)

print(f"\n  Parquet все столбцы:  {t_all_cols:.3f}с")
print(f"  Parquet 2 столбца:    {t_few_cols:.3f}с  ({t_all_cols/t_few_cols:.1f}x быстрее)")
print("  Column pruning — читаем только нужные столбцы из Parquet!")


# ========================================
# ЧАСТЬ 5: CATEGORICAL DTYPES
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: Category dtype — экономия памяти и скорость")
print("=" * 70)

mem_before = df_pandas.memory_usage(deep=True).sum() / 1024**2
df_opt = df_pandas.copy()
for col in ['category', 'city', 'status']:
    df_opt[col] = df_opt[col].astype('category')
mem_after = df_opt.memory_usage(deep=True).sum() / 1024**2

print(f"  Память до оптимизации:  {mem_before:.0f} МБ")
print(f"  Память после:           {mem_after:.0f} МБ")
print(f"  Экономия:               {mem_before-mem_after:.0f} МБ ({(1-mem_after/mem_before)*100:.0f}%)")

print("""
  Как работает category dtype:
    'Москва', 'СПб', 'Казань'... → коды [0, 1, 2...]
    Хранятся только коды (int8) вместо строк
    10 уникальных городов из 2М строк:
      object:   2М × ~20 байт = 40 МБ
      category: 2М × 1 байт  + 10 строк = 2 МБ
""")

# GroupBy с category dtype
t_obj = bench("GroupBy object",
    lambda: df_pandas.groupby('city')['amount'].sum())
t_cat = bench("GroupBy category",
    lambda: df_opt.groupby('city', observed=True)['amount'].sum())
print(f"  GroupBy object:   {t_obj*1000:.0f}мс")
print(f"  GroupBy category: {t_cat*1000:.0f}мс  ({t_obj/t_cat:.1f}x быстрее)")


# ========================================
# ЧАСТЬ 6: КОГДА ЧТО ИСПОЛЬЗОВАТЬ
# ========================================

print("\n" + "=" * 70)
print("6  ЧАСТЬ 6: Pandas vs Polars — когда что использовать")
print("=" * 70)

print("""
┌──────────────────────┬──────────────────────┬──────────────────────┐
│                      │       Pandas         │       Polars         │
├──────────────────────┼──────────────────────┼──────────────────────┤
│ Скорость             │ Медленнее            │ 5-100x быстрее       │
│ Память               │ Больше               │ Меньше               │
│ API                  │ Знакомый, гибкий     │ Строгий, чистый      │
│ Lazy API             │ Нет                  │ Да (.lazy().collect) │
│ Параллелизм          │ Нет (GIL)            │ Да (по умолчанию)    │
│ Экосистема           │ Огромная             │ Растёт               │
│ Совместимость        │ Везде                │ Не везде             │
│ Обучение             │ Много курсов         │ Меньше материалов    │
├──────────────────────┼──────────────────────┼──────────────────────┤
│ Когда Pandas:        │ < 1М строк, быстрый прототип, sklearn       │
│ Когда Polars:        │ > 1М строк, ETL pipeline, production        │
│ Когда DuckDB:        │ SQL запросы, аналитика, joins, aggregations  │
└──────────────────────────────────────────────────────────────────┘

Рекомендация для Analytics Engineer:
  Знай Pandas → Изучи Polars → Используй DuckDB для SQL
""")


# ========================================
# ЧАСТЬ 7: ВИЗУАЛИЗАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("7  ЧАСТЬ 7: Визуализация результатов")
print("=" * 70)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('День 36: Pandas vs Polars — Performance Benchmark (2М строк)',
             fontsize=13, fontweight='bold')

# 1. Бенчмарк основных операций
ax1 = axes[0, 0]
ops      = ['Фильтрация', 'GroupBy', 'Вычисл.\nполя', 'Сортировка', 'Сложный\nзапрос']
pandas_t = [t2*1000, t5*1000, t7*1000, t9*1000, t11*1000]
polars_t = [t3*1000, t6*1000, t8*1000, t10*1000, t12*1000]
x = np.arange(len(ops))
w = 0.35
ax1.bar(x-w/2, pandas_t, w, label='Pandas',
        color='#3498db', alpha=0.85)
ax1.bar(x+w/2, polars_t, w, label='Polars',
        color='#e74c3c', alpha=0.85)
ax1.set_title('Время выполнения (мс)', fontweight='bold')
ax1.set_xticks(x)
ax1.set_xticklabels(ops, fontsize=8)
ax1.set_ylabel('мс')
ax1.legend()
ax1.grid(axis='y', alpha=0.3)

# 2. Speedup Polars vs Pandas
ax2 = axes[0, 1]
speedups = [t2/t3, t5/t6, t7/t8, t9/t10, t11/t12]
colors_s = ['#2ecc71' if s >= 3 else '#f39c12' if s >= 1.5 else '#e74c3c'
            for s in speedups]
bars = ax2.bar(ops, speedups, color=colors_s, alpha=0.85)
ax2.axhline(y=1, color='black', linewidth=1.5, linestyle='--')
for bar, val in zip(bars, speedups):
    ax2.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.1,
             f'{val:.1f}x', ha='center', va='bottom',
             fontsize=10, fontweight='bold')
ax2.set_title('Ускорение Polars vs Pandas', fontweight='bold')
ax2.set_ylabel('Ускорение (раз)')
ax2.tick_params(axis='x', labelsize=8)
ax2.grid(axis='y', alpha=0.3)

# 3. Память: object vs category
ax3 = axes[1, 0]
cols_show = ['category', 'city', 'status', 'amount', 'order_id']
mem_obj = [df_pandas[c].memory_usage(deep=True)/1024**2 for c in cols_show]
mem_cat = [df_opt[c].memory_usage(deep=True)/1024**2 for c in cols_show]
x3 = np.arange(len(cols_show))
ax3.bar(x3-0.2, mem_obj, 0.4, label='object/int', color='#e74c3c', alpha=0.8)
ax3.bar(x3+0.2, mem_cat, 0.4, label='category',   color='#2ecc71', alpha=0.8)
ax3.set_title('Память по столбцам (МБ)', fontweight='bold')
ax3.set_xticks(x3)
ax3.set_xticklabels(cols_show)
ax3.set_ylabel('МБ')
ax3.legend()
ax3.grid(axis='y', alpha=0.3)

# 4. Parquet vs CSV
ax4 = axes[1, 1]
labels4 = ['CSV\n(запись)', 'Parquet\n(запись)', 'CSV\n(чтение)', 'Parquet\n(чтение)']
times4  = [t_csv_write, t_parquet_write, t_csv_read, t_parquet_pd]
colors4 = ['#e74c3c', '#2ecc71', '#e74c3c', '#2ecc71']
bars4   = ax4.bar(labels4, [t*1000 for t in times4], color=colors4, alpha=0.85)
for bar, val in zip(bars4, [t*1000 for t in times4]):
    ax4.text(bar.get_x()+bar.get_width()/2, bar.get_height()+5,
             f'{val:.0f}мс', ha='center', va='bottom', fontsize=9, fontweight='bold')
ax4.set_title(f'CSV vs Parquet (500К строк)\nРазмер: CSV={csv_size:.0f}МБ, Parquet={parquet_size:.0f}МБ',
              fontweight='bold')
ax4.set_ylabel('Время (мс)')
ax4.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig('reports/day36_pandas_polars.png', dpi=150, bbox_inches='tight')
plt.close()
print("График сохранён: reports/day36_pandas_polars.png")

print("\n" + "=" * 70)
print("ДЕНЬ 36 ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Pandas vs Polars — ключевые выводы:

Фильтрация:      Polars в {t2/t3:.1f}x быстрее Pandas
GroupBy:         Polars в {t5/t6:.1f}x быстрее Pandas
Вычисл. поля:    Polars в {t7/t8:.1f}x быстрее Pandas
Сортировка:      Polars в {t9/t10:.1f}x быстрее Pandas
Сложный запрос:  Polars в {t11/t12:.1f}x быстрее Pandas

Цикл vs векторизация: {t_loop/t7:.0f}x разница!

Category dtype: экономит {mem_before-mem_after:.0f} МБ памяти
Parquet vs CSV: в {csv_size/parquet_size:.1f}x меньше, в {t_csv_read/t_parquet_pd:.1f}x быстрее чтение

Следующий день: День 37 — Chunking, Streaming, DuckDB out-of-core
""")