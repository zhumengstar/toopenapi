FROM python:3.11-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive

# 工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt requirements_async.txt ./

# 安装依赖
RUN pip install --no-cache-dir -r requirements_async.txt

# 复制应用代码
COPY server_backup.py ./server_sync.py
COPY async_server.py ./async_server.py

# 创建日志目录
RUN mkdir -p /app/logs /tmp && chmod 755 /app/logs /tmp

# 暴露端口
EXPOSE 8787 8888

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -s http://localhost:${PORT:-8787}/health | grep -q '\"status\"' || exit 1

# 运行命令（可通过环境变量选择同步/异步）
CMD if [ "$USE_ASYNC" = "true" ]; then \
        exec python async_server.py; \
    else \
        exec python server_sync.py; \
    fi
