"""
День 27: Python ООП — Рефакторинг ETL в классы
Extractor, Transformer, Loader, Pipeline + Factory + Repository
"""

import pandas as pd
import numpy as np
import duckdb
import logging
from pathlib import Path
from datetime import datetime
from abc import ABC, abstractmethod

print("=" * 70)
print(" " * 5 + "ДЕНЬ 27: PYTHON ООП — РЕФАКТОРИНГ ETL")
print("=" * 70)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('etl_oop.log', encoding='utf-8', mode='w'),
        logging.StreamHandler()
    ]
)


# ========================================
# ЧАСТЬ 1: АБСТРАКТНЫЕ КЛАССЫ
# ========================================

print("\n" + "=" * 70)
print("1  ЧАСТЬ 1: Абстрактные классы (ABC)")
print("=" * 70)

class BaseExtractor(ABC):
    """Абстрактный класс для всех Extractor-ов"""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def extract(self) -> pd.DataFrame:
        """Каждый наследник ОБЯЗАН реализовать этот метод"""
        pass

    def validate(self, df: pd.DataFrame) -> bool:
        """Общая валидация после извлечения"""
        if df is None or len(df) == 0:
            self.logger.warning(f"Пустые данные из {self.source_name}")
            return False
        self.logger.info(f"Извлечено из {self.source_name}: {len(df)} строк")
        return True


class BaseTransformer(ABC):
    """Абстрактный класс для всех Transformer-ов"""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.stats = {}

    @abstractmethod
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        pass

    def log_stats(self, before: int, after: int):
        self.stats['rows_before']  = before
        self.stats['rows_after']   = after
        self.stats['rows_dropped'] = before - after
        self.logger.info(
            f"Transform: {before} -> {after} строк "
            f"(удалено: {before - after})"
        )


class BaseLoader(ABC):
    """Абстрактный класс для всех Loader-ов"""

    def __init__(self, target_name: str):
        self.target_name = target_name
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def load(self, df: pd.DataFrame) -> bool:
        pass


print("Созданы абстрактные классы:")
print("  BaseExtractor   — ABC с методом extract()")
print("  BaseTransformer — ABC с методом transform()")
print("  BaseLoader      — ABC с методом load()")


# ========================================
# ЧАСТЬ 2: КОНКРЕТНЫЕ РЕАЛИЗАЦИИ
# ========================================

print("\n" + "=" * 70)
print("2  ЧАСТЬ 2: Конкретные реализации ETL")
print("=" * 70)

class CSVExtractor(BaseExtractor):
    """Извлекает данные из CSV файлов"""

    def __init__(self, file_path: str):
        super().__init__(source_name=file_path)
        self.file_path = Path(file_path)

    def extract(self) -> pd.DataFrame:
        try:
            df = pd.read_csv(self.file_path)
            self.validate(df)
            return df
        except FileNotFoundError:
            self.logger.error(f"Файл не найден: {self.file_path}")
            return pd.DataFrame()


class GeneratorExtractor(BaseExtractor):
    """Генерирует тестовые данные (для разработки)"""

    def __init__(self, n_rows: int = 1000, seed: int = 42):
        super().__init__(source_name='generator')
        self.n_rows = n_rows
        self.seed   = seed

    def extract(self) -> pd.DataFrame:
        np.random.seed(self.seed)
        df = pd.DataFrame({
            'order_id':    range(1, self.n_rows + 1),
            'customer_id': np.random.randint(1, 201, self.n_rows),
            'product':     np.random.choice(
                ['Ноутбук', 'Телефон', 'Планшет', 'Часы', 'Наушники'],
                self.n_rows
            ),
            'category':    np.random.choice(
                ['Электроника', 'Аксессуары'], self.n_rows, p=[0.6, 0.4]
            ),
            'amount':      np.random.randint(500, 15000, self.n_rows),
            'quantity':    np.random.randint(1, 5, self.n_rows),
            'status':      np.random.choice(
                ['completed', 'cancelled', 'pending'],
                self.n_rows, p=[0.7, 0.15, 0.15]
            ),
            'city':        np.random.choice(
                ['Москва', 'СПб', 'Казань', 'Екб', 'НСК'],
                self.n_rows
            ),
            'order_date':  pd.date_range(
                '2024-01-01', periods=self.n_rows, freq='8h'  # исправлено: 8H -> 8h
            )
        })
        # Добавляем 30 дубликатов намеренно
        dupes = df.sample(30, random_state=1)
        df = pd.concat([df, dupes], ignore_index=True)
        self.validate(df)
        return df


