FROM node:22-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS runtime

WORKDIR /app

# 复制依赖文件
COPY requirements-production.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements-production.txt

COPY . .
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

RUN mkdir -p logs

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}"]
