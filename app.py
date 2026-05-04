import os
import re
import json
import logging
import asyncio
import zipfile
from io import BytesIO
from threading import Thread
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from openai import OpenAI

# ==================== КОНФИГУРАЦИЯ ====================
TELEGRAM_TOKEN = "8663335250:AAG022Ubd_a00DTNk-JTx1bo4rhzHgw3myM"
DEEPSEEK_API_KEY = "sk-46f721604f7c475a924c946e31858fb3"
PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096

# AI клиент DeepSeek
ai_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
AI_NAME = "DeepSeek Coder"

user_sessions = {}

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def split_long_text(text: str, chunk_size: int = MAX_MESSAGE_LENGTH) -> list:
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    pos = 0
    while pos < len(text):
        end = pos + chunk_size
        if end >= len(text):
            chunks.append(text[pos:])
            break
        split_at = text.rfind('\n', pos, end)
        if split_at == -1:
            split_at = text.rfind(' ', pos, end)
        if split_at == -1 or split_at <= pos:
            split_at = end
        chunks.append(text[pos:split_at])
        pos = split_at
        while pos < len(text) and text[pos] in ' \n':
            pos += 1
    return chunks

async def send_long_message(bot, chat_id, text, parse_mode="Markdown"):
    chunks = split_long_text(text)
    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            chunk = f"📄 *Часть {i+1}/{len(chunks)}*\n\n{chunk}"
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode)

# ==================== AI СКЛЕЙКА ====================
async def ai_merge_code(current_code: str, new_part: str, instruction: str = "") -> dict:
    prompt = f"""Ты эксперт по сборке кода. Объедини текущий код с новой частью.
Текущий код:
{current_code if current_code else "(пусто)"}

Новая часть:
{new_part}

Инструкция: {instruction if instruction else "Объедини код"}

Верни JSON: {{"code": "полный код", "changes": "что изменено"}}"""
    
    try:
        response = ai_client.chat.completions.create(
            model="deepseek-coder",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000
        )
        result_text = response.choices[0].message.content
        result_text = result_text.strip('`').replace('json\n', '')
        result = json.loads(result_text)
        return {"code": result.get("code", new_part), "changes": result.get("changes", "Код обновлён")}
    except Exception as e:
        logger.error(f"AI ошибка: {e}")
        new_code = current_code + "\n\n" + new_part if current_code else new_part
        return {"code": new_code, "changes": "Простое склеивание"}

# ==================== ПЕРЕСТАНОВКА КОДА ====================
def reorder_code(code: str) -> str:
    lines = code.split('\n')
    functions = []
    imports = []
    other = []
    
    for line in lines:
        if line.strip().startswith(('import ', 'from ')):
            imports.append(line)
        elif line.strip().startswith(('def ', 'async def ')):
            functions.append(line)
        else:
            other.append(line)
    
    result = []
    if imports:
        result.extend(sorted(set(imports)))
        result.append('')
    if functions:
        result.extend(functions)
        result.append('')
    result.extend(other)
    
    return '\n'.join(result)

# ==================== ПОИСК БАГОВ ====================
def find_bugs(code: str) -> list:
    bugs = []
    patterns = [
        (r'/\s*0\b', 'Деление на ноль', 'CRITICAL', 'Проверьте делитель'),
        (r'eval\s*\(', 'Использование eval()', 'HIGH', 'Используйте ast.literal_eval()'),
        (r'except\s*:', 'Голый except', 'MEDIUM', 'Укажите конкретное исключение'),
        (r'password\s*=\s*[\'"]', 'Хардкод пароля', 'CRITICAL', 'Используйте переменные окружения'),
    ]
    
    for pattern, msg, severity, fix in patterns:
        if re.search(pattern, code):
            bugs.append({"message": msg, "severity": severity, "fix": fix})
    return bugs

def generate_bugs_report(bugs: list) -> str:
    if not bugs:
        return "✅ **Багов не найдено!**"
    report = "🐛 **Найденные проблемы:**\n\n"
    for b in bugs[:5]:
        report += f"• {b['message']} `[{b['severity']}]`\n  💡 {b['fix']}\n\n"
    return report

