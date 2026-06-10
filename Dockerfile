FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install httpx pymysql --no-cache-dir

COPY src/ mariadb_bottlenect_monitor/

RUN useradd -r monitor
USER monitor

ENV PYTHONPATH=/app

ENTRYPOINT ["python", "-m", "mariadb_bottlenect_monitor"]