class EcommerceTransformer(BaseTransformer):
    """Очистка и трансформация e-commerce данных"""

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        before = len(df)

        # 1. Дубликаты
        df = df.drop_duplicates(subset=['order_id'])

        # 2. Только completed
        df = df[df['status'] == 'completed'].copy()

        # 3. Вычисляемые поля
        df['total_amount'] = df['amount'] * df['quantity']
        df['order_date']   = pd.to_datetime(df['order_date'])
        df['month']        = df['order_date'].dt.month
        df['quarter']      = df['order_date'].dt.quarter
        df['year']         = df['order_date'].dt.year
        df['day_of_week']  = df['order_date'].dt.day_name()

        # 4. Revenue tier
        conditions = [
            df['total_amount'] < 1000,
            (df['total_amount'] >= 1000) & (df['total_amount'] < 5000),
            (df['total_amount'] >= 5000) & (df['total_amount'] < 20000),
            df['total_amount'] >= 20000
        ]
        df['revenue_tier'] = np.select(
            conditions,
            ['Низкий', 'Средний', 'Высокий', 'VIP'],
            default='Низкий'
        )

        # 5. Оптимизация типов
        for col in ['status', 'city', 'revenue_tier', 'category']:
            if col in df.columns:
                df[col] = df[col].astype('category')

        self.log_stats(before, len(df))
        return df


class DuckDBLoader(BaseLoader):
    """Загружает данные в DuckDB"""

    def __init__(self, db_path: str, table_name: str):
        super().__init__(target_name=table_name)
        self.db_path    = db_path
        self.table_name = table_name

    def load(self, df: pd.DataFrame) -> bool:
        try:
            con = duckdb.connect(self.db_path)
            con.execute(f"""
                CREATE OR REPLACE TABLE {self.table_name} AS
                SELECT * FROM df
            """)
            n = con.execute(
                f"SELECT COUNT(*) FROM {self.table_name}"
            ).fetchone()[0]
            con.close()
            self.logger.info(f"Загружено в {self.table_name}: {n} строк")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка загрузки: {e}")
            return False


class CSVLoader(BaseLoader):
    """Сохраняет данные в CSV"""

    def __init__(self, file_path: str):
        super().__init__(target_name=file_path)
        self.file_path = file_path

    def load(self, df: pd.DataFrame) -> bool:
        try:
            df.to_csv(self.file_path, index=False, encoding='utf-8')
            self.logger.info(f"Сохранено в {self.file_path}: {len(df)} строк")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка сохранения CSV: {e}")
            return False


print("Созданы конкретные классы:")
print("  CSVExtractor         — читает из CSV")
print("  GeneratorExtractor   — генерирует тестовые данные")
print("  EcommerceTransformer — очистка + обогащение")
print("  DuckDBLoader         — загрузка в DuckDB")
print("  CSVLoader            — сохранение в CSV")


# ========================================
# ЧАСТЬ 3: FACTORY PATTERN
# ========================================

print("\n" + "=" * 70)
print("3  ЧАСТЬ 3: Factory Pattern")
print("=" * 70)

