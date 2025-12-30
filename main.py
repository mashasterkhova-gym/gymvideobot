import os
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    CallbackQueryHandler,
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

# Image: prefer local file, fallback to URL
MUSCLE_IMAGE_PATH = os.getenv("MUSCLE_IMAGE_PATH", "muscles.png").strip()
MUSCLE_IMAGE_URL = os.getenv("MUSCLE_IMAGE_URL", "").strip()

# Optional: column names in Google Sheet (defaults match our bot)
COL_EXERCISE = os.getenv("COL_EXERCISE", "exercise").strip()
COL_URL = os.getenv("COL_URL", "url").strip()
COL_MUSCLES = os.getenv("COL_MUSCLES", "primary_muscle").strip()  # muscles in one cell, comma-separated

# ========= UI TEXT =========
BTN_FIND_VIDEO = "🔎 Найти видео"
BTN_REPLACE = "🔁 Заменить упражнение"
BTN_PAY_1M = "💳 Оплатить клуб на 1 месяц"
BTN_PAY_3M = "💳 Оплатить клуб на 3 месяца"

MODE_FIND = "find"
MODE_REPLACE = "replace"

# ========= LIMITS =========
FREE_LIMIT = 3
USER_USAGE: Dict[int, int] = {}  # in-memory counters (MVP)

LIMIT_MESSAGE = (
    "Больше видео доступно только для участниц сообщества.\n"
    "Доступ к сообществу можно оплатить в боте.\n"
    "А пока — порадуй себя мягкой растяжкой от нашего тренера 💛\n"
)

# ========= MUSCLES LIST (your canonical list) =========
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

# aliases to be more forgiving (optional but helps with "Ягодица"/"Широчайшие"/"Разгибатели")
ALIASES = {
    "ягодица": "ягодицы",
    "ягодицы": "ягодицы",
    "широчайшие": "спина (широчайшие)",
    "разгибатели": "спина (разгибатели)",
}

# ========= Google Sheet cache =========
CACHE_TTL_SEC = 60
_sheet_cache = {"ts": 0.0, "rows": []}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _require_env() -> None:
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not GROUP_CHAT:
        missing.append("GROUP_CHAT")
    if not SHEET_ID:
        missing.append("SHEET_ID")
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")
    if missing:
        raise RuntimeError(f"Missing env vars: {', '.join(missing)}")


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_FIND_VIDEO), KeyboardButton(BTN_REPLACE)],
            [KeyboardButton(BTN_PAY_1M), KeyboardButton(BTN_PAY_3M)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def pay_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Оплатить 1 месяц", url=PAY_1M_URL)],
            [InlineKeyboardButton("Оплатить 3 месяца", url=PAY_3M_URL)],
        ]
    )


def get_usage(user_id: int) -> int:
    return int(USER_USAGE.get(user_id, 0))


def inc_usage(user_id: int) -> None:
    USER_USAGE[user_id] = get_usage(user_id) + 1


def limit_reached(is_member: bool, user_id: int) -> bool:
    return (not is_member) and (get_usage(user_id) >= FREE_LIMIT)


def limit_text() -> str:
    return LIMIT_MESSAGE + (STRETCH_URL or "")


async def is_member_of_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        m = await context.bot.get_chat_member(chat_id=GROUP_CHAT, user_id=user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return False


def _get_gspread_client() -> gspread.Client:
    info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    return gspread.authorize(creds)


def get_rows_from_sheet() -> List[Dict[str, str]]:
    now = time.time()
    if _sheet_cache["rows"] and (now - _sheet_cache["ts"] < CACHE_TTL_SEC):
        return _sheet_cache["rows"]

    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)

    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except Exception:
        ws = sh.get_worksheet(0)

    records = ws.get_all_records()
    rows: List[Dict[str, str]] = []
    for r in records:
        rows.append(
            {
                "exercise": str(r.get(COL_EXERCISE, "")).strip(),
                "url": str(r.get(COL_URL, "")).strip(),
                "muscles": str(r.get(COL_MUSCLES, "")).strip(),  # comma-separated in one cell
            }
        )

    _sheet_cache["rows"] = rows
    _sheet_cache["ts"] = now
    return rows


def split_muscles(cell_value: str) -> List[str]:
    """
    'Передняя дельта, Разгибатели, Хамстринги'
    -> ['передняя дельта', 'разгибатели', 'хамстринги']
    """
    if not cell_value:
        return []
    return [_norm(x) for x in str(cell_value).split(",") if x.strip()]


