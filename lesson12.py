"""
День 12: NumPy - основы векторных вычислений
Фундамент для pandas, ML, и data science
"""

import numpy as np
import pandas as pd
import time

print("=" * 70)
print(" " * 18 + "🔢 ДЕНЬ 12: NUMPY")
print("=" * 70)

# ========================================
# ЧАСТЬ 1: СОЗДАНИЕ МАССИВОВ
# ========================================

print("\n" + "=" * 70)
print("📊 ЧАСТЬ 1: Создание NumPy массивов")
print("=" * 70)

# Из Python списка
arr1 = np.array([1, 2, 3, 4, 5])
print(f"Из списка: {arr1}")
print(f"Тип: {type(arr1)}, dtype: {arr1.dtype}")

# 2D массив (матрица)
arr2d = np.array([[1, 2, 3],
                  [4, 5, 6],
                  [7, 8, 9]])
print(f"\n2D массив:\n{arr2d}")
print(f"Размерность (shape): {arr2d.shape}")

# Специальные массивы
zeros = np.zeros((3, 4))  # Матрица нулей 3x4
ones = np.ones((2, 3))    # Матрица единиц 2x3
arange = np.arange(0, 20, 2)  # От 0 до 20 с шагом 2
linspace = np.linspace(0, 1, 5)  # 5 чисел от 0 до 1

print(f"\nНули 3x4:\n{zeros}")
print(f"\nArange (0-20, шаг 2): {arange}")
print(f"Linspace (0-1, 5 точек): {linspace}")

# Случайные числа
random_arr = np.random.randint(0, 100, size=10)
print(f"\n10 случайных чисел (0-100): {random_arr}")


# ========================================
# ЧАСТЬ 2: VECTORIZATION VS LOOPS
# ========================================

print("\n" + "=" * 70)
print("⚡ ЧАСТЬ 2: Векторизация vs Циклы")
print("=" * 70)

size = 1_000_000
print(f"📊 Тест на {size:,} элементах\n")

# Создаем данные
py_list = list(range(size))
np_array = np.array(py_list)

# ❌ Python loop
start = time.time()
result_loop = []
for x in py_list:
    result_loop.append(x * 2 + 10)
t_loop = time.time() - start
print(f"❌ Python loop: {t_loop:.4f} сек")

# ⚠️ List comprehension
start = time.time()
result_comp = [x * 2 + 10 for x in py_list]
t_comp = time.time() - start
print(f"⚠️  List comprehension: {t_comp:.4f} сек")

# ✅ NumPy vectorization
start = time.time()
result_numpy = np_array * 2 + 10
t_numpy = time.time() - start
print(f"✅ NumPy векторизация: {t_numpy:.4f} сек")

print(f"\n🚀 Ускорение:")
print(f"  - NumPy vs Loop: {t_loop/t_numpy:.0f}x")
print(f"  - NumPy vs Comprehension: {t_comp/t_numpy:.0f}x")


# ========================================
# ЧАСТЬ 3: BROADCASTING
# ========================================

print("\n" + "=" * 70)
print("📡 ЧАСТЬ 3: Broadcasting (умное распространение)")
print("=" * 70)

# Скаляр + массив
arr = np.array([1, 2, 3, 4, 5])
print(f"Массив: {arr}")
print(f"Массив + 10: {arr + 10}")
print(f"Массив * 2: {arr * 2}")

# Массив + массив (element-wise)
arr2 = np.array([10, 20, 30, 40, 50])
print(f"\nМассив 1: {arr}")
print(f"Массив 2: {arr2}")
print(f"Сумма: {arr + arr2}")
print(f"Умножение: {arr * arr2}")

# Broadcasting 2D
matrix = np.array([[1, 2, 3],
                   [4, 5, 6]])
vector = np.array([10, 20, 30])

print(f"\nМатрица 2x3:\n{matrix}")
print(f"Вектор 1x3: {vector}")
print(f"Матрица + Вектор:\n{matrix + vector}")

print("""
💡 Broadcasting правила:
1. Скаляр применяется ко всем элементам
2. Массивы одинакового размера → element-wise операции
3. Массивы разных размеров → NumPy "растягивает" меньший
""")


# ========================================
# ЧАСТЬ 4: ИНДЕКСИРОВАНИЕ И SLICING
# ========================================

print("\n" + "=" * 70)
print("🎯 ЧАСТЬ 4: Индексирование и срезы")
print("=" * 70)

arr = np.array([10, 20, 30, 40, 50, 60, 70])
print(f"Массив: {arr}")
print(f"arr[0]: {arr[0]}")
print(f"arr[-1]: {arr[-1]} (последний)")
print(f"arr[2:5]: {arr[2:5]} (срез)")
print(f"arr[::2]: {arr[::2]} (каждый 2-й)")

# 2D индексирование
matrix = np.array([[1, 2, 3],
                   [4, 5, 6],
                   [7, 8, 9]])
