"""
Telegram-бот: Випадкова стаття Кримінального кодексу України
Запуск: python bot.py
Потрібна бібліотека: pip install python-telegram-bot==20.7
"""

import json
import random
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from emoji_mapper import get_emoji

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Завантаження даних
# ─────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(__file__), "ккy_особлива_частина_ст109-447_bot.json")

with open(DATA_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

# Відфільтровуємо виключені статті (ті що починаються на '{')
ARTICLES = [
    a for a in data["articles"]
    if not a["name"].startswith("{") and a["text"].strip()
]

logger.info(f"Завантажено {len(ARTICLES)} активних статей")

# ─────────────────────────────────────────────
# Rate limiter: 3 статті на годину на користувача
# ─────────────────────────────────────────────
RATE_LIMIT = 3
RATE_WINDOW = timedelta(hours=1)

# user_id -> список datetime останніх запитів
user_requests: dict[int, list[datetime]] = defaultdict(list)


def check_rate_limit(user_id: int) -> tuple[bool, int]:
    """
    Перевіряє чи може користувач отримати статтю.
    Повертає (allowed: bool, seconds_until_reset: int).
    """
    now = datetime.now()
    cutoff = now - RATE_WINDOW

    # Прибираємо запити старші за 1 годину
    user_requests[user_id] = [t for t in user_requests[user_id] if t > cutoff]

    if len(user_requests[user_id]) >= RATE_LIMIT:
        oldest = user_requests[user_id][0]
        reset_at = oldest + RATE_WINDOW
        seconds_left = int((reset_at - now).total_seconds()) + 1
        return False, seconds_left

    user_requests[user_id].append(now)
    return True, 0


def format_wait_time(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600} год {(seconds % 3600) // 60} хв"
    if seconds >= 60:
        return f"{seconds // 60} хв {seconds % 60} сек"
    return f"{seconds} сек"


# ─────────────────────────────────────────────
# Форматування статті
# ─────────────────────────────────────────────
def format_article(article: dict) -> list[str]:
    """
    Повертає список повідомлень (частин) для відправки в Telegram.
    Кожна частина <= 4096 символів.
    """
    emoji = get_emoji(article)
    num = article["number"]
    name = article["name"]
    text = article["text"]

    header = f"{emoji} <b>Стаття {num}. {name}</b>\n\n"
    full = header + text

    if len(full) <= 4096:
        return [full]

    # Розбиваємо на частини по абзацах
    parts = []
    lines = text.split("\n")
    current = header
    part_idx = 1

    for line in lines:
        candidate = current + line + "\n"
        if len(candidate) > 4000:
            parts.append(current.strip())
            part_idx += 1
            current = f"{emoji} <b>Стаття {num} (продовження {part_idx})</b>\n\n{line}\n"
        else:
            current = candidate

    if current.strip():
        parts.append(current.strip())

    return parts


def get_random_article() -> dict:
    return random.choice(ARTICLES)


def get_article_by_number(number: str) -> dict | None:
    for a in ARTICLES:
        if a["number"] == number:
            return a
    return None


# ─────────────────────────────────────────────
# Клавіатура
# ─────────────────────────────────────────────
def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Ще одна стаття", callback_data="random")],
        [InlineKeyboardButton("📖 Про бота", callback_data="about")],
    ])


# ─────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "⚖️ <b>Кримінальний кодекс України — Особлива частина</b>\n\n"
        "Цей бот показує випадкові статті ККУ (ст. 109–447).\n\n"
        "📌 Команди:\n"
        "/random — випадкова стаття\n"
        "/article 115 — стаття за номером\n\n"
        "⏳ Ліміт: <b>3 статті на годину</b> для кожного користувача.\n\n"
        "Натисни кнопку нижче або відправ /random 👇"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())


async def cmd_random(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    allowed, seconds_left = check_rate_limit(user_id)

    if not allowed:
        wait = format_wait_time(seconds_left)
        await update.message.reply_text(
            f"⏳ <b>Ліміт вичерпано.</b>\n\n"
            f"Ти вже отримав {RATE_LIMIT} статті за останню годину.\n"
            f"Наступна стаття буде доступна через <b>{wait}</b>.",
            parse_mode="HTML"
        )
        return

    article = get_random_article()
    parts = format_article(article)
    remaining = RATE_LIMIT - len(user_requests[user_id])

    for i, part in enumerate(parts):
        kb = main_keyboard() if i == len(parts) - 1 else None
        await update.message.reply_text(part, parse_mode="HTML", reply_markup=kb)

    if remaining == 0:
        await update.message.reply_text(
            "⚠️ Це була твоя остання стаття на цю годину. Повертайся пізніше! 🕐",
            parse_mode="HTML"
        )


async def cmd_article(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "❗ Вкажи номер статті. Наприклад: /article 115",
            parse_mode="HTML"
        )
        return

    number = context.args[0].strip()
    article = get_article_by_number(number)

    if not article:
        await update.message.reply_text(
            f"❌ Стаття <b>{number}</b> не знайдена або виключена з кодексу.\n\n"
            f"Доступні статті: 109–447",
            parse_mode="HTML"
        )
        return

    parts = format_article(article)
    for i, part in enumerate(parts):
        kb = main_keyboard() if i == len(parts) - 1 else None
        await update.message.reply_text(part, parse_mode="HTML", reply_markup=kb)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "random":
        user_id = update.effective_user.id
        allowed, seconds_left = check_rate_limit(user_id)

        if not allowed:
            wait = format_wait_time(seconds_left)
            await query.answer(
                f"⏳ Ліміт вичерпано. Повертайся через {wait}.",
                show_alert=True
            )
            return

        article = get_random_article()
        parts = format_article(article)
        remaining = RATE_LIMIT - len(user_requests[user_id])

        await query.edit_message_text(
            parts[0], parse_mode="HTML",
            reply_markup=main_keyboard() if len(parts) == 1 else None
        )
        for i, part in enumerate(parts[1:], 1):
            kb = main_keyboard() if i == len(parts) - 1 else None
            await query.message.reply_text(part, parse_mode="HTML", reply_markup=kb)

        if remaining == 0:
            await query.message.reply_text(
                "⚠️ Це була твоя остання стаття на цю годину. Повертайся пізніше! 🕐",
                parse_mode="HTML"
            )

    elif query.data == "about":
        text = (
            "⚖️ <b>Про бота</b>\n\n"
            "База: Кримінальний кодекс України\n"
            "Розділ: Особлива частина (ст. 109–447)\n"
            "Джерело: zakon.rada.gov.ua\n\n"
            "Бот показує випадкові статті з текстом санкцій.\n"
            "Для навчальних та довідкових цілей. 🎓\n\n"
            f"⏳ Ліміт: <b>{RATE_LIMIT} статті на годину</b> для кожного користувача.\n\n"
            "<i>Не є юридичною консультацією.</i>"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_keyboard())


# ─────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────
def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError(
            "❌ Не знайдено токен бота!\n"
            "Встанови змінну середовища BOT_TOKEN:\n"
            "  export BOT_TOKEN=123456:ABC-DEF...\n"
            "  python bot.py"
        )

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("random", cmd_random))
    app.add_handler(CommandHandler("article", cmd_article))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("✅ Бот запущено. Натисни Ctrl+C для зупинки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
