FROM python:3.11-slim

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY app.py .

# Открываем порт
EXPOSE 5000

# Запускаем бота
CMD ["python", "app.py"]