class ExtractorFactory:
    """
    Factory: создаёт нужный Extractor по типу.
    Вместо: if type == 'csv': ... elif type == 'db': ...
    """

    _extractors = {
        'csv':       CSVExtractor,
        'generator': GeneratorExtractor,
    }

    @classmethod
    def create(cls, source_type: str, **kwargs) -> BaseExtractor:
        if source_type not in cls._extractors:
            raise ValueError(
                f"Неизвестный тип: {source_type}. "
                f"Доступные: {list(cls._extractors.keys())}"
            )
        return cls._extractors[source_type](**kwargs)

    @classmethod
    def register(cls, name: str, extractor_class):
        """Зарегистрировать новый тип (открытость к расширению)"""
        cls._extractors[name] = extractor_class
        print(f"Зарегистрирован новый extractor: {name}")


class LoaderFactory:
    """Factory для Loader-ов"""

    @staticmethod
    def create(target_type: str, **kwargs) -> BaseLoader:
        loaders = {
            'duckdb': DuckDBLoader,
            'csv':    CSVLoader,
        }
        if target_type not in loaders:
            raise ValueError(f"Неизвестный тип: {target_type}")
        return loaders[target_type](**kwargs)


extractor_gen = ExtractorFactory.create('generator', n_rows=1000)
print("Factory создал объекты:")
print(f"  generator: {type(extractor_gen).__name__}")


# ========================================
# ЧАСТЬ 4: REPOSITORY PATTERN
# ========================================

print("\n" + "=" * 70)
print("4  ЧАСТЬ 4: Repository Pattern")
print("=" * 70)

