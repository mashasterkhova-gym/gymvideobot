import os
from dotenv import load_dotenv

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

from notion_client import Client as NotionClient

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()

PAY_1M_URL = os.getenv("PAY_1M_URL", "https://getcourse.ru/").strip()
PAY_3M_URL = os.getenv("PAY_3M_URL", "https://getcourse.ru/").strip()

# ✅ Твои реальные названия свойств в Notion
PROP_TITLE = "Name"      # Title
PROP_URL = "Link"        # URL
PROP_TAGS = "Muscles"    # Multi-select
PROP_ACTIVE = "Active"   # Checkbox

notion = NotionClient(auth=NOTION_TOKEN)

BTN_FIND_VIDEO = "🔎 Найти видео"
BTN_FIND_TAG = "🏷️ Найти хештег"
BTN_PAY_1M = "💳 Оплатить клуб на 1 месяц"
BTN_PAY_3M = "💳 Оплатить клуб на 3 месяца"

MODE_NONE = None
MODE_FIND_VIDEO = "find_video"
MODE_FIND_TAG = "find_tag"


def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_FIND_VIDEO), KeyboardButton(BTN_FIND_TAG)],
            [KeyboardButton(BTN_PAY_1M), KeyboardButton(BTN_PAY_3M)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def pay_kb(url: str, label: str):
    if not url:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)]])


def _get_title(page) -> str:
    prop = page.get("properties", {}).get(PROP_TITLE, {})
    title_arr = prop.get("title", [])
    if not title_arr:
        return "Без названия"
    return "".join(x.get("plain_text", "") for x in title_arr).strip() or "Без названия"


def _get_url(page) -> str:
    prop = page.get("properties", {}).get(PROP_URL, {})
    return (prop.get("url") or "").strip()


def _get_tags(page):
    prop = page.get("properties", {}).get(PROP_TAGS, {})
    ms = prop.get("multi_select", []) or []
    return [x.get("name", "").strip() for x in ms if x.get("name")]


def _is_active(page) -> bool:
    prop = page.get("properties", {}).get(PROP_ACTIVE)
    if not prop:
        return True
    if prop.get("type") == "checkbox":
        return bool(prop.get("checkbox"))
    return True


def notion_search_by_title(query: str, limit: int = 10):
    q = query.strip()
    if not q:
        return []

    res = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        page_size=min(max(limit, 1), 50),
        filter={
            "and": [
                {
                    "property": PROP_TITLE,
                    "title": {"contains": q},
                }
            ]
        },
    )
    pages = res.get("results", []) or []
    pages = [p for p in pages if _is_active(p)]
    return pages[:limit]


def notion_search_by_tag_exact(tag: str, limit: int = 10):
    t = tag.strip()
    if not t:
        return []

    res = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        page_size=min(max(limit, 1), 50),
        filter={
            "and": [
                {
                    "property": PROP_TAGS,
                    "multi_select": {"contains": t},
                }
            ]
        },
    )
    pages = res.get("results", []) or []
    pages = [p for p in pages if _is_active(p)]
    return pages[:limit]


def notion_get_all_muscles(limit_pages: int = 500):
    muscles = set()
    start_cursor = None
    pages_seen = 0

    while True:
        kwargs = {
            "database_id": NOTION_DATABASE_ID,
            "page_size": 100,
        }
        if start_cursor:
            kwargs["start_cursor"] = start_cursor

        res = notion.databases.query(**kwargs)
        results = res.get("results", []) or []

        for p in results:
            if not _is_active(p):
                continue
            for m in _get_tags(p):
                if m:
                    muscles.add(m)

        pages_seen += 1
        if pages_seen >= limit_pages:
            break

        if res.get("has_more"):
            start_cursor = res.get("next_cursor")
            if not start_cursor:
                break
        else:
            break

    return sorted(muscles, key=lambda x: x.lower())


def format_pages(pages):
    blocks = []
    for p in pages:
        title = _get_title(p)
        url = _get_url(p)
        tags = _get_tags(p)

        tags_line = (" ".join(tags)).strip()
        if url:
            block = f"• {title}\n{url}"
        else:
            block = f"• {title}\n(ссылка не указана)"

        if tags_line:
            block += f"\n{tags_line}"

        blocks.append(block)

    return "\n\n".join(blocks)


