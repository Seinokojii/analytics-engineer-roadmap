# Образ коннектора. Платформа Airbyte запускает именно его:
#   docker run --rm <image> spec
#   docker run --rm -v <dir>:/data <image> read --config /data/config.json --catalog /data/catalog.json
FROM python:3.12-slim

WORKDIR /airbyte/integration_code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY source_open_meteo ./source_open_meteo

ENV AIRBYTE_ENTRYPOINT="python /airbyte/integration_code/main.py"
ENTRYPOINT ["python", "/airbyte/integration_code/main.py"]

LABEL io.airbyte.name=local/source-open-meteo
LABEL io.airbyte.version=0.1.0
