"""
День 37: Работа с большими файлами
chunking, streaming in Python, DuckDB out-of-core аналитика
"""

import pandas as pd
import numpy as np
import duckdb
import time
import gc
import os
import matplotlib.pyplot as plt
from pathlib import Path

plt.rcParams['font.family'] = 'DejaVu Sans'

print("=" * 70)
print(" " * 5 + "ДЕНЬ 37: БОЛЬШИЕ ФАЙЛЫ — CHUNKING + DUCKDB OUT-OF-CORE")
print("=" * 70)

Path('data/large').mkdir(parents=True, exist_ok=True)
Path('reports').mkdir(exist_ok=True)


# ========================================
# ЧАСТЬ 1: ГЕНЕРАЦИЯ БОЛЬШОГО ФАЙЛА
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Создание большого файла для экспериментов")
print("=" * 70)

large_csv = Path('data/large/orders_large.csv')
large_parquet = Path('data/large/orders_large.parquet')

np.random.seed(42)
N_TOTAL   = 3_000_000
CHUNK_GEN = 500_000

if not large_csv.exists():
    print(f"Генерация {N_TOTAL:,} строк → {large_csv}")
    t0 = time.time()
    for i, start in enumerate(range(0, N_TOTAL, CHUNK_GEN)):
        end = min(start + CHUNK_GEN, N_TOTAL)
        n   = end - start
        chunk = pd.DataFrame({
            'order_id':    range(start + 1, end + 1),
            'customer_id': np.random.randint(1, 100001, n),
            'category':    np.random.choice(
                ['Электроника', 'Одежда', 'Дом', 'Спорт', 'Книги'], n
            ),
            'city':        np.random.choice(
                ['Москва', 'СПб', 'Казань', 'Екб', 'НСК',
                 'Краснодар', 'Ростов', 'Уфа', 'Пермь', 'Волгоград'], n
            ),
            'status':      np.random.choice(
                ['completed', 'cancelled', 'refunded'], n, p=[0.7, 0.2, 0.1]
            ),
            'amount':      np.random.randint(100, 50000, n),
            'quantity':    np.random.randint(1, 6, n),
            'order_date':  pd.date_range(
                f'2022-01-01', periods=n, freq='1s'
            ).strftime('%Y-%m-%d'),
        })
        mode   = 'w' if i == 0 else 'a'
        header = i == 0
        chunk.to_csv(large_csv, mode=mode, header=header, index=False)
        print(f"  Записан chunk {i+1}/{N_TOTAL//CHUNK_GEN}: {end:,} строк")
    print(f"CSV создан за {time.time()-t0:.1f}с")
else:
    print(f"Файл уже существует: {large_csv}")

csv_size_mb = large_csv.stat().st_size / 1024**2
print(f"Размер CSV: {csv_size_mb:.0f} МБ")


# ========================================
# ЧАСТЬ 2: ПРОБЛЕМА — ЧИТАЕМ ВСЁ В ПАМЯТЬ
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: Проблема — pd.read_csv() всего файла")
print("=" * 70)

print("""
Что происходит при pd.read_csv('большой_файл.csv'):

  1. Python читает ВЕСЬ файл в RAM
  2. 3М строк × ~10 столбцов ≈ 300-500 МБ RAM
  3. При 5-10 файлах — 3-5 ГБ RAM → OutOfMemoryError

Решения:
  1. Chunked reading    — читаем по кускам (pandas)
  2. DuckDB             — SQL прямо из файла (out-of-core)
  3. Polars lazy        — streaming без загрузки в память
  4. Dask               — распределённые DataFrame
""")

# Читаем весь файл
print("Читаем весь CSV (для сравнения)...")
t_full = time.time()
df_full = pd.read_csv(large_csv,
                      dtype={'category': 'category',
                             'city': 'category',
                             'status': 'category'})
t_full = time.time() - t_full
mem_full = df_full.memory_usage(deep=True).sum() / 1024**2
print(f"  Чтение всего файла: {t_full:.1f}с")
print(f"  Памяти занято:      {mem_full:.0f} МБ")
print(f"  Строк:              {len(df_full):,}")
del df_full
gc.collect()


# ========================================
# ЧАСТЬ 3: CHUNKED READING — PANDAS
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: Chunked Reading — pandas")
print("=" * 70)

print("Паттерн 1: Агрегация по чанкам")
t_chunk = time.time()
chunk_size = 200_000

total_revenue = 0
total_orders  = 0
city_revenue  = {}

