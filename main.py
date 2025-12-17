import os
import json
import random
from typing import Dict, List

from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# ========= ENV =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROUP_CHAT = os.getenv("GROUP_CHAT", "")

SHEET_ID = os.getenv("SHEET_ID", "")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Sheet1")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

PAY_1M_URL = os.getenv("PAY_1M_URL", "")
PAY_3M_URL = os.getenv("PAY_3M_URL", "")
STRETCH_URL = os.getenv("STRETCH_URL", "")
MUSCLE_IMAGE_URL = os.getenv("MUSCLE_IMAGE_URL", "")

# ========= CONSTANTS =========
FREE_LIMIT = 3
USER_USAGE: Dict[int, int] = {}

BTN_FIND_VIDEO = "🔎 Найти видео"
BTN_REPLACE = "🔁 Заменить упражнение"
BTN_PAY_1M = "💳 Оплатить клуб на 1 месяц"
BTN_PAY_3M = "💳 Оплатить клуб на 3 месяца"

MODE_FIND = "find"
MODE_REPLACE = "replace"

ALLOWED_MUSCLES = [
    "Грудные (верх)", "Грудные (середина)", "Грудные (низ)", "Грудные (весь блок)",
    "Спина (широчайшие)", "Спина (глубокий слой)", "Спина (разгибатели)",
    "Средняя трапеция", "Верх трапеции",
    "Передняя дельта", "Средняя дельта", "Задняя дельта",
    "Плечи (общая нагрузка)", "Ротаторы и элеваторы лопатки",
    "Бицепс", "Трицепс",
    "Квадрицепсы", "Хамстринги", "Сгибатели бедра",
    "Внутренняя поверхность бедра", "Ягодицы", "Ротаторы бедра",
]

# ========= GOOGLE SHEETS =========
def get_sheet_rows() -> List[dict]:
    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    client = gspread.authorize(creds)
    ws = client.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME)
    return ws.get_all_records()

# ========= UI =========
def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_FIND_VIDEO), KeyboardButton(BTN_REPLACE)],
            [KeyboardButton(BTN_PAY_1M), KeyboardButton(BTN_PAY_3M)],
        ],
        resize_keyboard=True,
    )

def payment_kb():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Оплатить 1 месяц", url=PAY_1M_URL)],
            [InlineKeyboardButton("Оплатить 3 месяца", url=PAY_3M_URL)],
        ]
    )

# ========= ACCESS =========
async def is_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(GROUP_CHAT, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def limit_reached(user_id: int, member: bool) -> bool:
    return False if member else USER_USAGE.get(user_id, 0) >= FREE_LIMIT

def inc_usage(user_id: int):
    USER_USAGE[user_id] = USER_USAGE.get(user_id, 0) + 1

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Выбирай действие 👇", reply_markup=main_keyboard())

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    member = await is_member(user_id, context)

    # --- Payment (never counted)
    if text in (BTN_PAY_1M, BTN_PAY_3M):
        await update.message.reply_text("Оплата доступа 👇", reply_markup=payment_kb())
        return

    # --- Find video
    ifROWS = get_sheet_rows()

    if text == BTN_FIND_VIDEO:
        if limit_reached(user_id, member):
            await update.message.reply_text(
                "Больше видео доступно только для участниц сообщества.\n"
                "Доступ к сообществу можно оплатить в боте.\n"
                f"А пока — мягкая растяжка 💛\n{STRETCH_URL}",
                reply_markup=payment_kb(),
            )
            return
        context.user_data["mode"] = MODE_FIND
        await update.message.reply_text("Напиши название упражнения 👇")
        return

    # --- Replace exercise
    if text == BTN_REPLACE:
        if limit_reached(user_id, member):
            await update.message.reply_text(
                "Больше видео доступно только для участниц сообщества.\n"
                "Доступ к сообществу можно оплатить в боте.\n"
                f"А пока — мягкая растяжка 💛\n{STRETCH_URL}",
                reply_markup=payment_kb(),
            )
            return
        context.user_data["mode"] = MODE_REPLACE
        await update.message.reply_text("Выбери нужную мышцу 👇")
        await update.message.reply_photo(MUSCLE_IMAGE_URL)
        return

    mode = context.user_data.get("mode")

    if mode == MODE_FIND:
        inc_usage(user_id)
        q = text.lower()
        results = [r for r in ROWS if q in r["exercise"].lower()]
        if not results:
            await update.message.reply_text("Не нашла 😿")
            return
        msg = "\n\n".join(
            f"• {r['exercise']}\n{r['url']}\n{r['primary_muscle']}"
            for r in results[:10]
        )
        await update.message.reply_text(msg)
        return

    if mode == MODE_REPLACE:
        muscle = next((m for m in ALLOWED_MUSCLES if text.lower() in m.lower()), None)
        if not muscle:
            await update.message.reply_text("Не поняла мышцу 😿 Попробуй ещё раз.")
            return
        inc_usage(user_id)
        options = [r for r in ROWS if r["primary_muscle"] == muscle]
        if not options:
            await update.message.reply_text("Пока нет видео по этой мышце 😿")
            return
        pick = random.choice(options)
        await update.message.reply_text(
            f"Вот вариант замены 👇\n\n• {pick['exercise']}\n{pick['url']}"
        )
        return

    await update.message.reply_text("Выбери действие кнопкой 👇", reply_markup=main_keyboard())

# ========= RUN =========
def run():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    run()
