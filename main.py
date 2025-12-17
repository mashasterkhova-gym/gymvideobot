{\rtf1\ansi\ansicpg1252\cocoartf2822
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 import os\
from dotenv import load_dotenv\
\
from telegram import (\
    Update,\
    ReplyKeyboardMarkup,\
    KeyboardButton,\
    InlineKeyboardMarkup,\
    InlineKeyboardButton,\
)\
from telegram.ext import (\
    Application,\
    CommandHandler,\
    MessageHandler,\
    ContextTypes,\
    filters,\
)\
\
from notion_client import Client as NotionClient\
\
load_dotenv()\
\
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()\
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()\
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()\
\
PAY_1M_URL = os.getenv("PAY_1M_URL", "https://getcourse.ru/").strip()\
PAY_3M_URL = os.getenv("PAY_3M_URL", "https://getcourse.ru/").strip()\
\
# \uc0\u9989  \u1058 \u1074 \u1086 \u1080  \u1088 \u1077 \u1072 \u1083 \u1100 \u1085 \u1099 \u1077  \u1085 \u1072 \u1079 \u1074 \u1072 \u1085 \u1080 \u1103  \u1089 \u1074 \u1086 \u1081 \u1089 \u1090 \u1074  \u1074  Notion\
PROP_TITLE = "Name"      # Title\
PROP_URL = "Link"        # URL\
PROP_TAGS = "Muscles"    # Multi-select\
PROP_ACTIVE = "Active"   # Checkbox\
\
notion = NotionClient(auth=NOTION_TOKEN)\
\
BTN_FIND_VIDEO = "\uc0\u55357 \u56590  \u1053 \u1072 \u1081 \u1090 \u1080  \u1074 \u1080 \u1076 \u1077 \u1086 "\
BTN_FIND_TAG = "\uc0\u55356 \u57335 \u65039  \u1053 \u1072 \u1081 \u1090 \u1080  \u1093 \u1077 \u1096 \u1090 \u1077 \u1075 "\
BTN_PAY_1M = "\uc0\u55357 \u56499  \u1054 \u1087 \u1083 \u1072 \u1090 \u1080 \u1090 \u1100  \u1082 \u1083 \u1091 \u1073  \u1085 \u1072  1 \u1084 \u1077 \u1089 \u1103 \u1094 "\
BTN_PAY_3M = "\uc0\u55357 \u56499  \u1054 \u1087 \u1083 \u1072 \u1090 \u1080 \u1090 \u1100  \u1082 \u1083 \u1091 \u1073  \u1085 \u1072  3 \u1084 \u1077 \u1089 \u1103 \u1094 \u1072 "\
\
MODE_NONE = None\
MODE_FIND_VIDEO = "find_video"\
MODE_FIND_TAG = "find_tag"\
\
\
def main_keyboard():\
    return ReplyKeyboardMarkup(\
        [\
            [KeyboardButton(BTN_FIND_VIDEO), KeyboardButton(BTN_FIND_TAG)],\
            [KeyboardButton(BTN_PAY_1M), KeyboardButton(BTN_PAY_3M)],\
        ],\
        resize_keyboard=True,\
        one_time_keyboard=False,\
    )\
\
\
def pay_kb(url: str, label: str):\
    if not url:\
        return None\
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)]])\
\
\
def _get_title(page) -> str:\
    prop = page.get("properties", \{\}).get(PROP_TITLE, \{\})\
    title_arr = prop.get("title", [])\
    if not title_arr:\
        return "\uc0\u1041 \u1077 \u1079  \u1085 \u1072 \u1079 \u1074 \u1072 \u1085 \u1080 \u1103 "\
    return "".join(x.get("plain_text", "") for x in title_arr).strip() or "\uc0\u1041 \u1077 \u1079  \u1085 \u1072 \u1079 \u1074 \u1072 \u1085 \u1080 \u1103 "\
\
\
def _get_url(page) -> str:\
    prop = page.get("properties", \{\}).get(PROP_URL, \{\})\
    return (prop.get("url") or "").strip()\
\
\
def _get_tags(page):\
    prop = page.get("properties", \{\}).get(PROP_TAGS, \{\})\
    ms = prop.get("multi_select", []) or []\
    return [x.get("name", "").strip() for x in ms if x.get("name")]\
