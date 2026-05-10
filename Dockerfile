# Stage 1: build deps
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: runtime
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /install /usr/local
COPY *.py config.yaml favicon.svg ./
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

# Stage 3: test runner
FROM runtime AS test
COPY pytest.ini ./
COPY tests/ ./tests/
CMD ["python", "-m", "pytest", "tests/", "-v"]