for chunk in pd.read_csv(large_csv, chunksize=chunk_size,
                         dtype={'category': 'category',
                                'city': 'category',
                                'status': 'category'}):
    completed = chunk[chunk['status'] == 'completed']
    total_revenue += completed['amount'].sum()
    total_orders  += len(completed)
    city_agg = completed.groupby('city', observed=True)['amount'].sum()
    for city, rev in city_agg.items():
        city_revenue[city] = city_revenue.get(city, 0) + rev

t_chunk = time.time() - t_chunk
print(f"  Обработка чанками ({chunk_size:,} строк/чанк): {t_chunk:.2f}с")
print(f"  GMV: {total_revenue:,.0f} ₽ | Заказов: {total_orders:,}")
print("\n  Выручка по городам:")
for city, rev in sorted(city_revenue.items(), key=lambda x: -x[1]):
    print(f"    {city:12}: {rev:>15,.0f} ₽")

print("""
  Паттерн chunked reading:
    for chunk in pd.read_csv(file, chunksize=200_000):
        # обрабатываем только chunk (200К строк в памяти)
        # агрегируем результаты
  
  Плюсы:  Работает даже если файл > RAM
  Минусы: Медленнее DuckDB, нельзя делать JOIN между чанками
""")


# ========================================
# ЧАСТЬ 4: DUCKDB OUT-OF-CORE — ГЛАВНЫЙ ИНСТРУМЕНТ
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: DuckDB Out-of-Core — SQL прямо из файла")
print("=" * 70)

print("""
DuckDB читает CSV/Parquet НАПРЯМУЮ — не грузит в память:
  - Читает только нужные столбцы (projection pushdown)
  - Применяет фильтры при чтении (predicate pushdown)
  - Параллельно читает несколько чанков
  - Использует disk spill если не хватает RAM
""")

con = duckdb.connect(':memory:')

# Простая аналитика прямо из CSV
print("SQL прямо из CSV файла:")
t_duck_csv = time.time()
df_duck = con.execute(f"""
    SELECT
        city,
        category,
        COUNT(*)          AS заказов,
        SUM(amount)       AS выручка,
        ROUND(AVG(amount), 0) AS средний_чек
    FROM read_csv_auto('{large_csv}')
    WHERE status = 'completed'
    GROUP BY city, category
    ORDER BY выручка DESC
    LIMIT 15
""").df()
t_duck_csv = time.time() - t_duck_csv

print(f"  DuckDB CSV: {t_duck_csv:.2f}с")
print(df_duck.head(10).to_string(index=False))

# Сохраняем Parquet для ещё более быстрой работы
print("\nКонвертируем CSV → Parquet через DuckDB:")
t_convert = time.time()
con.execute(f"""
    COPY (SELECT * FROM read_csv_auto('{large_csv}'))
    TO '{large_parquet}'
    (FORMAT PARQUET, COMPRESSION SNAPPY)
""")
t_convert = time.time() - t_convert

parquet_size = large_parquet.stat().st_size / 1024**2
print(f"  Конвертация: {t_convert:.1f}с")
print(f"  Parquet:     {parquet_size:.0f} МБ (было CSV: {csv_size_mb:.0f} МБ)")
print(f"  Сжатие:      {csv_size_mb/parquet_size:.1f}x")

# Сравниваем скорость CSV vs Parquet
print("\nСравнение CSV vs Parquet в DuckDB:")
t_csv = time.time()
con.execute(f"""
    SELECT city, SUM(amount) FROM read_csv_auto('{large_csv}')
    WHERE status = 'completed' GROUP BY city
""").df()
t_csv = time.time() - t_csv

t_pq = time.time()
con.execute(f"""
    SELECT city, SUM(amount) FROM read_parquet('{large_parquet}')
    WHERE status = 'completed' GROUP BY city
""").df()
t_pq = time.time() - t_pq

print(f"  DuckDB + CSV:     {t_csv:.2f}с")
print(f"  DuckDB + Parquet: {t_pq:.2f}с  ({t_csv/t_pq:.1f}x быстрее)")


# ========================================
# ЧАСТЬ 5: ПРОДВИНУТЫЕ ПАТТЕРНЫ DUCKDB
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: Продвинутые паттерны DuckDB")
print("=" * 70)

# 5.1 Чтение нескольких файлов сразу (glob)
print("--- Glob: читаем несколько файлов сразу ---")