\
\
def _is_active(page) -> bool:\
    prop = page.get("properties", \{\}).get(PROP_ACTIVE)\
    if not prop:\
        return True\
    if prop.get("type") == "checkbox":\
        return bool(prop.get("checkbox"))\
    return True\
\
\
def notion_search_by_title(query: str, limit: int = 10):\
    q = query.strip()\
    if not q:\
        return []\
\
    res = notion.databases.query(\
        database_id=NOTION_DATABASE_ID,\
        page_size=min(max(limit, 1), 50),\
        filter=\{\
            "and": [\
                \{\
                    "property": PROP_TITLE,\
                    "title": \{"contains": q\},\
                \}\
            ]\
        \},\
    )\
    pages = res.get("results", []) or []\
    pages = [p for p in pages if _is_active(p)]\
    return pages[:limit]\
\
\
def notion_search_by_tag_exact(tag: str, limit: int = 10):\
    """\
    \uc0\u1042 \u1072 \u1078 \u1085 \u1086 : Notion multi_select filter 'contains' \u1090 \u1088 \u1077 \u1073 \u1091 \u1077 \u1090  \u1090 \u1086 \u1095 \u1085 \u1086 \u1075 \u1086  \u1089 \u1086 \u1074 \u1087 \u1072 \u1076 \u1077 \u1085 \u1080 \u1103  \u1079 \u1085 \u1072 \u1095 \u1077 \u1085 \u1080 \u1103  \u1090 \u1077 \u1075 \u1072 .\
    \uc0\u1055 \u1086 \u1101 \u1090 \u1086 \u1084 \u1091  \u1089 \u1102 \u1076 \u1072  \u1087 \u1077 \u1088 \u1077 \u1076 \u1072 \u1105 \u1084  \u1091 \u1078 \u1077  \u1085 \u1086 \u1088 \u1084 \u1072 \u1083 \u1080 \u1079 \u1086 \u1074 \u1072 \u1085 \u1085 \u1099 \u1081  tag \u1080 \u1079  \u1089 \u1087 \u1080 \u1089 \u1082 \u1072  Muscles.\
    """\
    t = tag.strip()\
    if not t:\
        return []\
\
    res = notion.databases.query(\
        database_id=NOTION_DATABASE_ID,\
        page_size=min(max(limit, 1), 50),\
        filter=\{\
            "and": [\
                \{\
                    "property": PROP_TAGS,\
                    "multi_select": \{"contains": t\},\
                \}\
            ]\
        \},\
    )\
    pages = res.get("results", []) or []\
    pages = [p for p in pages if _is_active(p)]\
    return pages[:limit]\
\
\
def notion_get_all_muscles(limit_pages: int = 500):\
    """\
    \uc0\u1057 \u1086 \u1073 \u1080 \u1088 \u1072 \u1077 \u1084  \u1074 \u1089 \u1077  \u1091 \u1085 \u1080 \u1082 \u1072 \u1083 \u1100 \u1085 \u1099 \u1077  \u1079 \u1085 \u1072 \u1095 \u1077 \u1085 \u1080 \u1103  Muscles \u1080 \u1079  \u1073 \u1072 \u1079 \u1099 .\
    \uc0\u1057  \u1087 \u1072 \u1075 \u1080 \u1085 \u1072 \u1094 \u1080 \u1077 \u1081 . \u1052 \u1086 \u1078 \u1085 \u1086  \u1086 \u1075 \u1088 \u1072 \u1085 \u1080 \u1095 \u1080 \u1090 \u1100  \u1087 \u1086  \u1095 \u1080 \u1089 \u1083 \u1091  \u1089 \u1090 \u1088 \u1072 \u1085 \u1080 \u1094  (\u1089 \u1090 \u1088 \u1072 \u1085 \u1080 \u1094  \u1088 \u1077 \u1079 \u1091 \u1083 \u1100 \u1090 \u1072 \u1090 \u1086 \u1074  Notion),\
    \uc0\u1095 \u1090 \u1086 \u1073 \u1099  \u1085 \u1077  \u1091 \u1087 \u1077 \u1088 \u1077 \u1090 \u1100 \u1089 \u1103  \u1074  \u1073 \u1077 \u1089 \u1082 \u1086 \u1085 \u1077 \u1095 \u1085 \u1086 \u1089 \u1090 \u1100  \u1085 \u1072  \u1075 \u1080 \u1075 \u1072 \u1085 \u1090 \u1089 \u1082 \u1080 \u1093  \u1073 \u1072 \u1079 \u1072 \u1093 .\
    """\
    muscles = set()\
    start_cursor = None\
    pages_seen = 0\
