from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

PENDING_FILE = DATA_DIR / "pending.json"
APPROVED_FILE = DATA_DIR / "approved.json"
REJECTED_FILE = DATA_DIR / "rejected.json"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "bb1191981954*"
ADMIN_TOKEN = "sKrsFcuKqTGD0v9rMhbSNeNV5cLqrvjBRrPZY0K2DeA10zT5AY"

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "https://querybot.kr",
    "https://www.querybot.kr",
]

RESEND_API_KEY = "re_cC94QKxN_ME7bpRj1ENAWzAqmWeZVjgdp"
RESEND_FROM_EMAIL = "notify@querybot.kr"
ADMIN_NOTIFY_EMAIL = "rladleh0729@naver.com"