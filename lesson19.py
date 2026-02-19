"""
День 19: Automation & Orchestration
Автоматизация ETL, scheduling, мониторинг
"""

import schedule
import time
import subprocess
import logging
from datetime import datetime
from pathlib import Path
import json

print("=" * 70)
print(" " * 10 + "🤖 ДЕНЬ 19: AUTOMATION & ORCHESTRATION")
print("=" * 70)

# ========================================
# ЧАСТЬ 1: LOGGING
# ========================================

print("\n" + "=" * 70)
print("📝 ЧАСТЬ 1: Logging (логирование процессов)")
print("=" * 70)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('etl_pipeline.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("ETL Pipeline Started")
logger.info("=" * 50)

print("✅ Логирование настроено")
print("  - Файл: etl_pipeline.log")
print("  - Уровень: INFO")


# ========================================
# ЧАСТЬ 2: ETL RUNNER
# ========================================

print("\n" + "=" * 70)
print("🚀 ЧАСТЬ 2: ETL Runner (запуск dbt)")
print("=" * 70)

class DBTRunner:
    """Класс для запуска dbt команд"""
    
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def run_command(self, command):
        """Запускает dbt команду"""
        self.logger.info(f"Running: {command}")
        
        try:
            result = subprocess.run(
                command,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                shell=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"✅ Success: {command}")
                self.logger.debug(result.stdout)
                return True
            else:
                self.logger.error(f"❌ Failed: {command}")
                self.logger.error(result.stderr)
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Exception: {e}")
            return False
    
    def run_full_refresh(self):
        """Полный refresh всех моделей"""
        self.logger.info("=" * 50)
        self.logger.info("Starting FULL REFRESH")
        self.logger.info("=" * 50)
        
        steps = [
            "dbt seed",
            "dbt run --full-refresh",
            "dbt test"
        ]
        
        for step in steps:
            if not self.run_command(step):
                self.logger.error("Pipeline failed, stopping")
                return False
        
        self.logger.info("=" * 50)
        self.logger.info("FULL REFRESH completed successfully")
        self.logger.info("=" * 50)
        return True
    
    def run_incremental(self):
        """Инкрементальное обновление"""
        self.logger.info("=" * 50)
        self.logger.info("Starting INCREMENTAL RUN")
        self.logger.info("=" * 50)
        
        steps = [
            "dbt run --models +fct_orders_incremental",
            "dbt test --models fct_orders_incremental"
        ]
        
        for step in steps:
            if not self.run_command(step):
                self.logger.error("Incremental update failed")
                return False
        
        self.logger.info("INCREMENTAL RUN completed")
        return True

# Пример использования
if Path('dbt_analytics').exists():
    runner = DBTRunner('dbt_analytics')
    print("✅ DBTRunner создан")
    print("  - project_dir: dbt_analytics")
    print("""
    Использование:
    runner.run_full_refresh()  # Полное обновление
    runner.run_incremental()   # Инкрементальное
    """)
else:
    print("⚠️  dbt_analytics не найден, пропускаем")


# ========================================
# ЧАСТЬ 3: SCHEDULER (РАСПИСАНИЕ)
# ========================================

print("\n" + "=" * 70)
print("⏰ ЧАСТЬ 3: Scheduling (расписание запусков)")
print("=" * 70)

def daily_full_refresh():
    """Задача: ежедневный full refresh"""
    logger.info("🔄 Запуск ежедневного full refresh")
    
    if Path('dbt_analytics').exists():
        runner = DBTRunner('dbt_analytics')
        success = runner.run_full_refresh()
        
        if success:
            logger.info("✅ Daily job completed")
        else:
            logger.error("❌ Daily job failed")
    else:
        logger.warning("dbt_analytics не найден")

def hourly_incremental():
    """Задача: каждый час incremental"""
    logger.info("🔄 Запуск hourly incremental")
    
    if Path('dbt_analytics').exists():
        runner = DBTRunner('dbt_analytics')
        runner.run_incremental()

# Настройка расписания
schedule.every().day.at("02:00").do(daily_full_refresh)
schedule.every().hour.do(hourly_incremental)

print("✅ Расписание настроено:")
print("  - Full refresh: каждый день в 02:00")
print("  - Incremental: каждый час")

print("""
💡 Для запуска scheduler в production:
while True:
    schedule.run_pending()
    time.sleep(60)  # Проверка каждую минуту
""")


# ========================================
# ЧАСТЬ 4: MONITORING (МОНИТОРИНГ)
# ========================================

print("\n" + "=" * 70)
print("📊 ЧАСТЬ 4: Monitoring & Alerts")
print("=" * 70)

class PipelineMonitor:
    """Мониторинг ETL процессов"""
    
    def __init__(self):
        self.runs = []
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def log_run(self, job_name, status, duration):
        """Логирует запуск job"""
        run_info = {
            'job_name': job_name,
            'status': status,
            'duration': duration,
            'timestamp': datetime.now()
        }
        self.runs.append(run_info)
        
        self.logger.info(f"Job: {job_name} | Status: {status} | Duration: {duration}s")
    
    def get_stats(self):
        """Статистика по запускам"""
        if not self.runs:
            return "No runs yet"
        
        total = len(self.runs)
        success = sum(1 for r in self.runs if r['status'] == 'success')
        failed = total - success
        
        return f"""
        📊 Pipeline Stats:
        - Total runs: {total}
        - Success: {success} ({success/total*100:.1f}%)
        - Failed: {failed}
        - Last run: {self.runs[-1]['timestamp']}
        """
    
    def send_alert(self, message):
        """Отправка алерта (упрощенная версия)"""
        self.logger.warning(f"🚨 ALERT: {message}")

monitor = PipelineMonitor()
print("✅ Monitor создан")

# Пример логирования
monitor.log_run('daily_refresh', 'success', 45.2)
monitor.log_run('hourly_incremental', 'success', 5.1)
monitor.log_run('daily_refresh', 'failed', 12.3)

print(monitor.get_stats())


# ========================================
# ЧАСТЬ 5: AIRFLOW BASICS (КОНЦЕПТ)
# ========================================

print("\n" + "=" * 70)
print("🌪️ ЧАСТЬ 5: Airflow Basics (концепция)")
print("=" * 70)

airflow_dag_example = """
# airflow_dags/analytics_dag.py
from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'analytics_team',
    'depends_on_past': False,
    'email': ['alerts@company.com'],
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'analytics_etl_daily',
    default_args=default_args,
    description='Daily analytics ETL',
    schedule_interval='0 2 * * *',  # Каждый день в 02:00
    start_date=datetime(2024, 1, 1),
    catchup=False,
)

# Задача 1: dbt seed
seed_task = BashOperator(
    task_id='dbt_seed',
    bash_command='cd /opt/dbt_analytics && dbt seed',
    dag=dag,
)

# Задача 2: dbt run
run_task = BashOperator(
    task_id='dbt_run',
    bash_command='cd /opt/dbt_analytics && dbt run',
    dag=dag,
)

# Задача 3: dbt test
test_task = BashOperator(
    task_id='dbt_test',
    bash_command='cd /opt/dbt_analytics && dbt test',
    dag=dag,
)

# Зависимости (граф выполнения)
seed_task >> run_task >> test_task
"""

print("📝 Пример Airflow DAG:")
print(airflow_dag_example)

print("""
💡 Ключевые концепты Airflow:
- DAG: Граф задач с зависимостями
- Operators: Bash, Python, SQL, Email, Slack...
- Schedule: Cron-выражения для расписания
- Retries: Автоматические повторы при ошибках
- Monitoring: Web UI для отслеживания

В production:
1. Установи Airflow: pip install apache-airflow
2. Создай DAG файл в ~/airflow/dags/
3. Запусти: airflow scheduler
4. Web UI: http://localhost:8080
""")


# ========================================
# ЧАСТЬ 6: ERROR HANDLING
# ========================================

print("\n" + "=" * 70)
print("⚠️ ЧАСТЬ 6: Error Handling & Recovery")
print("=" * 70)

def safe_etl_run(runner, job_type='full'):
    """Безопасный запуск ETL с обработкой ошибок"""
    
    try:
        logger.info(f"Starting {job_type} ETL job")
        start_time = time.time()
        
        if job_type == 'full':
            success = runner.run_full_refresh()
        else:
            success = runner.run_incremental()
        
        duration = time.time() - start_time
        
        if success:
            monitor.log_run(f'{job_type}_etl', 'success', duration)
            logger.info(f"✅ Job completed in {duration:.2f}s")
        else:
            monitor.log_run(f'{job_type}_etl', 'failed', duration)
            monitor.send_alert(f"{job_type} ETL failed!")
            
        return success
        
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        monitor.send_alert(f"Critical error in {job_type} ETL: {e}")
        return False

print("✅ Создана функция safe_etl_run")
print("""
Обработка ошибок:
- try/except для критичных секций
- Логирование всех ошибок
- Алерты при failures
- Retry логика
- Rollback при необходимости
""")


# ========================================
# ЧАСТЬ 7: CONFIG MANAGEMENT
# ========================================

print("\n" + "=" * 70)
print("⚙️ ЧАСТЬ 7: Configuration Management")
print("=" * 70)

# Конфиг для разных окружений
config = {
    "dev": {
        "dbt_project": "dbt_analytics",
        "schedule": {
            "full_refresh": "0 2 * * *",
            "incremental": "0 * * * *"
        },
        "alerts": {
            "email": "dev@company.com",
            "slack": False
        },
        "retries": 1
    },
    "prod": {
        "dbt_project": "dbt_analytics_prod",
        "schedule": {
            "full_refresh": "0 1 * * *",
            "incremental": "*/30 * * * *"
        },
        "alerts": {
            "email": "alerts@company.com",
            "slack": True,
            "pagerduty": True
        },
        "retries": 3
    }
}

# Сохраняем конфиг
with open('etl_config.json', 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2)

print("✅ Создан etl_config.json")
print("""
💡 Best Practices:
- Разные конфиги для dev/staging/prod
- Secrets в .env файлах (не в Git!)
- Переменные окружения для credentials
- Версионирование конфигов
""")


# ========================================
# ИТОГИ
# ========================================

print("\n" + "=" * 70)
print("✅ ДЕНЬ 19 ЗАВЕРШЕН!")
print("=" * 70)
print("""
Ты освоил Automation & Orchestration:
1. ✅ Logging - отслеживание процессов
2. ✅ ETL Runner - автоматизация dbt
3. ✅ Scheduling - расписание запусков
4. ✅ Monitoring - мониторинг и алерты
5. ✅ Airflow - концепция DAG
6. ✅ Error Handling - обработка ошибок
7. ✅ Config Management - управление конфигами

ГОТОВО! ДНИ 17-19 ЗАВЕРШЕНЫ! 🎉

Ты освоил:
- dbt (models, tests, docs, macros)
- Automation (scheduling, monitoring)
- Orchestration (Airflow концепты)

Это уровень MIDDLE Analytics Engineer!

СЛЕДУЮЩИЕ ШАГИ:
1. Запусти dbt проект (cd dbt_analytics && dbt run)
2. Посмотри документацию (dbt docs serve)
3. Настрой scheduler для автоматизации

Или продолжай roadmap → День 20-21 (Checkpoint Week 3)
""")