print(f"\nМатрица:\n{matrix}")
print(f"matrix[0, 0]: {matrix[0, 0]}")
print(f"matrix[1, 2]: {matrix[1, 2]}")
print(f"matrix[:, 1]: {matrix[:, 1]} (весь 2-й столбец)")
print(f"matrix[1, :]: {matrix[1, :]} (вся 2-я строка)")

# Boolean indexing (ВАЖНО для фильтрации!)
arr = np.array([10, 25, 30, 45, 50, 65])
mask = arr > 30
print(f"\nМассив: {arr}")
print(f"Маска (arr > 30): {mask}")
print(f"Фильтрация: {arr[mask]}")


# ========================================
# ЧАСТЬ 5: АГРЕГАЦИИ
# ========================================

print("\n" + "=" * 70)
print("📊 ЧАСТЬ 5: Агрегационные функции")
print("=" * 70)

data = np.random.randint(1, 100, size=20)
print(f"Данные: {data}")
print(f"\nСтатистики:")
print(f"  Сумма: {data.sum()}")
print(f"  Среднее: {data.mean():.2f}")
print(f"  Медиана: {np.median(data):.2f}")
print(f"  Мин: {data.min()}, Макс: {data.max()}")
print(f"  Стандартное отклонение: {data.std():.2f}")
print(f"  Процентили (25%, 50%, 75%): {np.percentile(data, [25, 50, 75])}")

# Агрегация по осям в 2D
matrix = np.random.randint(1, 10, size=(3, 4))
print(f"\nМатрица 3x4:\n{matrix}")
print(f"Сумма всех элементов: {matrix.sum()}")
print(f"Сумма по столбцам (axis=0): {matrix.sum(axis=0)}")
print(f"Сумма по строкам (axis=1): {matrix.sum(axis=1)}")


# ========================================
# ЧАСТЬ 6: NUMPY + PANDAS ИНТЕГРАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("🐼 ЧАСТЬ 6: NumPy + Pandas")
print("=" * 70)

# Pandas использует NumPy под капотом
df = pd.DataFrame({
    'A': [1, 2, 3, 4, 5],
    'B': [10, 20, 30, 40, 50]
})

print("DataFrame:")
print(df)

# Конвертация DataFrame → NumPy
np_array = df.to_numpy()
print(f"\nПреобразован в NumPy array:\n{np_array}")
print(f"Тип: {type(np_array)}")

# NumPy операции на pandas колонках
df['C'] = df['A'].values * df['B'].values  # Векторизация!
df['D'] = np.sqrt(df['A'].values)  # NumPy функции

print(f"\nПосле NumPy операций:")
print(df)


# ========================================
# ПРАКТИЧЕСКАЯ ЗАДАЧА: НОРМАЛИЗАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("🎯 ПРАКТИЧЕСКАЯ ЗАДАЧА: Min-Max нормализация")
print("=" * 70)

# Генерируем данные о продажах
sales = np.random.randint(100, 5000, size=10)
print(f"Продажи: {sales}")

# Min-Max нормализация: (x - min) / (max - min)
# Результат: значения от 0 до 1
normalized = (sales - sales.min()) / (sales.max() - sales.min())
print(f"Нормализованные (0-1): {normalized.round(3)}")

# Z-score нормализация: (x - mean) / std
# Результат: среднее=0, std=1
z_scores = (sales - sales.mean()) / sales.std()
print(f"Z-scores: {z_scores.round(3)}")

print("""
💡 Применение:
- Min-Max: Подготовка данных для нейросетей
- Z-score: Поиск аномалий (|z| > 3 = выброс)

В ML: ВСЕГДА нормализуй данные перед обучением!
""")


# ========================================
# ПРАКТИЧЕСКАЯ ЗАДАЧА: MOVING AVERAGE
# ========================================

print("\n" + "=" * 70)
print("📈 ПРАКТИЧЕСКАЯ ЗАДАЧА: Скользящее среднее (NumPy)")
print("=" * 70)

# Дневные продажи
daily_sales = np.array([1200, 1100, 1300, 1150, 1400, 1250, 1350, 1500, 1450, 1600])
window = 3

print(f"Дневные продажи: {daily_sales}")
print(f"Окно: {window} дней\n")

# Скользящее среднее через np.convolve
moving_avg = np.convolve(daily_sales, np.ones(window)/window, mode='valid')
print(f"Скользящее среднее (3 дня): {moving_avg.round(2)}")

print("""
💡 Как работает:
- День 1-3: (1200+1100+1300)/3 = 1200
- День 2-4: (1100+1300+1150)/3 = 1183.33
- И так далее...

В бизнесе: Сглаживание графиков для трендов
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 12 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил NumPy:
1. ✅ Создание массивов (array, zeros, arange, random)
2. ✅ Векторизация - 50-100x ускорение
3. ✅ Broadcasting - умные операции
4. ✅ Индексирование и boolean masks
5. ✅ Агрегации (sum, mean, percentile)
6. ✅ Интеграция с pandas
7. ✅ Нормализация данных для ML
8. ✅ Скользящие средние

Это фундамент для Data Science и ML!
Следующий шаг: День 13 - Работа с API
""")