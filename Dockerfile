# Используем официальный образ Python 3.11
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл с зависимостями и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код бота в контейнер
COPY app.py .

# Открываем порт, который будет слушать приложение
EXPOSE 10000

# Команда для запуска бота
CMD ["python", "app.py"]
