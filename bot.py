import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Базовая команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Бот успешно запущен на сервере!")

# Точка входа
if __name__ == "__main__":
    TOKEN = os.getenv("BOT_TOKEN")  # Токен будет храниться в переменных окружения
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    print("✅ Бот запущен и работает...")
    app.run_polling()
