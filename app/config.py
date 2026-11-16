"""Settings read from environment variables (see .env.example)."""
import os
from zoneinfo import ZoneInfo


def _list(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# LINE userIds allowed to use the bot. Empty = setup mode (bot only replies with your userId).
ALLOWED_USER_IDS = _list("ALLOWED_USER_IDS")

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "expenses.db")
SLIP_DIR = os.path.join(DATA_DIR, "slips")
KEEP_SLIPS = os.environ.get("KEEP_SLIPS", "true").lower() == "true"

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_MODEL_FAST = os.environ.get("CLAUDE_MODEL_FAST", "haiku")    # slip reading, categorizing
CLAUDE_MODEL_SMART = os.environ.get("CLAUDE_MODEL_SMART", "sonnet")  # Q&A, monthly analysis
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "120"))
CLAUDE_CONCURRENCY = int(os.environ.get("CLAUDE_CONCURRENCY", "2"))

TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Bangkok"))
MONTHLY_SUMMARY_DAY = int(os.environ.get("MONTHLY_SUMMARY_DAY", "1"))
MONTHLY_SUMMARY_HOUR = int(os.environ.get("MONTHLY_SUMMARY_HOUR", "9"))

CATEGORIES = [
    "อาหาร",
    "เครื่องดื่ม/กาแฟ",
    "เดินทาง",
    "ช้อปปิ้ง",
    "ของใช้ในบ้าน",
    "บิล/ค่าบริการ",
    "ที่พัก",
    "สุขภาพ",
    "บันเทิง",
    "การศึกษา",
    "โอนให้คน",
    "อื่นๆ",
]
