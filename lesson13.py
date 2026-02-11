"""
День 13: Работа с API
Получение данных из внешних источников
"""

import requests
import pandas as pd
import json
import time
from datetime import datetime

print("=" * 70)
print(" " * 18 + "🌐 ДЕНЬ 13: РАБОТА С API")
print("=" * 70)

# ========================================
# ЧАСТЬ 1: БАЗОВЫЙ GET ЗАПРОС
# ========================================

print("\n" + "=" * 70)
print("📡 ЧАСТЬ 1: Базовый GET запрос (Public API)")
print("=" * 70)

# Используем публичный API (без ключей)
url = "https://jsonplaceholder.typicode.com/posts"

print(f"🌐 Запрос к: {url}")
response = requests.get(url)

print(f"✅ Статус код: {response.status_code}")
print(f"📊 Тип контента: {response.headers['Content-Type']}")

# Парсинг JSON
data = response.json()
print(f"📦 Получено записей: {len(data)}")
print(f"\nПервая запись:")
print(json.dumps(data[0], indent=2, ensure_ascii=False))

# Конвертируем в DataFrame
df = pd.DataFrame(data)
print(f"\n✅ DataFrame создан:")
print(df.head())


# ========================================
# ЧАСТЬ 2: ПАРАМЕТРЫ ЗАПРОСА
# ========================================

print("\n" + "=" * 70)
print("🔍 ЧАСТЬ 2: Параметры запроса (фильтрация)")
print("=" * 70)

# API с параметрами
url_users = "https://jsonplaceholder.typicode.com/users"

# Запрос с фильтром (params)
params = {'id': 1}
response = requests.get(url_users, params=params)
user = response.json()

print(f"👤 Пользователь с id=1:")
print(json.dumps(user[0], indent=2, ensure_ascii=False))


# ========================================
# ЧАСТЬ 3: ОБРАБОТКА ОШИБОК
# ========================================

print("\n" + "=" * 70)
print("⚠️  ЧАСТЬ 3: Обработка ошибок HTTP")
print("=" * 70)

