FROM python:3.12.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Chromium for Playwright PDF export (painting M3, #320). --with-deps pulls the
# system libraries headless Chromium needs on the slim base image.
RUN playwright install --with-deps chromium

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
