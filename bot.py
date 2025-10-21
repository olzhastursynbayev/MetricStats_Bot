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
    state = json.loads(urllib.parse.unquote(request.args.get("state", "{}")))
    telegram_id = state.get("telegram_id")

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
        user_tokens[telegram_id] = token
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
        "state": json.dumps({"telegram_id": telegram_id})
    }
    base = "https://www.facebook.com/v19.0/dialog/oauth"
    return base + "?" + "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in params.items())

async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = get_auth_url(update.message.from_user.id)
    await update.message.reply_text(f"🔗 Подключи Facebook Ads: {url}")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    token = user_tokens.get(uid)
    if not token:
        await update.message.reply_text("❌ Сначала подключи Facebook через /connect")
        return
    resp = requests.get(
        "https://graph.facebook.com/v19.0/me/adaccounts?fields=name,account_id",
        params={"access_token": token}
    )
    await update.message.reply_text(f"📊 Твои рекламные аккаунты:\n{resp.text}")

def run_bot():
    TOKEN = os.getenv("BOT_TOKEN")
    tg_app = ApplicationBuilder().token(TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("connect", connect))
    tg_app.add_handler(CommandHandler("report", report))
    tg_app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()
