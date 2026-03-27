# 用于在容器环境中运行项目测试的镜像定义。
FROM python:3.12-slim

WORKDIR /app

# 安装测试依赖，保证容器内可稳定执行离线验证。
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝源码与测试文件。
COPY src ./src
COPY test ./test
COPY docker_env_manager.py ./docker_env_manager.py
COPY logging_config.py ./logging_config.py
COPY pytest.ini ./pytest.ini

# 默认直接执行测试套件。
CMD ["pytest", "-q"]