\
    while True:\
        kwargs = \{\
            "database_id": NOTION_DATABASE_ID,\
            "page_size": 100,\
        \}\
        if start_cursor:\
            kwargs["start_cursor"] = start_cursor\
\
        res = notion.databases.query(**kwargs)\
        results = res.get("results", []) or []\
\
        for p in results:\
            if not _is_active(p):\
                continue\
            for m in _get_tags(p):\
                if m:\
                    muscles.add(m)\
\
        pages_seen += 1\
        if pages_seen >= limit_pages:\
            break\
\
        if res.get("has_more"):\
            start_cursor = res.get("next_cursor")\
            if not start_cursor:\
                break\
        else:\
            break\
\
    return sorted(muscles, key=lambda x: x.lower())\
\
\
def format_pages(pages):\
    blocks = []\
    for p in pages:\
        title = _get_title(p)\
        url = _get_url(p)\
        tags = _get_tags(p)\
\
        tags_line = (" ".join(tags)).strip()\
        if url:\
            block = f"\'95 \{title\}\\n\{url\}"\
        else:\
            block = f"\'95 \{title\}\\n(\uc0\u1089 \u1089 \u1099 \u1083 \u1082 \u1072  \u1085 \u1077  \u1091 \u1082 \u1072 \u1079 \u1072 \u1085 \u1072 )"\
\
        if tags_line:\
            block += f"\\n\{tags_line\}"\
\
        blocks.append(block)\
\
    return "\\n\\n".join(blocks)\
\
\
def format_muscles_list(muscles):\
    if not muscles:\
        return "\uc0\u1055 \u1086 \u1082 \u1072  \u1089 \u1087 \u1080 \u1089 \u1086 \u1082  \u1084 \u1099 \u1096 \u1094  \u1087 \u1091 \u1089 \u1090 \u1086 \u1081  (\u1080 \u1083 \u1080  \u1074 \u1089 \u1077  \u1079 \u1072 \u1087 \u1080 \u1089 \u1080  \u1085 \u1077 \u1072 \u1082 \u1090 \u1080 \u1074 \u1085 \u1099 )."\
\
    # Telegram limit \uc0\u1087 \u1086  \u1089 \u1086 \u1086 \u1073 \u1097 \u1077 \u1085 \u1080 \u1102  ~4096 \u1089 \u1080 \u1084 \u1074 \u1086 \u1083 \u1086 \u1074 , \u1088 \u1072 \u1079 \u1086 \u1073 \u1100 \u1105 \u1084  \u1085 \u1072  \u1095 \u1072 \u1085 \u1082 \u1080 \
    chunks = []\
    current = "\uc0\u1044 \u1086 \u1089 \u1090 \u1091 \u1087 \u1085 \u1099 \u1077  \u1084 \u1099 \u1096 \u1094 \u1099  \u1074  \u1073 \u1072 \u1079 \u1077 :\\n\\n"\
    for m in muscles:\
        line = f"\'95 \{m\}\\n"\
        if len(current) + len(line) > 3800:\
            chunks.append(current.rstrip())\
            current = ""\
        current += line\
\
    if current.strip():\
        chunks.append(current.rstrip())\
\
    return chunks\