# ==================== АНАЛИЗ СЛОЖНОСТИ ====================
def analyze_complexity(code: str) -> dict:
    lines = code.split('\n')
    code_lines = len([l for l in lines if l.strip() and not l.strip().startswith('#')])
    functions = code.count('def ')
    branches = code.count('if ') + code.count('for ') + code.count('while ')
    complexity = 1 + branches * 0.5
    
    if complexity < 10:
        rating = "🟢 Низкая"
    elif complexity < 20:
        rating = "🟡 Средняя"
    else:
        rating = "🔴 Высокая"
    
    return {"lines": len(lines), "code_lines": code_lines, "functions": functions, "complexity": complexity, "rating": rating}

def format_complexity_report(analysis: dict) -> str:
    return f"""📊 **Анализ сложности**

• Строк кода: {analysis['code_lines']}
• Функций: {analysis['functions']}
• Цикломатическая: {analysis['complexity']:.1f}
• Оценка: {analysis['rating']}"""

# ==================== ВАЛИДАЦИЯ ====================
def validate_and_fix(code: str) -> tuple:
    errors = []
    fixes = []
    try:
        compile(code, '<string>', 'exec')
    except SyntaxError as e:
        errors.append(f"Синтаксическая ошибка: {e.msg}")
    return code, errors, fixes

# ==================== КОМАНДЫ БОТА ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": []}
    
    await update.message.reply_text(
        f"🤖 *AI Code Assembler Bot*\n\n"
        f"Привет! Я собираю код из частей.\n\n"
        f"🧠 *AI:* {AI_NAME}\n"
        f"📦 *Размер кода:* {len(user_sessions[user_id]['code'])} символов\n\n"
        f"*Команды:*\n"
        f"/show — показать код\n"
        f"/done — скачать файл\n"
        f"/reset — очистить\n"
        f"/complexity — анализ сложности\n"
        f"/bugs — поиск багов\n"
        f"/validate — проверить\n"
        f"/order — переставить функции\n"
        f"/web — веб-редактор\n\n"
        f"📝 Просто отправь мне часть кода!",
        parse_mode="Markdown"
    )

async def show_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code.strip():
        await update.message.reply_text("📭 Код пуст. Отправь мне часть кода!")
        return
    await send_long_message(context.bot, update.effective_chat.id, f"```python\n{code}\n```", parse_mode="Markdown")

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code.strip():
        await update.message.reply_text("❌ Нет кода для сохранения!")
        return
    
    filename = f"code_{user_id}.py"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(code)
    with open(filename, "rb") as f:
        await update.message.reply_document(document=f, filename=filename, caption="✅ Готовый код!")
    os.remove(filename)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        user_sessions[user_id]["code"] = ""
    await update.message.reply_text("🧹 Код очищен!")

async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода")
        return
    user_sessions[user_id]["code"] = reorder_code(code)
    await update.message.reply_text("🔄 Код переставлен!")

async def complexity_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода")
        return
    analysis = analyze_complexity(code)
    await update.message.reply_text(format_complexity_report(analysis), parse_mode="Markdown")

async def bugs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода")
        return
    bugs = find_bugs(code)
    await update.message.reply_text(generate_bugs_report(bugs), parse_mode="Markdown")

async def validate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = user_sessions.get(user_id, {}).get("code", "")
    if not code:
        await update.message.reply_text("📭 Нет кода")
        return
    fixed, errors, fixes = validate_and_fix(code)
    if errors:
        await update.message.reply_text(f"⚠️ Найдены ошибки:\n" + "\n".join(errors))
    else:
        await update.message.reply_text("✅ Код в идеальном состоянии!")

async def web_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_url = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-ai-bot-4g1k.onrender.com")
    await update.message.reply_text(f"🎨 *Веб-редактор*\n\n🔗 {bot_url}/web_editor/{user_id}", parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"code": "", "history": []}
    
    current = user_sessions[user_id]["code"]
    status = await update.message.reply_text(f"🧠 {AI_NAME} анализирует...")
    
    result = await ai_merge_code(current, user_message, "")
    final = result["code"]
    final = reorder_code(final)
    
    user_sessions[user_id]["code"] = final
    user_sessions[user_id]["history"].append({"time": str(datetime.now()), "part": user_message[:100]})
    
    await status.edit_text(
        f"✅ *Код обновлён!*\n\n"
        f"🔧 {result['changes']}\n"
        f"📊 Размер: {len(final)} символов\n\n"
        f"`/show` — посмотреть код\n"
        f"`/done` — скачать",
        parse_mode="Markdown"
    )