# Разбиваем на файлы по городам
cities = ['Москва', 'СПб', 'Казань']
for city in cities:
    t = time.time()
    city_safe = city.replace(" ", "_")
    con.execute(f"""
        COPY (
            SELECT * FROM read_parquet('{large_parquet}')
            WHERE city = '{city}'
        ) TO 'data/large/city_{city_safe}.parquet'
        (FORMAT PARQUET)
    """)
    n = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('data/large/city_{city_safe}.parquet')"
    ).fetchone()[0]
    print(f"  {city}: {n:,} строк, {time.time()-t:.1f}с")

# Читаем все файлы сразу через glob
t_glob = time.time()
df_all_cities = con.execute("""
    SELECT city, COUNT(*) AS заказов, SUM(amount) AS выручка
    FROM read_parquet('data/large/city_*.parquet')
    GROUP BY city ORDER BY выручка DESC
""").df()
t_glob = time.time() - t_glob
print(f"\n  Glob чтение 3 файлов: {t_glob:.2f}с")
print(df_all_cities.to_string(index=False))

# 5.2 Window Functions прямо на файле
print("\n--- Window Functions на Parquet файле ---")
t_wf = time.time()
df_wf = con.execute(f"""
    SELECT
        city,
        category,
        SUM(amount)  AS выручка,
        RANK() OVER (ORDER BY SUM(amount) DESC) AS ранг,
        ROUND(SUM(amount) * 100.0 / SUM(SUM(amount)) OVER (), 2) AS доля_pct
    FROM read_parquet('{large_parquet}')
    WHERE status = 'completed'
    GROUP BY city, category
    QUALIFY RANK() OVER (ORDER BY SUM(amount) DESC) <= 10
    ORDER BY выручка DESC
""").df()
t_wf = time.time() - t_wf
print(f"  Window Functions на {parquet_size:.0f}МБ файле: {t_wf:.2f}с")
print(df_wf.to_string(index=False))

# 5.3 Streaming агрегация через DuckDB
print("\n--- Streaming агрегация через DuckDB ---")
print("""
  DuckDB использует streaming execution по умолчанию:
  - Никогда не загружает весь файл в память
  - Обрабатывает данные частями (morsel-driven parallelism)
  - Автоматически использует несколько CPU ядер
  
  Настройки:
    SET memory_limit = '4GB';     -- лимит RAM
    SET threads = 8;              -- количество потоков
    SET temp_directory = '/tmp';  -- куда спиллить на диск
""")

# Показываем настройки
settings = con.execute("""
    SELECT name, value
    FROM duckdb_settings()
    WHERE name IN ('memory_limit', 'threads', 'temp_directory')
""").df()
print("  Текущие настройки DuckDB:")
print(settings.to_string(index=False))


# ========================================
# ЧАСТЬ 6: СРАВНЕНИЕ ПОДХОДОВ
# ========================================

print("\n" + "=" * 70)
print("6  ЧАСТЬ 6: Итоговое сравнение подходов")
print("=" * 70)

approaches = [
    ("pd.read_csv(весь файл)", t_full, "Вся RAM сразу",   "🔴"),
    ("Pandas chunking",        t_chunk, "Мало RAM",        "🟡"),
    ("DuckDB + CSV",           t_duck_csv, "Минимум RAM",  "🟢"),
    ("DuckDB + Parquet",       t_pq,    "Минимум RAM",     "🟢"),
]

print(f"\n{'Подход':<30} {'Время':>8}  {'Память':<15} {'Рейтинг'}")
print("-" * 65)
for name, t, mem, rating in approaches:
    print(f"  {name:<28} {t:>6.1f}с  {mem:<15} {rating}")

print(f"""
Вывод:
  DuckDB + Parquet — лучший выбор для больших файлов:
    • В {t_chunk/t_pq:.0f}x быстрее chunked pandas
    • Файл в {csv_size_mb/parquet_size:.1f}x меньше CSV
    • Работает с файлами больше RAM
    • Полный SQL включая Window Functions, JOIN
""")


# ========================================
# ЧАСТЬ 7: ВИЗУАЛИЗАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("7  ЧАСТЬ 7: Визуализация")
print("=" * 70)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('День 37: Большие файлы — Chunking vs DuckDB Out-of-Core',
             fontsize=13, fontweight='bold')