class OrderRepository:
    """
    Repository: абстракция над базой данных.
    Код не знает где хранится — просто вызывает методы.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.logger  = logging.getLogger(self.__class__.__name__)

    def _connect(self):
        return duckdb.connect(self.db_path)

    def get_all(self) -> pd.DataFrame:
        try:
            con = self._connect()
            df  = con.execute("SELECT * FROM ecommerce_orders").df()
            con.close()
            return df
        except Exception as e:
            self.logger.error(f"get_all ошибка: {e}")
            return pd.DataFrame()

    def get_by_city(self, city: str) -> pd.DataFrame:
        con = self._connect()
        df  = con.execute(
            "SELECT * FROM ecommerce_orders WHERE city = ?", [city]
        ).df()
        con.close()
        return df

    def get_top_customers(self, n: int = 10) -> pd.DataFrame:
        con = self._connect()
        df  = con.execute(f"""
            SELECT
                customer_id,
                COUNT(*)          AS всего_заказов,
                SUM(total_amount) AS сумма_покупок,
                AVG(total_amount) AS средний_чек
            FROM ecommerce_orders
            GROUP BY customer_id
            ORDER BY сумма_покупок DESC
            LIMIT {n}
        """).df()
        con.close()
        return df

    def get_revenue_by_month(self) -> pd.DataFrame:
        con = self._connect()
        df  = con.execute("""
            SELECT
                month             AS месяц,
                COUNT(*)          AS заказов,
                SUM(total_amount) AS выручка
            FROM ecommerce_orders
            GROUP BY month
            ORDER BY month
        """).df()
        con.close()
        return df

    def get_category_stats(self) -> pd.DataFrame:
        con = self._connect()
        df  = con.execute("""
            SELECT
                category          AS категория,
                revenue_tier      AS уровень,
                COUNT(*)          AS заказов,
                SUM(total_amount) AS выручка,
                AVG(total_amount) AS средний_чек
            FROM ecommerce_orders
            GROUP BY category, revenue_tier
            ORDER BY выручка DESC
        """).df()
        con.close()
        return df


print("OrderRepository создан с методами:")
print("  get_all()              — все заказы")
print("  get_by_city(city)      — заказы города")
print("  get_top_customers(n)   — топ-N клиентов")
print("  get_revenue_by_month() — выручка по месяцам")
print("  get_category_stats()   — статистика по категориям")


# ========================================
# ЧАСТЬ 5: PIPELINE — ВСЁ ВМЕСТЕ
# ========================================

print("\n" + "=" * 70)
print("5  ЧАСТЬ 5: Pipeline — запускает весь ETL")
print("=" * 70)

class ETLPipeline:
    """
    Оркестрирует весь ETL:
    Extractor → Transformer → Loader
    """

    def __init__(self,
                 extractor:   BaseExtractor,
                 transformer: BaseTransformer,
                 loaders:     list):
        self.extractor   = extractor
        self.transformer = transformer
        self.loaders     = loaders
        self.logger      = logging.getLogger('ETLPipeline')
        self.run_stats   = {}

    def run(self) -> bool:
        start = datetime.now()
        self.logger.info("=" * 50)
        self.logger.info("ETL Pipeline ЗАПУЩЕН")
        self.logger.info("=" * 50)

        try:
            # EXTRACT
            self.logger.info("ШАГ 1: Extract")
            raw_df = self.extractor.extract()
            if raw_df.empty:
                self.logger.error("Extract вернул пустые данные")
                return False
            self.run_stats['rows_extracted'] = len(raw_df)

            # TRANSFORM
            self.logger.info("ШАГ 2: Transform")
            clean_df = self.transformer.transform(raw_df)
            self.run_stats['rows_transformed'] = len(clean_df)
            self.run_stats.update(self.transformer.stats)

            # LOAD
            self.logger.info("ШАГ 3: Load")
            for loader in self.loaders:
                success = loader.load(clean_df)
                if not success:
                    self.logger.error(
                        f"Loader {type(loader).__name__} упал"
                    )
                    return False

            duration = (datetime.now() - start).total_seconds()
            self.run_stats['duration_sec'] = round(duration, 2)
            self.run_stats['status']       = 'success'

            self.logger.info("=" * 50)
            self.logger.info(f"ETL Pipeline ЗАВЕРШЁН за {duration:.2f}с")
            self.logger.info(f"Статистика: {self.run_stats}")
            self.logger.info("=" * 50)
            return True

        except Exception as e:
            self.logger.error(f"Pipeline УПАЛ: {e}")
            self.run_stats['status'] = 'failed'
            self.run_stats['error']  = str(e)
            return False


# ========================================
# ЧАСТЬ 6: ЗАПУСК PIPELINE
# ========================================

print("\n" + "=" * 70)
print("6  ЧАСТЬ 6: Запуск полного ETL Pipeline")
print("=" * 70)

Path('data/oop').mkdir(parents=True, exist_ok=True)

pipeline = ETLPipeline(
    extractor=ExtractorFactory.create('generator', n_rows=1000),
    transformer=EcommerceTransformer(),
    loaders=[
        LoaderFactory.create('duckdb',
                             db_path='data/oop/ecommerce.duckdb',
                             table_name='ecommerce_orders'),
        LoaderFactory.create('csv',
                             file_path='data/oop/ecommerce_clean.csv'),
    ]
)

success = pipeline.run()

print(f"\nСтатус пайплайна: {'УСПЕШНО ✓' if success else 'ОШИБКА ✗'}")
print(f"Статистика: {pipeline.run_stats}")

if success:
    repo = OrderRepository('data/oop/ecommerce.duckdb')

    print("\nТоп-5 клиентов по сумме покупок:")
    print(repo.get_top_customers(5).to_string(index=False))

    print("\nВыручка по месяцам:")
    print(repo.get_revenue_by_month().to_string(index=False))

    print("\nСтатистика по категориям:")
    print(repo.get_category_stats().to_string(index=False))


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("ДЕНЬ 27 ЗАВЕРШЁН!")
print("=" * 70)
print("""
Ты создал ООП ETL архитектуру:
1. Абстрактные классы (BaseExtractor, BaseTransformer, BaseLoader)
2. Конкретные реализации (CSV, Generator, Ecommerce, DuckDB)
3. Factory Pattern — создаёт нужный класс по типу
4. Repository Pattern — абстракция над базой данных
5. ETLPipeline — оркестрирует весь процесс

Загрузка: data/oop/ecommerce.duckdb
CSV:      data/oop/ecommerce_clean.csv
Лог:      etl_oop.log

Следующий шаг: Месячный проект — E-Commerce ETL + DW + dbt
""")