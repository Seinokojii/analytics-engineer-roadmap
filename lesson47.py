# lesson47.py — День 47: GitHub Actions CI/CD для dbt
# Запуск: python lesson47.py

import os, textwrap

print("=" * 70)
print("ДЕНЬ 47: GitHub Actions CI/CD для dbt")
print("=" * 70)

# ── Создаём структуру папок ───────────────────────────────────────────────
os.makedirs(".github/workflows", exist_ok=True)
print("✅ .github/workflows/ создана")

# ══════════════════════════════════════════════════════════════════════
# CI WORKFLOW — запускается на каждый Pull Request
# ══════════════════════════════════════════════════════════════════════

ci_workflow = textwrap.dedent("""\
    name: dbt CI

    # Запускается на каждый PR в main или dev
    on:
      pull_request:
        branches: [main, dev]
        paths:
          - 'dbt_analytics/**'
          - '.github/workflows/dbt_ci.yml'

    jobs:
      dbt-ci:
        name: dbt build + test
        runs-on: ubuntu-latest

        steps:
          # 1. Checkout кода
          - name: Checkout
            uses: actions/checkout@v4

          # 2. Python
          - name: Setup Python
            uses: actions/setup-python@v5
            with:
              python-version: '3.12'

          # 3. Кэш pip зависимостей
          - name: Cache pip
            uses: actions/cache@v4
            with:
              path: ~/.cache/pip
              key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}

          # 4. Установка dbt-duckdb
          - name: Install dbt
            run: |
              pip install dbt-duckdb great-expectations pytest --quiet

          # 5. dbt deps — установка пакетов
          - name: dbt deps
            working-directory: dbt_analytics
            run: dbt deps

          # 6. dbt build — запуск моделей + тестов вместе
          - name: dbt build
            working-directory: dbt_analytics
            run: |
              dbt build --target ci
            env:
              DBT_ENV: ci

          # 7. dbt snapshot — проверяем что snapshots компилируются
          - name: dbt snapshot (dry-run compile)
            working-directory: dbt_analytics
            run: dbt compile --select snapshot:*

          # 8. Загружаем артефакты для дебага при падении
          - name: Upload dbt logs
            if: failure()
            uses: actions/upload-artifact@v4
            with:
              name: dbt-logs
              path: dbt_analytics/logs/
""")

# ══════════════════════════════════════════════════════════════════════
# CD WORKFLOW — деплой в prod при merge в main
# ══════════════════════════════════════════════════════════════════════

cd_workflow = textwrap.dedent("""\
    name: dbt CD (deploy to prod)

    # Запускается при push/merge в main
    on:
      push:
        branches: [main]
        paths:
          - 'dbt_analytics/**'

    jobs:
      dbt-deploy:
        name: dbt deploy prod
        runs-on: ubuntu-latest

        steps:
          - name: Checkout
            uses: actions/checkout@v4

          - name: Setup Python
            uses: actions/setup-python@v5
            with:
              python-version: '3.12'

          - name: Cache pip
            uses: actions/cache@v4
            with:
              path: ~/.cache/pip
              key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}

          - name: Install dbt
            run: pip install dbt-duckdb --quiet

          - name: dbt deps
            working-directory: dbt_analytics
            run: dbt deps

          # Full build в prod таргете
          - name: dbt build (prod)
            working-directory: dbt_analytics
            run: |
              dbt build --target prod --full-refresh
            env:
              DBT_ENV: prod

          # Snapshots в проде
          - name: dbt snapshot (prod)
            working-directory: dbt_analytics
            run: dbt snapshot --target prod
            env:
              DBT_ENV: prod

          # Генерация и публикация документации
          - name: dbt docs generate
            working-directory: dbt_analytics
            run: dbt docs generate --target prod

          # Публикуем docs как GitHub Pages артефакт
          - name: Upload docs
            uses: actions/upload-artifact@v4
            with:
              name: dbt-docs
              path: dbt_analytics/target/
              retention-days: 30

          # Уведомление об успехе (опционально — Slack webhook)
          - name: Notify success
            if: success()
            run: echo "✅ dbt prod deploy completed successfully"

          - name: Notify failure
            if: failure()
            run: |
              echo "❌ dbt prod deploy FAILED"
              exit 1
""")

