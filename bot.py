import os
import logging
import asyncio
import requests
import urllib.parse
from threading import Thread

from flask import Flask, request, redirect
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ====== Логирование ======
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ====== Конфиг из окружения ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
FB_APP_ID = os.getenv("FB_APP_ID")
FB_APP_SECRET = os.getenv("FB_APP_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")  # напр. https://metricstats-bot.onrender.com/oauth/callback
PORT = int(os.getenv("PORT", 5000))

if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not set in environment. Exiting.")
    raise SystemExit("BOT_TOKEN is required")

if not FB_APP_ID or not FB_APP_SECRET or not REDIRECT_URI:
    logger.warning("FB_APP_ID/FB_APP_SECRET/REDIRECT_URI not fully set — OAuth will fail until configured.")

# ====== Хранилище токенов (в памяти) ======
# формат: user_tokens[telegram_id] = access_token
user_tokens = {}

# ====== Flask (для OAuth callback) ======
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Bot is running!"

@app.route("/oauth/callback")
def oauth_callback():
    """
    Facebook redirects here with ?code=...&state=<telegram_id>
    We exchange code -> access_token and store it keyed by telegram_id.
    """
    error = request.args.get("error")
    if error:
        logger.error("OAuth error from provider: %s", error)
        return f"Auth error: {error}", 400

    code = request.args.get("code")
    state = request.args.get("state")  # we pass telegram_id here
    if not code:
        logger.error("Callback missing code")
        return "Missing code", 400
    if not state:
        logger.error("Callback missing state (telegram_id)")
        return "Missing state (telegram_id)", 400

    # exchange code -> short-lived token
    try:
        token_resp = requests.get(
            "https://graph.facebook.com/v19.0/oauth/access_token",
            params={
                "client_id": FB_APP_ID,
                "redirect_uri": REDIRECT_URI,
                "client_secret": FB_APP_SECRET,
                "code": code,
            },
            timeout=10
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
    except Exception as e:
        logger.exception("Failed to exchange code for token: %s", e)
        return f"Token exchange error: {e}", 500

    access_token = token_data.get("access_token")
    if not access_token:
        logger.error("No access_token in token response: %s", token_data)
        return f"Token exchange failed: {token_data}", 500

    # (Optional) exchange for long-lived token
    try:
        exch = requests.get(
            "https://graph.facebook.com/v19.0/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": FB_APP_ID,
                "client_secret": FB_APP_SECRET,
                "fb_exchange_token": access_token,
            },
            timeout=10
        )
        exch.raise_for_status()
        exch_data = exch.json()
        long_token = exch_data.get("access_token")
        if long_token:
            access_token = long_token
            logger.info("Exchanged to long-lived token")
    except Exception:
        logger.info("Long-lived token exchange failed or skipped")

    # Save token keyed to telegram_id
    try:
        tg_id = int(state)
        user_tokens[tg_id] = access_token
        logger.info("Saved access token for telegram_id=%s", tg_id)
    except Exception as e:
        logger.exception("Failed saving token for state=%s: %s", state, e)
        return "Failed to save token", 500

    bot_username = os.getenv("BOT_USERNAME")  # optional
    if bot_username:
        return redirect(f"https://t.me/{bot_username}?start=connected_{tg_id}")
    else:
        return "✅ Facebook connected! Return to Telegram and request /report."

# ====== Telegram handlers ======
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот для получения отчетов по рекламным аккаунтам Facebook.\n\n"
        "Используй /connect чтобы подключить Facebook Ads, затем /report чтобы получить аккаунты."
    )

def make_auth_url(telegram_id: int) -> str:
    """
    Build Facebook OAuth URL. We pass state=telegram_id (as plain string) to map later.
    """
    params = {
        "client_id": FB_APP_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "ads_read,ads_management,read_insights",
        "response_type": "code",
        "state": str(telegram_id)
    }
    return "https://www.facebook.com/v19.0/dialog/oauth?" + "&".join(
        f"{k}={urllib.parse.quote(v)}" for k, v in params.items()
    )

async def connect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    if not FB_APP_ID or not FB_APP_SECRET or not REDIRECT_URI:
        await update.message.reply_text("❌ OAuth not configured on server. Contact admin.")
        return
    auth_url = make_auth_url(tg_id)
    await update.message.reply_text(f"🔗 Перейди по ссылке, чтобы подключить Facebook Ads:\n\n{auth_url}")

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    token = user_tokens.get(tg_id)
    if not token:
        await update.message.reply_text("❌ Сначала подключи Facebook через /connect")
        return

    # get ad accounts
    try:
        resp = requests.get(
            "https://graph.facebook.com/v19.0/me/adaccounts",
            params={"fields": "name,account_id", "access_token": token},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as e:
        logger.exception("Failed to fetch adaccounts: %s", e)
        await update.message.reply_text("❌ Ошибка получения аккаунтов. Проверьте доступы.")
        return

    if not data:
        await update.message.reply_text("❌ У вас нет доступных рекламных аккаунтов.")
        return

    keyboard = [[InlineKeyboardButton(acc.get("name", "—"), callback_data=acc.get("account_id"))] for acc in data]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📊 Выберите рекламный аккаунт:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_id = query.data
    tg_id = query.from_user.id
    token = user_tokens.get(tg_id)
    if not token:
        await query.edit_message_text("❌ Сначала подключите Facebook через /connect")
        return

    # request insights
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/act_{account_id}/insights",
            params={
                "access_token": token,
                "fields": "campaign_name,impressions,clicks,spend",
                "date_preset": "last_7d"
            },
            timeout=15
        )
        resp.raise_for_status()
        items = resp.json().get("data", [])
    except Exception as e:
        logger.exception("Failed to fetch insights: %s", e)
        await query.edit_message_text("❌ Ошибка при получении отчета.")
        return

    if not items:
        await query.edit_message_text(f"❌ Нет данных для аккаунта {account_id} за последние 7 дней.")
        return

    text_lines = [f"📈 Отчет по аккаунту *{account_id}* за последние 7 дней:\n"]
    for it in items:
        text_lines.append(
            f"📢 {it.get('campaign_name','—')}\n"
            f"👀 {it.get('impressions','0')} показов  •  🖱️ {it.get('clicks','0')} кликов  •  💰 {it.get('spend','0')}$\n"
        )
    text = "\n".join(text_lines)
    await query.edit_message_text(text, parse_mode="Markdown")

# ====== Run application (async) ======
async def start_application():
    application: Application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("connect", connect_cmd))
    application.add_handler(CommandHandler("report", report_cmd))
    application.add_handler(CallbackQueryHandler(button_handler))

    # В v21 используем application.initialize()/start()/updater.start_polling() больше нет.
    await application.initialize()
    await application.start()
    logger.info("Telegram bot polling started")
    # run until Ctrl+C
    await application.running_until_cancelled()
    await application.stop()
    await application.shutdown()

def run_flask_thread():
    # Flask нужен Render'у для проверки порта и для OAuth callback
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)

if __name__ == "__main__":
    # поднимем Flask в отдельном потоке, чтобы Render видел открытый порт
    Thread(target=run_flask_thread, daemon=True).start()
    try:
        asyncio.run(start_application())
    except KeyboardInterrupt:
        logger.info("Shutting down")
