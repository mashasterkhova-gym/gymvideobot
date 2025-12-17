import os
import json
import time
import random
from typing import Dict, List, Optional

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
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_CHAT = os.getenv("GROUP_CHAT", "").strip()

SHEET_ID = os.getenv("SHEET_ID", "").strip()
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Sheet1").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

PAY_1M_URL = os.getenv("PAY_1M_URL", "https://getcourse.ru/").strip()
PAY_3M_URL = os.getenv("PAY_3M_URL", "https://getcourse.ru/").strip()
STRETCH_URL = os.getenv("STRETCH_URL", "").strip()
MUSCLE_IMAGE_URL = os.getenv("MUSCLE_IMAGE_URL", "").strip()

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

# ========= HELPERS =========
def _norm(s: str) -> str:
    return (s or "").strip().lower()

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

def limit_text() -> str:
    base = (
        "Больше видео доступно только для участниц сообщества.\n"
        "Доступ к сообществу можно оплатить в боте.\n"
        "А пока — порадуй себя мягкой растяжкой от нашего тренера 💛\n"
    )
    return base + (STRETCH_URL if STRETCH_URL else "")

# ========= ACCESS =========
async def is_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        m = await context.bot.get_chat_member(GROUP_CHAT, user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return False

def limit_reached(user_id: int, member: bool) -> bool:
    return False if member else USER_USAGE.get(user_id, 0) >= FREE_LIMIT

def inc_usage(user_id: int):
    USER_USAGE[user_id] = USER_USAGE.get(user_id, 0) + 1

# ========= GOOGLE SHEETS (cached) =========
_CACHE_TTL = 60
_cache = {"ts": 0.0, "rows": []}

def get_sheet_rows() -> List[dict]:
    now = time.time()
    if _cache["rows"] and (now - _cache["ts"] < _CACHE_TTL):
        return _cache["rows"]

    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)

    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except Exception:
        ws = sh.get_worksheet(0)

    rows = ws.get_all_records()
    _cache["rows"] = rows
    _cache["ts"] = now
    return rows

def find_muscle_from_text(text: str) -> Optional[str]:
    q = _norm(text)
    if not q:
        return None
    # exact first
    for m in ALLOWED_MUSCLES:
        if _norm(m) == q:
            return m
    # partial
    candidates = [m for m in ALLOWED_MUSCLES if q in _norm(m)]
    if len(candidates) == 1:
        return candidates[0]
    return None

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Выбирай действие 👇", reply_markup=main_keyboard())

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    member = await is_member(user_id, context)

    # Payment (never counted)
    if text in (BTN_PAY_1M, BTN_PAY_3M):
        await update.message.reply_text("Оплата доступа 👇", reply_markup=payment_kb())
        return

    # Buttons
    if text == BTN_FIND_VIDEO:
        if limit_reached(user_id, member):
            await update.message.reply_text(limit_text(), reply_markup=payment_kb())
            return
        context.user_data["mode"] = MODE_FIND
        await update.message.reply_text("Напиши название упражнения (или часть) 👇")
        return

    if text == BTN_REPLACE:
        if limit_reached(user_id, member):
            await update.message.reply_text(limit_text(), reply_markup=payment_kb())
            return
        context.user_data["mode"] = MODE_REPLACE
        await update.message.reply_text("Выбери нужную мышцу 👇")

        # try send image, fallback to sending link
        try:
            if MUSCLE_IMAGE_URL:
                await update.message.reply_photo(MUSCLE_IMAGE_URL)
            else:
                await update.message.reply_text("Картинка не настроена (MUSCLE_IMAGE_URL пуст).")
        except Exception:
            await update.message.reply_text(
                "Не смогла показать картинку 😿 Вот ссылка на неё:\n" + MUSCLE_IMAGE_URL
            )
        return

    # Modes
    mode = context.user_data.get("mode")
    rows = get_sheet_rows()

    if mode == MODE_FIND:
        if limit_reached(user_id, member):
            await update.message.reply_text(limit_text(), reply_markup=payment_kb())
            return

        inc_usage(user_id)
        q = _norm(text)
        results = [r for r in rows if q and q in _norm(str(r.get("exercise", "")))]
        if not results:
            await update.message.reply_text("Не нашла 😿 Попробуй короче/по-другому.")
            return

        msg = "\n\n".join(
            f"• {r.get('exercise','')}\n{r.get('url','')}\n{r.get('primary_muscle','')}"
            for r in results[:10]
        )
        await update.message.reply_text(msg)
        return

    if mode == MODE_REPLACE:
        if limit_reached(user_id, member):
            await update.message.reply_text(limit_text(), reply_markup=payment_kb())
            return

        muscle = find_muscle_from_text(text)
        if not muscle:
            await update.message.reply_text(
                "Не поняла мышцу 😿\n"
                "Напиши точнее (например: `Ягодицы`, `Средняя дельта`, `Верх трапеции`)."
            )
            return

        inc_usage(user_id)

        # match by normalized equality with primary_muscle in sheet
        mnorm = _norm(muscle)
        options = [r for r in rows if _norm(str(r.get("primary_muscle", ""))) == mnorm]

        if not options:
            await update.message.reply_text(f"По мышце «{muscle}» пока нет видео 😿")
            return

        pick = random.choice(options)
        await update.message.reply_text(
            f"Вот вариант замены 👇\n\n• {pick.get('exercise','')}\n{pick.get('url','')}"
        )
        return

    await update.message.reply_text("Выбери действие кнопкой 👇", reply_markup=main_keyboard())

# ========= RUN =========
async def post_init(app: Application):
    # important: clear webhook and pending updates to avoid weird conflicts/stale updates
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"delete_webhook failed: {repr(e)}", flush=True)

def run():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("Bot is running...", flush=True)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
