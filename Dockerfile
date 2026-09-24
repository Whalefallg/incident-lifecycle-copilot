FROM python:3.11-slim

WORKDIR /app

# 复制依赖文件
COPY requirements-production.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements-production.txt

# 复制应用代码
COPY . .

# 创建日志目录
RUN mkdir -p logs

# 暴露端口
EXPOSE 8000

# 默认命令
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}"]
