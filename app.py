import os
import re
import json
import logging
import time
import subprocess
import tempfile
from threading import Thread
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import requests

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Хранилище кода пользователей
user_sessions = {}
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==================== ФУНКЦИИ TELEGRAM ====================
def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        requests.post(f"{API_URL}/sendMessage", json=data, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def send_file(chat_id, filename, caption=""):
    try:
        with open(filename, "rb") as f:
            requests.post(f"{API_URL}/sendDocument", data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=30)
    except Exception as e:
        logger.error(f"Ошибка: {e}")

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        return requests.get(f"{API_URL}/getUpdates", params=params, timeout=35).json().get("result", [])
    except:
        return []

# ==================== AI ФУНКЦИЯ =================
