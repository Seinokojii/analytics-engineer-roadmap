"""
День 15: Data Quality
Валидация, проверка качества, Great Expectations
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json

print("=" * 70)
print(" " * 15 + "🔍 ДЕНЬ 15: DATA QUALITY")
print("=" * 70)

# ========================================
# ЧАСТЬ 1: ПРОБЛЕМЫ КАЧЕСТВА ДАННЫХ
# ========================================

print("\n" + "=" * 70)
print("⚠️ ЧАСТЬ 1: Типичные проблемы качества данных")
print("=" * 70)

# Создаем "грязные" данные (как в реальности!)
dirty_data = pd.DataFrame({
    'user_id': [1, 2, 3, None, 5, 5, 7, 8],  # Дубликат, пропуск
    'email': ['user1@test.com', 'invalid-email', 'user3@test.com',
              'user4@test.com', '', 'user5@test.com', 
              'user7@test.com', None],  # Невалидный, пустой, null
    'age': [25, -5, 150, 30, 22, 22, 'тридцать', 40],  # Отрицательный, outlier, строка
    'revenue': [1000, 2000, None, 1500, '3000', 2500, 1800, 0],  # Null, строка, zero
    'signup_date': ['2024-01-01', '2024-02-30', '2024-03-15',  # Несуществующая дата
                    '2024-04-01', '2024-05-01', '2024-05-01',
                    '2025-12-31', '2023-06-01'],  # Будущая дата
})

print("📊 Грязные данные:")
print(dirty_data)

# ========================================
# ЧАСТЬ 2: АВТОМАТИЧЕСКОЕ ОБНАРУЖЕНИЕ ПРОБЛЕМ
# ========================================

print("\n" + "=" * 70)
print("🔍 ЧАСТЬ 2: Data Quality Checks")
print("=" * 70)

def data_quality_report(df):
    """Генерирует отчет о качестве данных"""
    report = {
        'total_rows': len(df),
        'total_columns': len(df.columns),
        'issues': []
    }
    
    for col in df.columns:
        col_report = {
            'column': col,
            'dtype': str(df[col].dtype),
            'missing_count': df[col].isna().sum(),
            'missing_pct': (df[col].isna().sum() / len(df) * 100),
            'unique_count': df[col].nunique(),
            'duplicate_count': len(df) - len(df.drop_duplicates(subset=[col]))
        }
        
        # Специфичные проверки по типу
        if df[col].dtype in ['int64', 'float64']:
            col_report['min'] = float(df[col].min()) if not df[col].isna().all() else None
            col_report['max'] = float(df[col].max()) if not df[col].isna().all() else None
            col_report['mean'] = float(df[col].mean()) if not df[col].isna().all() else None
            
            # Outliers (IQR method)
            Q1 = df[col].quantile(0.25)
            Q3 = df[col].quantile(0.75)
            IQR = Q3 - Q1
            outliers = ((df[col] < (Q1 - 1.5 * IQR)) | (df[col] > (Q3 + 1.5 * IQR))).sum()
            col_report['outliers_count'] = int(outliers)
        
        report['issues'].append(col_report)
    
    return report

quality_report = data_quality_report(dirty_data)

print(f"📊 Всего строк: {quality_report['total_rows']}")
print(f"📊 Всего колонок: {quality_report['total_columns']}\n")

for col_info in quality_report['issues']:
    print(f"┌─ {col_info['column']} ({col_info['dtype']}) ─")
    print(f"│  Пропуски: {col_info['missing_count']} ({col_info['missing_pct']:.1f}%)")
    print(f"│  Уникальных: {col_info['unique_count']}")
    print(f"│  Дубликатов: {col_info['duplicate_count']}")
    
    if 'outliers_count' in col_info:
        print(f"│  Выбросов: {col_info['outliers_count']}")
        print(f"│  Min: {col_info['min']}, Max: {col_info['max']}, Mean: {col_info['mean']:.2f}")
    print()

# ========================================
# ЧАСТЬ 3: ПРАВИЛА ВАЛИДАЦИИ
# ========================================

print("\n" + "=" * 70)
print("✅ ЧАСТЬ 3: Правила валидации")
print("=" * 70)

class DataValidator:
    """Класс для валидации данных"""
    
    def __init__(self, df):
        self.df = df
        self.errors = []
    
    def check_not_null(self, column):
        """Проверка на отсутствие null"""
        null_count = self.df[column].isna().sum()
        if null_count > 0:
            self.errors.append(f"❌ {column}: {null_count} null значений")
            return False
        return True
    
    def check_unique(self, column):
        """Проверка на уникальность"""
        duplicates = len(self.df) - len(self.df.drop_duplicates(subset=[column]))
        if duplicates > 0:
            self.errors.append(f"❌ {column}: {duplicates} дубликатов")
            return False
        return True
    
    def check_range(self, column, min_val, max_val):
        """Проверка диапазона значений"""
        out_of_range = ((self.df[column] < min_val) | (self.df[column] > max_val)).sum()
        if out_of_range > 0:
            self.errors.append(f"❌ {column}: {out_of_range} значений вне диапазона [{min_val}, {max_val}]")
            return False
        return True
    
    def check_email_format(self, column):
        """Проверка формата email"""
        invalid = self.df[column].apply(
            lambda x: False if pd.isna(x) or ('@' in str(x) and '.' in str(x)) else True
        ).sum()
        if invalid > 0:
            self.errors.append(f"❌ {column}: {invalid} невалидных email")
            return False
        return True
    
    def check_date_validity(self, column):
        """Проверка валидности дат"""
        try:
            pd.to_datetime(self.df[column], errors='coerce')
            invalid = self.df[column].apply(
                lambda x: pd.to_datetime(x, errors='coerce') is pd.NaT
            ).sum()
            if invalid > 0:
                self.errors.append(f"❌ {column}: {invalid} невалидных дат")
                return False
        except:
            self.errors.append(f"❌ {column}: не удалось конвертировать в дату")
            return False
        return True
    
    def get_report(self):
        """Возвращает отчет о валидации"""
        if len(self.errors) == 0:
            return "✅ Все проверки пройдены!"
        else:
            return "\n".join(self.errors)

# Применяем валидацию
validator = DataValidator(dirty_data)

print("Запускаем проверки...")
validator.check_not_null('user_id')
validator.check_unique('user_id')
validator.check_email_format('email')
# validator.check_range('age', 0, 120)  # Пропускаем, т.к. age имеет строковые значения

print("\n📋 Результат валидации:")
print(validator.get_report())

# ========================================
# ЧАСТЬ 4: ОЧИСТКА ДАННЫХ
# ========================================

print("\n" + "=" * 70)
print("🧹 ЧАСТЬ 4: Автоматическая очистка")
print("=" * 70)

def clean_data(df):
    """Pipeline очистки данных"""
    df_clean = df.copy()
    
    print("1. Удаление дубликатов...")
    before = len(df_clean)
    df_clean = df_clean.drop_duplicates(subset=['user_id'])
    print(f"   Удалено: {before - len(df_clean)} дубликатов")
    
    print("\n2. Обработка пропусков...")
    df_clean = df_clean.dropna(subset=['user_id'])
    print(f"   Удалено строк с null в user_id: {before - len(df_clean)}")
    
    print("\n3. Валидация email...")
    df_clean['email_valid'] = df_clean['email'].apply(
        lambda x: bool(pd.notna(x) and '@' in str(x) and '.' in str(x) and str(x).strip() != '')
    )
    invalid_emails = (~df_clean['email_valid']).sum()
    print(f"   Найдено невалидных: {invalid_emails}")
    
    print("\n4. Очистка age...")
    df_clean['age'] = pd.to_numeric(df_clean['age'], errors='coerce')
    df_clean = df_clean[(df_clean['age'] >= 0) & (df_clean['age'] <= 120)]
    print(f"   Удалено строк с невалидным возрастом")
    
    print("\n5. Конвертация revenue...")
    df_clean['revenue'] = pd.to_numeric(df_clean['revenue'], errors='coerce')
    df_clean['revenue'] = df_clean['revenue'].fillna(0)
    print(f"   Конвертировано в числа")
    
    return df_clean

df_clean = clean_data(dirty_data)

print("\n✅ Очищенные данные:")
print(df_clean)

print(f"\n📊 Было строк: {len(dirty_data)}")
print(f"📊 Стало строк: {len(df_clean)}")
print(f"📊 Удалено: {len(dirty_data) - len(df_clean)} ({(len(dirty_data)-len(df_clean))/len(dirty_data)*100:.1f}%)")

# ========================================
# ЧАСТЬ 5: ПРОФИЛИРОВАНИЕ ДАННЫХ
# ========================================

print("\n" + "=" * 70)
print("📊 ЧАСТЬ 5: Data Profiling")
print("=" * 70)

def profile_dataset(df):
    """Создает профиль датасета"""
    profile = {
        'dataset_name': 'cleaned_data',
        'rows': len(df),
        'columns': len(df.columns),
        'memory_usage_mb': df.memory_usage(deep=True).sum() / 1024**2,
        'column_profiles': {}
    }
    
    for col in df.columns:
        col_profile = {
            'dtype': str(df[col].dtype),
            'missing': int(df[col].isna().sum()),
            'missing_pct': float(df[col].isna().sum() / len(df) * 100),
            'unique': int(df[col].nunique()),
            'unique_pct': float(df[col].nunique() / len(df) * 100),
        }
        
        if df[col].dtype in ['int64', 'float64']:
            col_profile['stats'] = {
                'min': float(df[col].min()),
                'max': float(df[col].max()),
                'mean': float(df[col].mean()),
                'median': float(df[col].median()),
                'std': float(df[col].std())
            }
        
        profile['column_profiles'][col] = col_profile
    
    return profile

profile = profile_dataset(df_clean)

print(f"📊 Dataset: {profile['dataset_name']}")
print(f"📊 Rows: {profile['rows']}, Columns: {profile['columns']}")
print(f"💾 Memory: {profile['memory_usage_mb']:.2f} MB\n")

for col_name, col_profile in profile['column_profiles'].items():
    print(f"• {col_name} ({col_profile['dtype']})")
    print(f"  Missing: {col_profile['missing']} ({col_profile['missing_pct']:.1f}%)")
    print(f"  Unique: {col_profile['unique']} ({col_profile['unique_pct']:.1f}%)")
    
    if 'stats' in col_profile:
        stats = col_profile['stats']
        print(f"  Stats: min={stats['min']}, max={stats['max']}, mean={stats['mean']:.2f}")
    print()

# Сохраняем профиль
with open('data_profile.json', 'w') as f:
    json.dump(profile, f, indent=2)

print("💾 Профиль сохранен: data_profile.json")

# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 15 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил Data Quality:
1. ✅ Обнаружение проблем качества (null, дубликаты, outliers)
2. ✅ Правила валидации (DataValidator класс)
3. ✅ Автоматическая очистка (pipeline)
4. ✅ Data Profiling (статистика по колонкам)
5. ✅ Генерация отчетов о качестве

В production: Это запускается ДО любой аналитики!
Следующий шаг: День 16 - Advanced Pandas
""")