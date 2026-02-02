FROM python:3.10.18-slim

RUN mkdir -p /app/api

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY ./api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt  -i https://mirrors.aliyun.com/pypi/simple && \
    find /usr/local/lib/python3.10/site-packages -type d -name "__pycache__" -exec rm -rf {} +

COPY ./api/database /app/api/database
COPY ./api/models /app/api/models
COPY ./api/services /app/api/services
COPY ./api/routers /app/api/routers
COPY ./api/templates /app/api/templates
COPY ./api/utils /app/api/utils
COPY ./api/init_db.py /app/api/init_db.py
COPY ./api/kag_config.yaml /app/api/kag_config.yaml
COPY ./api/main.py /app/api/main.py

COPY kag /app/kag
COPY knext /app/knext

RUN mkdir -p /app/api/data

WORKDIR /app/api

EXPOSE 9387

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9387"]