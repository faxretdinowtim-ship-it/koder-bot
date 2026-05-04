# Используем официальный образ Python 3.11
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл с зависимостями и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код бота
COPY app.py .

# Открываем порт, который использует приложение
EXPOSE 10000

# Команда для запуска бота
CMD ["python", "app.py"]
