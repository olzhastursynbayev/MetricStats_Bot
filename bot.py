import os
import json
import threading
import requests
import urllib.parse
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

app_web = Flask(__name__)

# Хранилище токенов (пока в памяти)
user_tokens = {}

# === Flask ===
@app_web.route('/')
def home():
    return "✅ Bot is running!"

@app_web.route('/oauth/callback')
def oauth_callback():
    code = request.args.get("code")
    telegram_id = request.args.get("state")  # Получаем telegram_id напрямую

    if not telegram_id:
        return "❌ Ошибка: не удалось получить Telegram ID."

    # Обмен кода на токен
    resp = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "client_id": os.getenv("FB_APP_ID"),
            "client_secret": os.getenv("FB_APP_SECRET"),
            "redirect_uri": os.getenv("REDIRECT_URI"),
            "code": code,
        }
    )
    data = resp.json()
    token = data.get("access_token")
    if token:
        user_tokens[int(telegram_id)] = token
        return "✅ Facebook подключен! Вернитесь в Telegram."
    else:
        return f"❌ Ошибка авторизации: {data}"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app_web.run(host="0.0.0.0", port=port)

# === Telegram bot ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Я помогу тебе подключить Meta Ads.\nНапиши /connect")

def get_auth_url(telegram_id: int):
    params = {
        "client_id": os.getenv("FB_APP_ID"),
        "redirect_uri": os.getenv("REDIRECT_URI"),
        "scope": "ads_read,ads_management,read_insights",
        "response_type": "code",
        # теперь передаём просто ID, без JSON
        "state": str(telegram_id)
    }
    base = "https://www.facebook.com/v19.0/dialog/oauth"
    return base + "?" + "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in params.items())

async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = get_auth_url(update.message.from_user.id)
    await update.message.reply
