FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir flask gunicorn

COPY db/ db/
COPY models/ models/
COPY webhook/ webhook/

ENV PYTHONPATH=/app
ENV PORT=8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "webhook.main:app"]
