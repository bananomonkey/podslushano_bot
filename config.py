import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_RAW = os.getenv("ADMIN_ID")
CHANNEL_ID_RAW = os.getenv("CHANNEL_ID")

if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не задана!")
if not ADMIN_ID_RAW:
    raise ValueError("Переменная окружения ADMIN_ID не задана!")
if not CHANNEL_ID_RAW:
    raise ValueError("Переменная окружения CHANNEL_ID не задана!")

ADMIN_ID = int(ADMIN_ID_RAW)

# CHANNEL_ID может быть числовым (-100...) или @username канала
try:
    CHANNEL_ID = int(CHANNEL_ID_RAW)
except ValueError:
    CHANNEL_ID = CHANNEL_ID_RAW

DB_PATH = os.getenv("DB_PATH", "bot_database.db")
SIGNATURE = "\n\n#подслушано"
