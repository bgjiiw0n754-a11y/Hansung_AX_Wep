# Dockerfile
FROM python:3.11-slim

# pyhwp가 필요로 하는 시스템 패키지
RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# revision_backups 디렉토리 생성
RUN mkdir -p revision_backups

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