# ══════════════════════════════════════════════════════════════════════
# profiles.yml — таргеты dev/ci/prod
# ══════════════════════════════════════════════════════════════════════

# Для dbt-duckdb profiles.yml хранится в ~/.dbt/
# Создаём локальный вариант с комментарием
profiles_yml = textwrap.dedent("""\
    # ~/.dbt/profiles.yml
    # Этот файл НЕ коммитится в git (добавь в .gitignore)
    # Содержит конфигурацию подключений для разных окружений

    analytics_project:
      target: dev

      outputs:
        # Локальная разработка
        dev:
          type: duckdb
          path: analytics.duckdb
          threads: 4

        # CI окружение (GitHub Actions)
        ci:
          type: duckdb
          path: /tmp/analytics_ci.duckdb
          threads: 2

        # Production (в реальности — BigQuery/Snowflake/DuckDB в S3)
        prod:
          type: duckdb
          path: analytics_prod.duckdb
          threads: 4
          schema: prod
""")

# ══════════════════════════════════════════════════════════════════════
# requirements.txt
# ══════════════════════════════════════════════════════════════════════

requirements_txt = textwrap.dedent("""\
    dbt-duckdb>=1.8.0,<2.0.0
    great-expectations>=1.0.0,<2.0.0
    pytest>=7.0.0
    pytest-cov>=4.0.0
    pandas>=2.0.0
""")

# ══════════════════════════════════════════════════════════════════════
# .gitignore — что не коммитим
# ══════════════════════════════════════════════════════════════════════

gitignore_additions = textwrap.dedent("""\

    # dbt
    dbt_analytics/target/
    dbt_analytics/logs/
    dbt_analytics/*.duckdb
    dbt_analytics/dbt_packages/

    # Python
    .venv/
    venv312/
    __pycache__/
    *.pyc

    # Data
    data/large/
    *.parquet
    reports/

    # Секреты
    .env
    profiles.yml
""")

# ── Запись файлов ─────────────────────────────────────────────────────────
files = {
    ".github/workflows/dbt_ci.yml":  ci_workflow,
    ".github/workflows/dbt_cd.yml":  cd_workflow,
    "requirements.txt":              requirements_txt,
}

print("\n📝 Создание файлов:")
for rel_path, content in files.items():
    dir_name = os.path.dirname(rel_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(rel_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ {rel_path}")

# profiles.yml — показываем, но не записываем (секретный файл)
print(f"\n📋 profiles.yml (НЕ коммити — добавь в .gitignore):")
print(profiles_yml)

# .gitignore — дополняем существующий
gitignore_path = ".gitignore"
existing = ""
if os.path.exists(gitignore_path):
    with open(gitignore_path, "r", encoding="utf-8") as f:
        existing = f.read()

if "dbt_analytics/target" not in existing:
    with open(gitignore_path, "a", encoding="utf-8") as f:
        f.write(gitignore_additions)
    print("✅ .gitignore обновлён")
else:
    print("✅ .gitignore уже содержит нужные записи")

print("""
📋 ШПАРГАЛКА GitHub Actions:

  Структура:
    .github/workflows/dbt_ci.yml   ← триггер: pull_request
    .github/workflows/dbt_cd.yml   ← триггер: push в main

  Ключевые команды в workflow:
    dbt deps                        # установить пакеты
    dbt build --target ci           # run + test вместе
    dbt build --target prod --full-refresh  # полный пересчёт
    dbt snapshot --target prod      # snapshots в проде

  Таргеты (profiles.yml):
    dev   → локальная разработка
    ci    → GitHub Actions (временная БД)
    prod  → продакшн

  Посмотреть статус Actions:
    https://github.com/Seinokojii/analytics-engineer-roadmap/actions
""")

print("\n✅ День 47 завершён!")
print("🔧 Следующий шаг: запушь изменения и открой PR — Actions запустится автоматически")
print("""
Команды:
    git add .github/ requirements.txt .gitignore
    git commit -m "feat: day 47 GitHub Actions CI/CD dbt"
    git push
""")