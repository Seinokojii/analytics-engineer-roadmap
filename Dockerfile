# Dockerfile - Days 86-88
# Vosproizvodimost: odna komanda i u lyubogo cheloveka tot zhe stek.
# Multi-stage: builder stavit zavisimosti, runtime ostayotsya tonkim.

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

# git nuzhen dbt deps: pakety tyanutsya iz GitHub
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DAGSTER_HOME=/app/dagster_home \
    DBT_PROFILES_DIR=/app/.github/ci_profiles

WORKDIR /app

# Snachala manifesty zavisimostey - sloy keshiruetsya i ne
# peresobiraetsya pri pravke modeley.
COPY dbt_analytics/packages.yml dbt_analytics/dbt_project.yml ./dbt_analytics/
RUN cd dbt_analytics && dbt deps || true

COPY . .

RUN useradd --create-home --uid 1000 analytics \
 && mkdir -p /app/dagster_home \
 && chown -R analytics:analytics /app
USER analytics

EXPOSE 3000

CMD ["dagster", "dev", "-m", "definitions", "-h", "0.0.0.0", "-p", "3000"]