def format_muscles_list(muscles):
    if not muscles:
        return ["Пока список мышц пустой (или все записи неактивны)."]

    chunks = []
    current = "Доступные мышцы в базе:\n\n"
    for m in muscles:
        line = f"• {m}\n"
        if len(current) + len(line) > 3800:
            chunks.append(current.rstrip())
            current = ""
        current += line

    if current.strip():
        chunks.append(current.rstrip())

    return chunks


def resolve_muscle_input(user_text: str, muscles):
    q = (user_text or "").strip()
    if not q:
        return ("none", [])

    q_low = q.lower()

    for m in muscles:
        if m.lower() == q_low:
            return ("exact", m)

    candidates = [m for m in muscles if q_low in m.lower()]
    if len(candidates) == 1:
        return ("exact", candidates[0])
    if len(candidates) > 1:
        return ("many", candidates[:20])
    return ("none", [])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = MODE_NONE
    await update.message.reply_text(
        "Привет! Выбирай действие 👇",
        reply_markup=main_keyboard(),
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text == BTN_FIND_VIDEO:
        context.user_data["mode"] = MODE_FIND_VIDEO
        await update.message.reply_text("Ок! Напиши название (или часть названия) видео 👇")
        return

    if text == BTN_FIND_TAG:
        context.user_data["mode"] = MODE_FIND_TAG

        muscles = notion_get_all_muscles()
        context.user_data["muscles_list"] = muscles

        for msg in format_muscles_list(muscles):
            await update.message.reply_text(msg)

        await update.message.reply_text(
            "Теперь напиши мышцу (можно часть слова, например: `ягод`), и я найду видео 👇"
        )
        return

    if text == BTN_PAY_1M:
        await update.message.reply_text(
            "Оплата за 1 месяц 👇",
            reply_markup=pay_kb(PAY_1M_URL, "Оплатить 1 месяц"),
        )
        return

    if text == BTN_PAY_3M:
        await update.message.reply_text(
            "Оплата за 3 месяца 👇",
            reply_markup=pay_kb(PAY_3M_URL, "Оплатить 3 месяца"),
        )
        return

    mode = context.user_data.get("mode", MODE_NONE)

    if mode == MODE_FIND_VIDEO:
        pages = notion_search_by_title(text, limit=10)
        if not pages:
            await update.message.reply_text("Не нашла 😿 Попробуй другое слово или короче запрос.")
            return
        await update.message.reply_text("Нашла вот что:\n\n" + format_pages(pages))
        return

    if mode == MODE_FIND_TAG:
        muscles = context.user_data.get("muscles_list") or notion_get_all_muscles()
        context.user_data["muscles_list"] = muscles

        kind, payload = resolve_muscle_input(text, muscles)

        if kind == "none":
            await update.message.reply_text(
                "Не могу сопоставить мышцу 😿\n"
                "Попробуй другое слово или нажми «Найти хештег» ещё раз, чтобы увидеть список."
            )
            return

        if kind == "many":
            suggest = "\n".join([f"• {m}" for m in payload])
            await update.message.reply_text(
                "Нашла несколько вариантов, уточни пожалуйста (скопируй один из списка):\n\n" + suggest
            )
            return

        muscle = payload
        pages = notion_search_by_tag_exact(muscle, limit=10)
        if not pages:
            await update.message.reply_text(f"По мышце «{muscle}» пока пусто 😿")
            return

        await update.message.reply_text(f"Видео по мышце «{muscle}»:\n\n" + format_pages(pages))
        return

    await update.message.reply_text("Сначала выбери кнопку 👇", reply_markup=main_keyboard())


def run():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing (Render env var BOT_TOKEN)")
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN is missing (Render env var NOTION_TOKEN)")
    if not NOTION_DATABASE_ID:
        raise RuntimeError("NOTION_DATABASE_ID is missing (Render env var NOTION_DATABASE_ID)")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    run()
