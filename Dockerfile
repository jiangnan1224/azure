# 使用官方的轻量级 Python 镜像。
# https://hub.docker.com/_/python
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装 uv
RUN pip install uv

# 复制依赖定义文件
COPY pyproject.toml .

# 安装依赖
RUN uv pip install . --system --no-cache

# 复制剩余的应用代码
COPY . .

# 运行应用的命令
CMD ["python", "main.py"]
