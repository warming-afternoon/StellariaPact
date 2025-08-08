# 使用官方的 Python 运行时作为父镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装 uv，一个更快的 Python 包安装器
RUN pip install uv

# 复制依赖定义文件
COPY pyproject.toml uv.lock ./
COPY README.md LICENSE ./

# 将项目源代码复制到工作目录中
# 我们只复制 src 目录，因为这是应用代码所在的位置
COPY src/ ./src/

# 使用 uv 安装项目依赖
# --system 表示将依赖安装到全局环境中
# --no-cache 避免缓存，减小镜像体积
RUN uv pip install --system --no-cache .

# 设置容器启动时执行的命令
# 这会执行 src/StellariaPact/__main__.py
CMD ["python", "-m", "StellariaPact"]