def canonical_keys(muscle: str) -> List[str]:
    """
    Makes matching tolerant:
    - 'Спина (разгибатели)' -> ['спина (разгибатели)', 'разгибатели']
    - 'Средняя трапеция' -> ['средняя трапеция']
    """
    m = _norm(muscle)
    keys = [m]
    if "(" in m and ")" in m:
        inside = m.split("(", 1)[1].split(")", 1)[0].strip()
        if inside:
            keys.append(inside)
    # alias mapping (optional)
    if m in ALIASES:
        keys.append(_norm(ALIASES[m]))
    return list(dict.fromkeys([k for k in keys if k]))


def muscles_match(target_muscle: str, cell_value: str) -> bool:
    """
    Match if ANY muscle from the cell matches target:
    - exact
    - substring either direction
    - with keys from canonical (handles '(...)' part)
    """
    cell_items = split_muscles(cell_value)
    if not cell_items:
        return False

    keys = canonical_keys(target_muscle)
    for item in cell_items:
        # apply alias for item too
        item2 = _norm(ALIASES.get(item, item))
        for k in keys:
            if item2 == k or k in item2 or item2 in k:
                return True
    return False


def search_by_exercise(query: str) -> List[Dict[str, str]]:
    q = _norm(query)
    if not q:
        return []
    rows = get_rows_from_sheet()
    return [r for r in rows if q in _norm(r["exercise"])]


def resolve_muscle(user_text: str) -> Tuple[str, Optional[int], List[str]]:
    """
    Returns:
      ("exact", idx, [])
      ("many", None, candidates)
      ("none", None, [])
    """
    q = _norm(user_text)
    if not q:
        return ("none", None, [])

    # exact by canonical list
    for i, m in enumerate(ALLOWED_MUSCLES):
        if _norm(m) == q:
            return ("exact", i, [])

    # partial matches by canonical list
    candidates = [(i, m) for i, m in enumerate(ALLOWED_MUSCLES) if q in _norm(m)]
    if len(candidates) == 1:
        return ("exact", candidates[0][0], [])
    if len(candidates) > 1:
        return ("many", None, [m for _, m in candidates[:30]])
    return ("none", None, [])


def search_by_muscle(canonical_muscle: str) -> List[Dict[str, str]]:
    rows = get_rows_from_sheet()
    return [r for r in rows if muscles_match(canonical_muscle, r.get("muscles", ""))]


def format_item(r: Dict[str, str]) -> str:
    ex = r.get("exercise", "") or "Без названия"
    url = r.get("url", "")
    muscles = r.get("muscles", "")
    out = f"• {ex}"
    if url:
        out += f"\n{url}"
    if muscles:
        out += f"\n{muscles}"
    return out


async def send_muscle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Выбери нужную мышцу 👇")

    path = Path(MUSCLE_IMAGE_PATH)
    try:
        if path.exists():
            with path.open("rb") as f:
                await update.message.reply_photo(photo=f)
        elif MUSCLE_IMAGE_URL:
            await update.message.reply_photo(photo=MUSCLE_IMAGE_URL)
        else:
            await update.message.reply_text("Картинка пока не настроена 😿")
    except Exception:
        if MUSCLE_IMAGE_URL:
            await update.message.reply_text(f"Не смогла показать картинку, вот ссылка:\n{MUSCLE_IMAGE_URL}")
        else:
            await update.message.reply_text("Не смогла показать картинку 😿")

    await update.message.reply_text("Напиши мышцу текстом (можно часть слова, например: `ягод` или `дельта`).")


def page_keyboard(idx: int, page: int, total: int, page_size: int) -> InlineKeyboardMarkup:
    max_page = max(0, (total - 1) // page_size)
    buttons = []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"m:{idx}:{page-1}"))
    if page < max_page:
        row.append(InlineKeyboardButton("➡️ Дальше", callback_data=f"m:{idx}:{page+1}"))
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons) if buttons else InlineKeyboardMarkup([])


async def send_muscle_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    idx: int,
    page: int,
    edit: bool,
):
    muscle = ALLOWED_MUSCLES[idx]
    items: List[Dict[str, str]] = context.user_data.get("last_items", [])
    page_size: int = int(context.user_data.get("page_size", 15))
    total = len(items)

    start_i = page * page_size
    end_i = start_i + page_size
    slice_items = items[start_i:end_i]

    header = f"Видео по мышце «{muscle}» — всего {total}. Страница {page+1}.\n\n"
    body = header + "\n\n".join([format_item(r) for r in slice_items])

    kb = page_keyboard(idx=idx, page=page, total=total, page_size=page_size)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(body, reply_markup=kb)
    else:
        await update.message.reply_text(body, reply_markup=kb)


# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Привет! 👋 Выбирай действие:", reply_markup=main_keyboard())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    member = await is_member_of_group(user_id, context)

    # Payment buttons never count
    if text == BTN_PAY_1M:
        await update.message.reply_text("Оплата за 1 месяц 👇", reply_markup=pay_buttons())
        return
    if text == BTN_PAY_3M:
        await update.message.reply_text("Оплата за 3 месяца 👇", reply_markup=pay_buttons())
        return

    # Menu actions
    if text == BTN_FIND_VIDEO:
        if limit_reached(member, user_id):
            await update.message.reply_text(limit_text(), reply_markup=pay_buttons())
            return
        context.user_data["mode"] = MODE_FIND
        await update.message.reply_text("Ок! Напиши название (или часть названия) упражнения 👇")
        return

    if text == BTN_REPLACE:
        if limit_reached(member, user_id):
            await update.message.reply_text(limit_text(), reply_markup=pay_buttons())
            return
        context.user_data["mode"] = MODE_REPLACE
        await send_muscle_prompt(update, context)
        return

    mode = context.user_data.get("mode")

    if mode == MODE_FIND:
        if limit_reached(member, user_id):
            await update.message.reply_text(limit_text(), reply_markup=pay_buttons())
            return

        inc_usage(user_id)

        results = search_by_exercise(text)
        if not results:
            await update.message.reply_text("Не нашла 😿 Попробуй другое слово или короче запрос.")
            return

        await update.message.reply_text("Нашла вот что 👇")
        # send up to 30 results in chunks
        lines = [format_item(r) for r in results[:30]]
        chunk, size = [], 0
        for line in lines:
            piece = line + "\n\n"
            if size + len(piece) > 3500 and chunk:
                await update.message.reply_text("".join(chunk).strip())
                chunk, size = [], 0
            chunk.append(piece)
            size += len(piece)
        if chunk:
            await update.message.reply_text("".join(chunk).strip())
        return

    if mode == MODE_REPLACE:
        if limit_reached(member, user_id):
            await update.message.reply_text(limit_text(), reply_markup=pay_buttons())
            return

        kind, idx, candidates = resolve_muscle(text)

        if kind == "none":
            await update.message.reply_text(
                "Не поняла мышцу 😿\n"
                "Попробуй ещё раз (например: `Ягодицы`, `Средняя дельта`, `Спина (разгибатели)`)."
            )
            return

        if kind == "many":
            suggest = "\n".join([f"• {m}" for m in candidates])
            await update.message.reply_text("Нашла несколько вариантов — скопируй один из списка:\n\n" + suggest)
            return

        # exact muscle counts as a request
        assert idx is not None
        inc_usage(user_id)

        muscle = ALLOWED_MUSCLES[idx]
        items = search_by_muscle(muscle)
        if not items:
            await update.message.reply_text(f"По мышце «{muscle}» пока нет видео 😿")
            return

        # Save for paging
        context.user_data["last_idx"] = idx
        context.user_data["last_items"] = items
        context.user_data["page_size"] = 15

        await send_muscle_page(update, context, idx=idx, page=0, edit=False)
        return

    await update.message.reply_text("Сначала выбери действие кнопкой 👇", reply_markup=main_keyboard())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    if not data.startswith("m:"):
        return

    try:
        _, idx_str, page_str = data.split(":", 2)
        idx = int(idx_str)
        page = int(page_str)
        if idx < 0 or idx >= len(ALLOWED_MUSCLES):
            return
    except Exception:
        return

    # If state mismatched, refresh from sheet (cheap thanks to cache)
    last_idx = context.user_data.get("last_idx")
    if last_idx != idx:
        muscle = ALLOWED_MUSCLES[idx]
        context.user_data["last_idx"] = idx
        context.user_data["last_items"] = search_by_muscle(muscle)
        context.user_data["page_size"] = int(context.user_data.get("page_size", 15))

    await send_muscle_page(update, context, idx=idx, page=page, edit=True)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # prevents "No error handlers are registered"
    try:
        err = context.error
        print(f"[ERROR] {repr(err)}", flush=True)
    except Exception:
        pass


async def post_init(app: Application):
    # Clear webhook & pending updates to avoid stuck states
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"delete_webhook failed: {repr(e)}", flush=True)


def run():
    _require_env()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    print("Bot is running...", flush=True)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
