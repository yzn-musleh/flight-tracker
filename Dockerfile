# syntax=docker/dockerfile:1

# --- build stage: install dependencies into a user site-packages dir -------
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- runtime stage: copy only what's needed, run as non-root ---------------
FROM python:3.12-slim

RUN groupadd --gid 1000 flighttracker \
    && useradd --uid 1000 --gid flighttracker --create-home --shell /usr/sbin/nologin flighttracker

WORKDIR /app

COPY --from=builder /root/.local /home/flighttracker/.local
COPY --chown=flighttracker:flighttracker . .

ENV PATH=/home/flighttracker/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/flights.db \
    LOCK_PATH=/data/bot.lock

# /data is where docker-compose.yml mounts the named volume for the SQLite
# file and lock file, so both survive a container recreate.
RUN mkdir -p /data && chown flighttracker:flighttracker /data

USER flighttracker

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python healthcheck.py

ENTRYPOINT ["python", "bot.py"]
