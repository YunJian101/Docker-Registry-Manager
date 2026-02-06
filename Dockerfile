FROM python:3.9-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 创建应用目录
WORKDIR /app

# 复制依赖文件和代码
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 创建配置和数据目录（确保容器启动时能自动创建Mirror.json）
RUN mkdir -p /app/config && chmod 777 /app/config && \
    mkdir -p /app/data && chmod 777 /app/data

# 暴露端口
EXPOSE 5001

# 启动应用 - 使用新的入口文件
CMD ["python", "-m", "backend.run"]