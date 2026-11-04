FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=babybuddy.settings.base

WORKDIR /app

RUN groupadd --system babytap \
    && useradd --system --gid babytap --home-dir /app babytap

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY --chown=babytap:babytap . .
RUN chmod +x scripts/start.sh \
    && mkdir -p data media static \
    && chown -R babytap:babytap data media static

USER babytap
EXPOSE 8000

CMD ["./scripts/start.sh"]