\
\
def resolve_muscle_input(user_text: str, muscles):\
    """\
    \uc0\u1055 \u1086 \u1083 \u1100 \u1079 \u1086 \u1074 \u1072 \u1090 \u1077 \u1083 \u1100  \u1084 \u1086 \u1078 \u1077 \u1090  \u1085 \u1072 \u1087 \u1080 \u1089 \u1072 \u1090 \u1100 :\
    - \uc0\u1090 \u1086 \u1095 \u1085 \u1086 \u1077  \u1085 \u1072 \u1079 \u1074 \u1072 \u1085 \u1080 \u1077 : "\u1071 \u1075 \u1086 \u1076 \u1080 \u1094 \u1099 "\
    - \uc0\u1076 \u1088 \u1091 \u1075 \u1086 \u1077  \u1088 \u1077 \u1075 \u1080 \u1089 \u1090 \u1088 \u1086 \u1074 \u1086 \u1077 : "\u1103 \u1075 \u1086 \u1076 \u1080 \u1094 \u1099 "\
    - \uc0\u1095 \u1072 \u1089 \u1090 \u1100 : "\u1103 \u1075 \u1086 \u1076 "\
    \uc0\u1042 \u1086 \u1079 \u1074 \u1088 \u1072 \u1097 \u1072 \u1077 \u1084 :\
    - ("exact", "\uc0\u1071 \u1075 \u1086 \u1076 \u1080 \u1094 \u1099 ") \u1077 \u1089 \u1083 \u1080  \u1085 \u1072 \u1096 \u1083 \u1080  \u1086 \u1076 \u1080 \u1085  \u1090 \u1086 \u1095 \u1085 \u1099 \u1081 /\u1077 \u1076 \u1080 \u1085 \u1089 \u1090 \u1074 \u1077 \u1085 \u1085 \u1099 \u1081  \u1087 \u1086 \u1076 \u1093 \u1086 \u1076 \u1103 \u1097 \u1080 \u1081 \
    - ("many", [\uc0\u1089 \u1087 \u1080 \u1089 \u1086 \u1082 ]) \u1077 \u1089 \u1083 \u1080  \u1084 \u1085 \u1086 \u1075 \u1086  \u1082 \u1072 \u1085 \u1076 \u1080 \u1076 \u1072 \u1090 \u1086 \u1074 \
    - ("none", []) \uc0\u1077 \u1089 \u1083 \u1080  \u1085 \u1080 \u1095 \u1077 \u1075 \u1086 \
    """\
    q = (user_text or "").strip()\
    if not q:\
        return ("none", [])\
\
    q_low = q.lower()\
\
    # 1) \uc0\u1090 \u1086 \u1095 \u1085 \u1086 \u1077  \u1089 \u1086 \u1074 \u1087 \u1072 \u1076 \u1077 \u1085 \u1080 \u1077  \u1073 \u1077 \u1079  \u1091 \u1095 \u1105 \u1090 \u1072  \u1088 \u1077 \u1075 \u1080 \u1089 \u1090 \u1088 \u1072 \
    for m in muscles:\
        if m.lower() == q_low:\
            return ("exact", m)\
\
    # 2) \uc0\u1095 \u1072 \u1089 \u1090 \u1080 \u1095 \u1085 \u1086 \u1077  \u1089 \u1086 \u1074 \u1087 \u1072 \u1076 \u1077 \u1085 \u1080 \u1077 \
    candidates = [m for m in muscles if q_low in m.lower()]\
    if len(candidates) == 1:\
        return ("exact", candidates[0])\
    if len(candidates) > 1:\
        return ("many", candidates[:20])  # \uc0\u1087 \u1086 \u1082 \u1072 \u1078 \u1077 \u1084  \u1084 \u1072 \u1082 \u1089 \u1080 \u1084 \u1091 \u1084  20, \u1095 \u1090 \u1086 \u1073 \u1099  \u1085 \u1077  \u1079 \u1072 \u1089 \u1087 \u1072 \u1084 \u1080 \u1090 \u1100 \
    return ("none", [])\
\
\
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):\
    context.user_data["mode"] = MODE_NONE\
    await update.message.reply_text(\
        "\uc0\u1055 \u1088 \u1080 \u1074 \u1077 \u1090 ! \u1042 \u1099 \u1073 \u1080 \u1088 \u1072 \u1081  \u1076 \u1077 \u1081 \u1089 \u1090 \u1074 \u1080 \u1077  \u55357 \u56391 ",\
        reply_markup=main_keyboard(),\
    )\
\
\
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):\
    text = (update.message.text or "").strip()\
\
    # --- buttons ---\
    if text == BTN_FIND_VIDEO:\
        context.user_data["mode"] = MODE_FIND_VIDEO\
        await update.message.reply_text("\uc0\u1054 \u1082 ! \u1053 \u1072 \u1087 \u1080 \u1096 \u1080  \u1085 \u1072 \u1079 \u1074 \u1072 \u1085 \u1080 \u1077  (\u1080 \u1083 \u1080  \u1095 \u1072 \u1089 \u1090 \u1100  \u1085 \u1072 \u1079 \u1074 \u1072 \u1085 \u1080 \u1103 ) \u1074 \u1080 \u1076 \u1077 \u1086  \u55357 \u56391 ")\
        return\
\
    if text == BTN_FIND_TAG:\
        context.user_data["mode"] = MODE_FIND_TAG\