def safe_api_call(url):
    """Безопасный вызов API с обработкой ошибок"""
    try:
        response = requests.get(url, timeout=10)
        
        # Проверка статуса
        if response.status_code == 200:
            print(f"✅ Успех: {response.status_code}")
            return response.json()
        elif response.status_code == 404:
            print(f"❌ Не найдено: {response.status_code}")
            return None
        elif response.status_code == 500:
            print(f"❌ Ошибка сервера: {response.status_code}")
            return None
        else:
            print(f"⚠️  Неожиданный статус: {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        print("❌ Timeout: сервер не ответил")
        return None
    except requests.exceptions.ConnectionError:
        print("❌ Ошибка соединения")
        return None
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None

# Тесты
print("Тест 1: Корректный URL")
data = safe_api_call("https://jsonplaceholder.typicode.com/posts/1")

print("\nТест 2: Несуществующий endpoint")
data = safe_api_call("https://jsonplaceholder.typicode.com/invalid")


# ========================================
# ЧАСТЬ 4: ПАГИНАЦИЯ
# ========================================

print("\n" + "=" * 70)
print("📄 ЧАСТЬ 4: Пагинация (получение больших данных)")
print("=" * 70)

def fetch_all_pages(base_url, max_pages=3):
    """Получить данные со всех страниц"""
    all_data = []
    
    for page in range(1, max_pages + 1):
        print(f"📄 Загрузка страницы {page}...")
        
        # Разные API используют разные параметры:
        # _page (JSONPlaceholder), page (GitHub), offset (другие)
        params = {'_page': page, '_limit': 10}
        response = requests.get(base_url, params=params)
        
        if response.status_code == 200:
            page_data = response.json()
            
            if not page_data:  # Пустая страница = конец
                print("  ℹ️  Страница пустая, останавливаемся")
                break
                
            all_data.extend(page_data)
            print(f"  ✅ Получено {len(page_data)} записей")
            time.sleep(0.5)  # Rate limiting - не ддосим API!
        else:
            print(f"  ❌ Ошибка: {response.status_code}")
            break
    
    return all_data

# Получаем 3 страницы
url_posts = "https://jsonplaceholder.typicode.com/posts"
all_posts = fetch_all_pages(url_posts, max_pages=3)
print(f"\n📦 Всего получено записей: {len(all_posts)}")


# ========================================
# ЧАСТЬ 5: RATE LIMITING
# ========================================

print("\n" + "=" * 70)
print("⏱️ ЧАСТЬ 5: Rate Limiting (ограничение частоты)")
print("=" * 70)

def rate_limited_requests(urls, requests_per_second=2):
    """Запросы с ограничением частоты"""
    results = []
    delay = 1.0 / requests_per_second
    
    for i, url in enumerate(urls, 1):
        print(f"📡 Запрос {i}/{len(urls)}: {url}")
        
        start = time.time()
        response = requests.get(url)
        
        if response.status_code == 200:
            results.append(response.json())
            print(f"  ✅ Успех за {time.time() - start:.3f}с")
        
        # Задержка между запросами
        if i < len(urls):
            time.sleep(delay)
            
    return results

# Тест: 5 запросов с лимитом 2 req/sec
test_urls = [
    f"https://jsonplaceholder.typicode.com/posts/{i}" 
    for i in range(1, 6)
]

print(f"⏱️ Лимит: 2 запроса в секунду")
print(f"📊 Ожидаемое время: ~{(len(test_urls)-1)/2:.1f} секунд\n")

start_time = time.time()
results = rate_limited_requests(test_urls, requests_per_second=2)
total_time = time.time() - start_time

print(f"\n⏱️ Фактическое время: {total_time:.2f} секунд")
print(f"📦 Получено результатов: {len(results)}")


# ========================================
# ЧАСТЬ 6: СОХРАНЕНИЕ В CSV/PARQUET
# ========================================

print("\n" + "=" * 70)
print("💾 ЧАСТЬ 6: Сохранение данных API в файлы")
print("=" * 70)

# Получаем данные
url = "https://jsonplaceholder.typicode.com/users"
response = requests.get(url)
users = response.json()

# Конвертируем в DataFrame
df_users = pd.DataFrame(users)

# Развернем вложенные объекты
df_users['city'] = df_users['address'].apply(lambda x: x['city'])
df_users['company_name'] = df_users['company'].apply(lambda x: x['name'])

# Выбираем нужные колонки
df_clean = df_users[['id', 'name', 'email', 'phone', 'city', 'company_name']]

print("✅ Очищенный DataFrame:")
print(df_clean)

# Сохраняем
df_clean.to_csv('api_users.csv', index=False)
df_clean.to_parquet('api_users.parquet', index=False)

print(f"\n💾 Сохранено:")
print(f"  - api_users.csv")
print(f"  - api_users.parquet")


# ========================================
# ПРАКТИЧЕСКАЯ ЗАДАЧА: ETL PIPELINE
# ========================================

print("\n" + "=" * 70)
print("🎯 ПРАКТИЧЕСКАЯ ЗАДАЧА: Полный ETL pipeline")
print("=" * 70)

def etl_pipeline(api_url, output_file):
    """
    ETL Pipeline: Extract → Transform → Load
    """
    print("🔄 ETL Pipeline запущен...")
    
    # EXTRACT: Получаем данные из API
    print("\n1️⃣ EXTRACT: Получение данных из API")
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()  # Вызовет ошибку если status != 200
        raw_data = response.json()
        print(f"  ✅ Получено записей: {len(raw_data)}")
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")
        return False
    
    # TRANSFORM: Очистка и трансформация
    print("\n2️⃣ TRANSFORM: Очистка и трансформация")
    df = pd.DataFrame(raw_data)
    
    # Добавляем метаданные
    df['loaded_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    df['source'] = 'API'
    
    # Валидация (пример)
    initial_rows = len(df)
    df = df.dropna(subset=['id'])  # Удаляем записи без ID
    df = df.drop_duplicates(subset=['id'])  # Дедупликация
    
    print(f"  📊 Было строк: {initial_rows}")
    print(f"  📊 Стало строк: {len(df)}")
    print(f"  ✅ Удалено дубликатов/пустых: {initial_rows - len(df)}")
    
    # LOAD: Сохранение
    print("\n3️⃣ LOAD: Сохранение в файл")
    try:
        df.to_parquet(output_file, index=False)
        print(f"  ✅ Сохранено: {output_file}")
        print(f"  📊 Размер файла: {len(df)} строк × {len(df.columns)} колонок")
        return True
    except Exception as e:
        print(f"  ❌ Ошибка сохранения: {e}")
        return False

# Запускаем ETL
success = etl_pipeline(
    api_url="https://jsonplaceholder.typicode.com/comments",
    output_file="api_comments_etl.parquet"
)

if success:
    # Проверяем результат
    loaded_df = pd.read_parquet("api_comments_etl.parquet")
    print(f"\n✅ ETL Pipeline завершен успешно!")
    print(f"\nПервые 3 записи:")
    print(loaded_df.head(3))


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 13 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил работу с API:
1. ✅ Базовые GET запросы (requests.get)
2. ✅ Параметры и фильтрация (params)
3. ✅ Обработка ошибок (try/except, status codes)
4. ✅ Пагинация для больших данных
5. ✅ Rate limiting - уважение к серверу
6. ✅ Сохранение в CSV/Parquet
7. ✅ Полный ETL pipeline: Extract → Transform → Load

Это основа для получения данных в production!
Следующий шаг: День 14 - Checkpoint Недели 2
""")

# Очистка
import os
for f in ['api_users.csv', 'api_users.parquet', 'api_comments_etl.parquet']:
    if os.path.exists(f):
        os.remove(f)
print("\n🗑️ Тестовые файлы удалены")