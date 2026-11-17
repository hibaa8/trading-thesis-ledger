FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY ledger ./ledger
COPY --from=frontend /app/ledger/web/react ./ledger/web/react
RUN pip install --no-cache-dir . && useradd -m ledger && mkdir /data && chown ledger:ledger /data
USER ledger
ENV LEDGER_DATA_DIR=/data
EXPOSE 8000
CMD ["thesis-ledger", "--host", "0.0.0.0", "--port", "8000"]