# 1. Сравнение скоростей
ax1 = axes[0, 0]
methods = ['Pandas\nвесь файл', 'Pandas\nchunking', 'DuckDB\nCSV', 'DuckDB\nParquet']
times_list = [t_full, t_chunk, t_duck_csv, t_pq]
colors1 = ['#e74c3c', '#f39c12', '#3498db', '#2ecc71']
bars1 = ax1.bar(methods, times_list, color=colors1, alpha=0.85)
for bar, val in zip(bars1, times_list):
    ax1.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.02,
             f'{val:.1f}с', ha='center', va='bottom',
             fontsize=10, fontweight='bold')
ax1.set_title('Скорость обработки 3М строк', fontweight='bold')
ax1.set_ylabel('Время (с)')
ax1.grid(axis='y', alpha=0.3)

# 2. Размер файлов
ax2 = axes[0, 1]
formats = ['CSV\n(оригинал)', 'Parquet\n(snappy)']
sizes = [csv_size_mb, parquet_size]
colors2 = ['#e74c3c', '#2ecc71']
bars2 = ax2.bar(formats, sizes, color=colors2, alpha=0.85, width=0.4)
for bar, val in zip(bars2, sizes):
    ax2.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
             f'{val:.0f} МБ', ha='center', va='bottom',
             fontsize=12, fontweight='bold')
ax2.set_title(f'Размер файла (3М строк)\nParquet в {csv_size_mb/parquet_size:.1f}x меньше',
              fontweight='bold')
ax2.set_ylabel('Размер (МБ)')
ax2.grid(axis='y', alpha=0.3)

# 3. Топ-10 город × категория (из DuckDB анализа)
ax3 = axes[1, 0]
top10 = df_wf.head(10)
colors3 = plt.cm.RdYlGn(np.linspace(0.8, 0.2, len(top10)))
ax3.barh(
    [f"{r['city']} / {r['category']}" for _, r in top10.iterrows()],
    top10['выручка'] / 1_000_000,
    color=colors3
)
ax3.set_title('Топ-10: Город × Категория по выручке', fontweight='bold')
ax3.set_xlabel('Выручка (млн ₽)')
ax3.grid(axis='x', alpha=0.3)

# 4. Схема работы chunking vs DuckDB
ax4 = axes[1, 1]
ax4.axis('off')
ax4.text(0.5, 0.95, 'Когда что использовать',
         transform=ax4.transAxes, ha='center', va='top',
         fontsize=12, fontweight='bold')

guide = [
    ('🔴 Pandas весь файл', '< 500К строк, прототип'),
    ('🟡 Pandas chunking',  'Нет DuckDB, простая агрег.'),
    ('🟢 DuckDB + CSV',     'Быстрый старт, нет конверт.'),
    ('🟢 DuckDB + Parquet', 'PRODUCTION — всегда'),
    ('🔵 Polars lazy',      '> 5М строк, Python pipeline'),
    ('🔵 Dask',             'Кластер, распределённые данные'),
]
for i, (tool, when) in enumerate(guide):
    y = 0.80 - i * 0.13
    ax4.text(0.05, y, tool,  transform=ax4.transAxes,
             va='center', fontsize=10, fontweight='bold')
    ax4.text(0.05, y-0.05, f'  → {when}', transform=ax4.transAxes,
             va='center', fontsize=9, color='#555')

plt.tight_layout()
plt.savefig('reports/day37_large_files.png', dpi=150, bbox_inches='tight')
plt.close()
print("График сохранён: reports/day37_large_files.png")

con.close()

print("\n" + "=" * 70)
print("ДЕНЬ 37 ЗАВЕРШЁН!")
print("=" * 70)
print(f"""
Работа с большими файлами:

1. Pandas chunking
   for chunk in pd.read_csv(file, chunksize=200_000):
       агрегируем результат чанка
   Когда: нет DuckDB, простые агрегации

2. DuckDB out-of-core
   SELECT ... FROM read_csv_auto('file.csv') WHERE ...
   SELECT ... FROM read_parquet('file.parquet') WHERE ...
   Когда: ВСЕГДА предпочтительнее chunking

3. DuckDB + Parquet = лучший выбор
   • {csv_size_mb/parquet_size:.1f}x сжатие vs CSV
   • {t_chunk/t_pq:.0f}x быстрее chunked pandas
   • Полный SQL: Window Functions, JOIN, QUALIFY

4. Glob — читаем несколько файлов
   read_parquet('data/city_*.parquet')

5. DuckDB настройки
   SET memory_limit = '4GB'
   SET threads = 8

Данные: data/large/
Графики: reports/day37_large_files.png

Следующий день: День 38 — dbt advanced models
""")