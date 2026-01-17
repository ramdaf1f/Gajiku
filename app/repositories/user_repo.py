from app.db import get_db


def get_user_by_name(name: str):
    db = get_db()
    return db.execute("SELECT * FROM users WHERE name=?", (name,)).fetchone()

def get_user_by_email(email: str):
    db = get_db()
    return db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()


def get_user_by_id(uid: int):
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