\
        # \uc0\u1057 \u1086 \u1073 \u1077 \u1088 \u1105 \u1084  \u1089 \u1087 \u1080 \u1089 \u1086 \u1082  \u1084 \u1099 \u1096 \u1094  \u1080  \u1079 \u1072 \u1082 \u1077 \u1096 \u1080 \u1088 \u1091 \u1077 \u1084  \u1074  user_data (\u1095 \u1090 \u1086 \u1073 \u1099  \u1080 \u1089 \u1087 \u1086 \u1083 \u1100 \u1079 \u1086 \u1074 \u1072 \u1090 \u1100  \u1087 \u1088 \u1080  \u1074 \u1074 \u1086 \u1076 \u1077 )\
        muscles = notion_get_all_muscles()\
        context.user_data["muscles_list"] = muscles\
\
        msgs = format_muscles_list(muscles)\
        for msg in msgs:\
            await update.message.reply_text(msg)\
\
        await update.message.reply_text(\
            "\uc0\u1058 \u1077 \u1087 \u1077 \u1088 \u1100  \u1085 \u1072 \u1087 \u1080 \u1096 \u1080  \u1084 \u1099 \u1096 \u1094 \u1091  (\u1084 \u1086 \u1078 \u1085 \u1086  \u1095 \u1072 \u1089 \u1090 \u1100  \u1089 \u1083 \u1086 \u1074 \u1072 , \u1085 \u1072 \u1087 \u1088 \u1080 \u1084 \u1077 \u1088 : `\u1103 \u1075 \u1086 \u1076 `), \u1080  \u1103  \u1085 \u1072 \u1081 \u1076 \u1091  \u1074 \u1080 \u1076 \u1077 \u1086  \u55357 \u56391 "\
        )\
        return\
\
    if text == BTN_PAY_1M:\
        await update.message.reply_text(\
            "\uc0\u1054 \u1087 \u1083 \u1072 \u1090 \u1072  \u1079 \u1072  1 \u1084 \u1077 \u1089 \u1103 \u1094  \u55357 \u56391 ",\
            reply_markup=pay_kb(PAY_1M_URL, "\uc0\u1054 \u1087 \u1083 \u1072 \u1090 \u1080 \u1090 \u1100  1 \u1084 \u1077 \u1089 \u1103 \u1094 "),\
        )\
        return\
\
    if text == BTN_PAY_3M:\
        await update.message.reply_text(\
            "\uc0\u1054 \u1087 \u1083 \u1072 \u1090 \u1072  \u1079 \u1072  3 \u1084 \u1077 \u1089 \u1103 \u1094 \u1072  \u55357 \u56391 ",\
            reply_markup=pay_kb(PAY_3M_URL, "\uc0\u1054 \u1087 \u1083 \u1072 \u1090 \u1080 \u1090 \u1100  3 \u1084 \u1077 \u1089 \u1103 \u1094 \u1072 "),\
        )\
        return\
\
    # --- search flow ---\
    mode = context.user_data.get("mode", MODE_NONE)\
\
    if mode == MODE_FIND_VIDEO:\
        pages = notion_search_by_title(text, limit=10)\
        if not pages:\
            await update.message.reply_text("\uc0\u1053 \u1077  \u1085 \u1072 \u1096 \u1083 \u1072  \u55357 \u56895  \u1055 \u1086 \u1087 \u1088 \u1086 \u1073 \u1091 \u1081  \u1076 \u1088 \u1091 \u1075 \u1086 \u1077  \u1089 \u1083 \u1086 \u1074 \u1086  \u1080 \u1083 \u1080  \u1082 \u1086 \u1088 \u1086 \u1095 \u1077  \u1079 \u1072 \u1087 \u1088 \u1086 \u1089 .")\
            return\
        await update.message.reply_text("\uc0\u1053 \u1072 \u1096 \u1083 \u1072  \u1074 \u1086 \u1090  \u1095 \u1090 \u1086 :\\n\\n" + format_pages(pages))\
        return\
\
    if mode == MODE_FIND_TAG:\
        muscles = context.user_data.get("muscles_list")\
        if not muscles:\
            muscles = notion_get_all_muscles()\
            context.user_data["muscles_list"] = muscles\
\
        kind, payload = resolve_muscle_input(text, muscles)\
