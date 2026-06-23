FROM python:3.11-slim

WORKDIR /app

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y tzdata && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scanner.py .
COPY templates/ ./templates/

RUN mkdir -p /app/logs

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5001/health')" || exit 1

CMD ["python", "scanner.py"]