# ==================== ВЕБ-РЕДАКТОР ====================
WEB_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>🤖 AI Code Editor</title>
    <script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js"></script>
    <style>
        body { margin: 0; padding: 0; background: #1e1e1e; font-family: monospace; }
        #editor { height: 85vh; }
        .toolbar { background: #2d2d2d; padding: 10px; display: flex; gap: 10px; }
        button { padding: 8px 16px; background: #0e639c; color: white; border: none; cursor: pointer; border-radius: 4px; }
        button:hover { background: #1177bb; }
        .status { background: #1e1e1e; color: #888; padding: 5px 10px; font-size: 12px; }
    </style>
</head>
<body>
<div class="toolbar">
    <button onclick="saveCode()">💾 Сохранить</button>
    <button onclick="analyzeComplexity()">📊 Сложность</button>
    <button onclick="findBugs()">🐛 Баги</button>
    <button onclick="reorderCode()">🔄 Порядок</button>
</div>
<div id="editor"></div>
<div class="status" id="status">Готов к работе</div>
<script>
let editor;
require.config({ paths: { vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs' } });
require(['vs/editor/editor.main'], function() {
    editor = monaco.editor.create(document.getElementById('editor'), {
        value: {{ code | tojson }},
        language: 'python',
        theme: 'vs-dark',
        fontSize: 14,
        minimap: { enabled: true }
    });
});
async function saveCode() {
    const code = editor.getValue();
    await fetch('/api/save_code', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: {{ user_id }}, code: code})
    });
    document.getElementById('status').innerText = '✅ Сохранено!';
    setTimeout(() => document.getElementById('status').innerText = 'Готов к работе', 2000);
}
async function analyzeComplexity() {
    const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    alert(data.report);
}
async function findBugs() {
    const res = await fetch('/api/bugs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    alert(data.report);
}
async function reorderCode() {
    const res = await fetch('/api/reorder', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({code: editor.getValue()})
    });
    const data = await res.json();
    editor.setValue(data.code);
    document.getElementById('status').innerText = '🔄 Код переставлен!';
    setTimeout(() => document.getElementById('status').innerText = 'Готов к работе', 2000);
}
</script>
</body>
</html>
"""

@app.route('/web_editor/<int:user_id>')
def web_editor(user_id):
    code = user_sessions.get(user_id, {}).get("code", "")
    return render_template_string(WEB_HTML, user_id=user_id, code=code)

@app.route('/api/save_code', methods=['POST'])
def api_save_code():
    data = request.json
    user_id = data.get('user_id')
    code = data.get('code', '')
    if user_id in user_sessions:
        user_sessions[user_id]["code"] = code
    return jsonify({"success": True})

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    code = request.json.get('code', '')
    analysis = analyze_complexity(code)
    return jsonify({"report": format_complexity_report(analysis)})

@app.route('/api/bugs', methods=['POST'])
def api_bugs():
    code = request.json.get('code', '')
    bugs = find_bugs(code)
    return jsonify({"report": generate_bugs_report(bugs)})

@app.route('/api/reorder', methods=['POST'])
def api_reorder():
    code = request.json.get('code', '')
    return jsonify({"code": reorder_code(code)})

@app.route('/')
def health():
    return "🤖 Bot is running!", 200

# ==================== ЗАПУСК ====================
def run_telegram_bot():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("show", show_code))
    application.add_handler(CommandHandler("done", done))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CommandHandler("order", order_command))
    application.add_handler(CommandHandler("complexity", complexity_command))
    application.add_handler(CommandHandler("bugs", bugs_command))
    application.add_handler(CommandHandler("validate", validate_command))
    application.add_handler(CommandHandler("web", web_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info(f"🚀 Бот запущен! AI: {AI_NAME}")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    bot_thread = Thread(target=run_telegram_bot, daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=PORT)
