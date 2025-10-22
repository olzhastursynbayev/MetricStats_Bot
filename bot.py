import os
import logging
import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# ====== Настройки логирования ======
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ====== Хранилище токенов пользователей (для теста, потом лучше использовать БД) ======
user_tokens = {}

# ====== Токен Telegram ======
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# ====== URL для авторизации в Facebook ======
REDIRECT_URI = "https://твоя-ссылка-на-render.onrender.com/oauth/callback"
FB_APP_ID = os.getenv("FB_APP_ID")
FB_APP_SECRET = os.getenv("FB_APP_SECRET")


# ====== Команда /start ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот для получения отчетов по рекламным аккаунтам Facebook.\n\n"
        "Чтобы начать, подключи свой аккаунт через команду /connect"
    )


# ====== Команда /connect ======
async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fb_auth_url = (
        f"https://www.facebook.com/v19.0/dialog/oauth?"
        f"client_id={FB_APP_ID}&redirect_uri={REDIRECT_URI}&scope=ads_read"
    )
    await update.message.reply_text(
        f"🔗 Чтобы подключить аккаунт, перейди по ссылке:\n{fb_auth_url}"
    )


# ====== Команда /report ======
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    token = user_tokens.get(uid)
    if not token:
        await update.message.reply_text("❌ Сначала подключи Facebook через /connect")
        return

    # Получаем список рекламных аккаунтов
    resp = requests.get(
        "https://graph.facebook.com/v19.0/me/adaccounts?fields=name,account_id",
        params={"access_token": token}
    )
    data = resp.json().get("data", [])

    if not data:
        await update.message.reply_text("❌ У тебя нет рекламных аккаунтов.")
        return

    # Формируем кнопки
    keyboard = [
        [InlineKeyboardButton(acc["name"], callback_data=acc["account_id"])]
        for acc in data
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("📊 Выбери рекламный аккаунт:", reply_markup=reply_markup)


# ====== Обработчик нажатий кнопок ======
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    account_id = query.data
    uid = query.from_user.id
    token = user_tokens.get(uid)

    # Получаем отчет по выбранному аккаунту
    resp = requests.get(
        f"https://graph.facebook.com/v19.0/act_{account_id}/insights",
        params={
            "access_token": token,
            "fields": "campaign_name,impressions,clicks,spend",
            "date_preset": "last_7d"
        }
    )
    data = resp.json().get("data", [])

    if not data:
        await query.edit_message_text(
            f"❌ Нет данных для аккаунта {account_id} за последние 7 дней."
        )
        return

    # Формируем красивый отчет
    text = f"📈 Отчет по аккаунту *{account_id}* за последние 7 дней:\n\n"
    for item in data:
        text += (
            f"📢 Кампания: {item.get('campaign_name', '—')}\n"
            f"👀 Показы: {item.get('impressions', '0')}\n"
            f"🖱️ Клики: {item.get('clicks', '0')}\n"
            f"💰 Расход: {item.get('spend', '0')} $\n\n"
        )

    await query.edit_message_text(text, parse_mode="Markdown")


# ====== Фейковая обработка колбэка (на проде — реальная авторизация) ======
# 👉 Этот блок нужно будет заменить на настоящий OAuth, если ещё не сделано
from flask import Flask, request

app = Flask(__name__)

@app.route("/oauth/callback")
def fb_callback():
    code = request.args.get("code")
    if not code:
        return "❌ Ошибка авторизации", 400

    # Обмениваем code на access_token
    token_resp = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "client_id": FB_APP_ID,
            "redirect_uri": REDIRECT_URI,
            "client_secret": FB_APP_SECRET,
            "code": code
        }
    ).json()

    access_token = token_resp.get("access_token")
    if not access_token:
        return "❌ Ошибка получения токена", 400

    # Получаем ID пользователя Facebook
    user_info = requests.get(
        "https://graph.facebook.com/me",
        params={"access_token": access_token}
    ).json()
    fb_user_id = user_info.get("id")

    # ⚠️ Для теста: сохраняем токен на 1 пользователя
    # На проде нужно связать fb_user_id с Telegram user_id
    user_tokens[fb_user_id] = access_token

    return "✅ Авторизация прошла успешно! Теперь вернись в Telegram и введи /report"


# ====== Запуск бота ======
def run_bot():
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("connect", connect))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()


if __name__ == "__main__":
    from threading import Thread
    # Flask в отдельном потоке
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))).start()
    # Telegram бот
    run_bot()
