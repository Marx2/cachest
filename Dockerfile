# Stage 1: build deps
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: test runner — build explicitly with --target test
FROM python:3.12-slim AS test
WORKDIR /app
COPY --from=builder /install /usr/local
COPY *.py config.yaml favicon.svg ./
COPY pytest.ini ./
COPY tests/ ./tests/
CMD ["python", "-m", "pytest", "tests/", "-v"]

# Stage 3: runtime (default)
FROM python:3.12-slim AS runtime
WORKDIR /app
# APP_VERSION is passed by CI (release tag); falls back to 0.0.0-dev at runtime
ARG APP_VERSION=""
ENV APP_VERSION=${APP_VERSION}
COPY --from=builder /install /usr/local
COPY *.py config.yaml favicon.svg ./
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
