"""
День 6: Python - основы языка
Современные практики 2026: type hints, comprehensions, clean code
"""

# ========================================
# ЧАСТЬ 1: TYPE HINTS И ФУНКЦИИ
# ========================================

def calculate_discount(price: float, discount_percent: int) -> float:
    """
    Вычисляет цену со скидкой
    
    Args:
        price: Исходная цена
        discount_percent: Процент скидки (0-100)
    
    Returns:
        Цена после скидки
    """
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("Скидка должна быть от 0 до 100")
    
    discount_amount = price * (discount_percent / 100)
    return price - discount_amount


def clean_product_name(name: str) -> str:
    """Очищает название товара от лишних пробелов и приводит к единому формату"""
    return name.strip().title()


def validate_email(email: str) -> bool:
    """Проверяет валидность email (упрощенная версия)"""
    return "@" in email and "." in email.split("@")[1]


print("=" * 60)
print("ЧАСТЬ 1: Функции с type hints")
print("=" * 60)

# Тестируем функции
original_price = 1000.0
discount = 20

final_price = calculate_discount(original_price, discount)
print(f"Цена {original_price}₽ со скидкой {discount}% = {final_price}₽")

# Очистка названий
dirty_names = ["  ноутбук  ", "МЫШЬ", "  КлАвИаТуРа"]
clean_names = [clean_product_name(name) for name in dirty_names]
print(f"\nОчищенные названия: {clean_names}")

# Валидация email
test_emails = ["user@example.com", "invalid.email", "test@domain.co"]
for email in test_emails:
    status = "✅ валидный" if validate_email(email) else "❌ невалидный"
    print(f"{email}: {status}")


# ========================================
# ЧАСТЬ 2: LIST COMPREHENSIONS
# ========================================

print("\n" + "=" * 60)
print("ЧАСТЬ 2: List Comprehensions")
print("=" * 60)

# Задача 1: Квадраты четных чисел
numbers = list(range(1, 11))
even_squares = [n ** 2 for n in numbers if n % 2 == 0]
print(f"Квадраты четных чисел от 1 до 10: {even_squares}")

# Задача 2: Фильтрация дорогих товаров
products = [
    {"name": "Ноутбук", "price": 1200},
    {"name": "Мышь", "price": 25},
    {"name": "Монитор", "price": 350},
    {"name": "Клавиатура", "price": 80}
]

expensive_products = [p["name"] for p in products if p["price"] > 100]
print(f"\nТовары дороже 100₽: {expensive_products}")

# Задача 3: Создание словаря из списков
names = ["Иван", "Мария", "Алексей"]
ages = [25, 30, 28]
users = {name: age for name, age in zip(names, ages)}
print(f"\nСловарь пользователей: {users}")

# Задача 4: Flatten вложенного списка
nested_data = [[1, 2, 3], [4, 5], [6, 7, 8, 9]]
flat_data = [num for sublist in nested_data for num in sublist]
print(f"\nВложенный список: {nested_data}")
print(f"Развернутый список: {flat_data}")


# ========================================
# ЧАСТЬ 3: РАБОТА СО СЛОВАРЯМИ
# ========================================

print("\n" + "=" * 60)
print("ЧАСТЬ 3: Словари и обработка данных")
print("=" * 60)

# Данные о продажах (имитация данных из БД)
sales_data: list[dict[str, str | int]] = [
    {"user_id": 1, "product": "Ноутбук", "amount": 1200},
    {"user_id": 2, "product": "Мышь", "amount": 25},
    {"user_id": 1, "product": "Клавиатура", "amount": 80},
    {"user_id": 3, "product": "Монитор", "amount": 350},
    {"user_id": 2, "product": "Принтер", "amount": 500},
]

# Группировка: сколько потратил каждый пользователь
def calculate_user_totals(sales: list[dict]) -> dict[int, int]:
    """Вычисляет общую сумму покупок для каждого пользователя"""
    totals: dict[int, int] = {}
    
    for sale in sales:
        user_id = sale["user_id"]
        amount = sale["amount"]
        
        if user_id in totals:
            totals[user_id] += amount
        else:
            totals[user_id] = amount
    
    return totals


user_totals = calculate_user_totals(sales_data)
print("Общие покупки по пользователям:")
for user_id, total in user_totals.items():
    print(f"  Пользователь {user_id}: {total}₽")


# ========================================
# ЧАСТЬ 4: ОБРАБОТКА ОШИБОК
# ========================================

print("\n" + "=" * 60)
print("ЧАСТЬ 4: Обработка ошибок")
print("=" * 60)

def safe_divide(a: float, b: float) -> float | None:
    """Безопасное деление с обработкой ошибок"""
    try:
        result = a / b
        return result
    except ZeroDivisionError:
        print(f"⚠️  Ошибка: деление {a} на ноль!")
        return None
    except TypeError:
        print(f"⚠️  Ошибка: неверный тип данных")
        return None


# Тестируем
test_cases = [(10, 2), (10, 0), (10, "2")]
for a, b in test_cases:
    result = safe_divide(a, b)
    if result is not None:
        print(f"✅ {a} / {b} = {result}")


# ========================================
# ЧАСТЬ 5: ПРАКТИЧЕСКАЯ ЗАДАЧА
# ========================================

print("\n" + "=" * 60)
print("ЧАСТЬ 5: Практическая задача - Очистка данных")
print("=" * 60)

# Грязные данные (как из реального API)
dirty_data = [
    {"name": "  iPhone  ", "price": "1000", "stock": "15"},
    {"name": "SAMSUNG", "price": "800", "stock": "20"},
    {"name": "  macbook  ", "price": "2500", "stock": "5"},
    {"name": None, "price": "600", "stock": "10"},  # Ошибка: нет имени
]

def clean_product_data(data: list[dict]) -> list[dict]:
    """
    Очищает данные о товарах:
    - Убирает пробелы из названий
    - Конвертирует строки в числа
    - Пропускает записи с ошибками
    """
    cleaned = []
    
    for item in data:
        try:
            # Проверяем наличие имени
            if item["name"] is None:
                print(f"⚠️  Пропускаем запись без имени: {item}")
                continue
            
            # Очищаем и конвертируем
            clean_item = {
                "name": item["name"].strip().title(),
                "price": int(item["price"]),
                "stock": int(item["stock"])
            }
            cleaned.append(clean_item)
            
        except (ValueError, KeyError, AttributeError) as e:
            print(f"⚠️  Ошибка при обработке {item}: {e}")
            continue
    
    return cleaned


cleaned_products = clean_product_data(dirty_data)
print("\n✅ Очищенные данные:")
for product in cleaned_products:
    print(f"  {product}")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 60)
print("✅ ДЕНЬ 6 ЗАВЕРШЕН!")
print("=" * 60)
print("""
Ты освоил:
1. ✅ Type hints - современный стандарт Python
2. ✅ Функции с документацией (docstrings)
3. ✅ List comprehensions - короткий и читаемый код
4. ✅ Работу со словарями для группировки данных
5. ✅ Обработку ошибок (try/except)
6. ✅ Очистку грязных данных (как в реальном ETL)

Следующий шаг: День 7 - Checkpoint недели 1!
""")