FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Папка для хранения SQLite базы данных (будет примонтирована как volume)
RUN mkdir -p /data

CMD ["python3", "main.py"]