\
        if kind == "none":\
            await update.message.reply_text(\
                "\uc0\u1053 \u1077  \u1084 \u1086 \u1075 \u1091  \u1089 \u1086 \u1087 \u1086 \u1089 \u1090 \u1072 \u1074 \u1080 \u1090 \u1100  \u1084 \u1099 \u1096 \u1094 \u1091  \u55357 \u56895 \\n"\
                "\uc0\u1055 \u1086 \u1087 \u1088 \u1086 \u1073 \u1091 \u1081  \u1076 \u1088 \u1091 \u1075 \u1086 \u1077  \u1089 \u1083 \u1086 \u1074 \u1086  (\u1085 \u1072 \u1087 \u1088 \u1080 \u1084 \u1077 \u1088 : \u1071 \u1075 \u1086 \u1076 \u1080 \u1094 \u1099  / \u1057 \u1087 \u1080 \u1085 \u1072  / \u1050 \u1074 \u1072 \u1076 \u1088 \u1080 \u1094 \u1077 \u1087 \u1089 \u1099 ) "\
                "\uc0\u1080 \u1083 \u1080  \u1085 \u1072 \u1078 \u1084 \u1080  \'ab\u1053 \u1072 \u1081 \u1090 \u1080  \u1093 \u1077 \u1096 \u1090 \u1077 \u1075 \'bb \u1077 \u1097 \u1105  \u1088 \u1072 \u1079 , \u1095 \u1090 \u1086 \u1073 \u1099  \u1091 \u1074 \u1080 \u1076 \u1077 \u1090 \u1100  \u1089 \u1087 \u1080 \u1089 \u1086 \u1082 ."\
            )\
            return\
\
        if kind == "many":\
            suggest = "\\n".join([f"\'95 \{m\}" for m in payload])\
            await update.message.reply_text(\
                "\uc0\u1053 \u1072 \u1096 \u1083 \u1072  \u1085 \u1077 \u1089 \u1082 \u1086 \u1083 \u1100 \u1082 \u1086  \u1074 \u1072 \u1088 \u1080 \u1072 \u1085 \u1090 \u1086 \u1074 , \u1091 \u1090 \u1086 \u1095 \u1085 \u1080  \u1087 \u1086 \u1078 \u1072 \u1083 \u1091 \u1081 \u1089 \u1090 \u1072  (\u1089 \u1082 \u1086 \u1087 \u1080 \u1088 \u1091 \u1081  \u1086 \u1076 \u1080 \u1085  \u1080 \u1079  \u1089 \u1087 \u1080 \u1089 \u1082 \u1072 ):\\n\\n" + suggest\
            )\
            return\
\
        # exact\
        muscle = payload\
        pages = notion_search_by_tag_exact(muscle, limit=10)\
        if not pages:\
            await update.message.reply_text(\
                f"\uc0\u1055 \u1086  \u1084 \u1099 \u1096 \u1094 \u1077  \'ab\{muscle\}\'bb \u1087 \u1086 \u1082 \u1072  \u1087 \u1091 \u1089 \u1090 \u1086  \u55357 \u56895 "\
            )\
            return\
\
        await update.message.reply_text(\
            f"\uc0\u1042 \u1080 \u1076 \u1077 \u1086  \u1087 \u1086  \u1084 \u1099 \u1096 \u1094 \u1077  \'ab\{muscle\}\'bb:\\n\\n" + format_pages(pages)\
        )\
        return\
\
    # If user types something without choosing a mode\
    await update.message.reply_text("\uc0\u1057 \u1085 \u1072 \u1095 \u1072 \u1083 \u1072  \u1074 \u1099 \u1073 \u1077 \u1088 \u1080  \u1082 \u1085 \u1086 \u1087 \u1082 \u1091  \u55357 \u56391 ", reply_markup=main_keyboard())\
\
\
def run():\
    if not BOT_TOKEN:\
        raise RuntimeError("BOT_TOKEN is missing. Put it into .env")\
    if not NOTION_TOKEN:\
        raise RuntimeError("NOTION_TOKEN is missing. Put it into .env")\
    if not NOTION_DATABASE_ID:\
        raise RuntimeError("NOTION_DATABASE_ID is missing. Put it into .env")\
\
    app = Application.builder().token(BOT_TOKEN).build()\
    app.add_handler(CommandHandler("start", start))\
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))\
\
    print("Bot is running...")\
    app.run_polling()\
\
\
if __name__ == "__main__":\
    run()\
}