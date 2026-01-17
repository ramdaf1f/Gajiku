import os

class Config:
    APP_VERSION = "v1.2.0-register"
    APP_SECRET = os.environ.get("APP_SECRET", "dev-secret-change-me")

    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "data", "tarikgaji.db"))

    # biaya REG flat per transaksi
    ADMIN_FEE = 15000
    # biaya URG per hari (dipakai untuk hitung (hari_dipakai - hari_berjalan) x fee/hari)
    ADMIN_FEE_PER_DAY = 15000

    # EMAIL/SMTP (gunakan ENV untuk keamanan)
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("SMTP_PASS", "")
    EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
    EMAIL_ADMIN_LIST = [
        e.strip() for e in os.environ.get("EMAIL_ADMIN_LIST", "dramadhani881@gmail.com").split(",") if e.strip()
    ]

    # Admin credentials (bisa override via ENV)
    ADMIN_USERNAME = os.environ.get("ADMIN_USER", "admin")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASS", "admin123")
