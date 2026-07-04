import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "..", "data", "tarikgaji-live.db")


def add_column_if_not_exists(conn, table_name, column_name, column_def):
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")]
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
        conn.commit()


if not os.path.exists(DB_PATH):
    print(f"❌ Database tidak ditemukan di {DB_PATH}!")
    exit()

try:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    print(f"🟢 Berhasil konek ke database: {DB_PATH}")

    add_column_if_not_exists(conn, "admins", "role", "TEXT DEFAULT 'admin'")

    email = input("Masukkan email admin yang ingin diubah role-nya: ").strip()
    if not email:
        print("Email tidak boleh kosong.")
        exit()

    print("Pilih role:")
    print("1. admin")
    print("2. superadmin")
    pilihan = input("Masukkan pilihan (1/2): ").strip()

    if pilihan == "1":
        role = "admin"
    elif pilihan == "2":
        role = "superadmin"
    else:
        print("Pilihan tidak valid.")
        exit()

    admin = cursor.execute(
        "SELECT id, name, email, role FROM admins WHERE LOWER(email)=LOWER(?)",
        (email,),
    ).fetchone()

    if not admin:
        print(f"❌ Admin dengan email '{email}' tidak ditemukan.")
        exit()

    cursor.execute("UPDATE admins SET role=? WHERE id=?", (role, admin["id"]))
    conn.commit()

    print(f"✅ Berhasil mengubah role admin '{admin['name']}' ({admin['email']}) menjadi {role}")

except Exception as e:
    print(f"❌ Terjadi error: {e}")
finally:
    if 'conn' in locals():
        conn.close()
        print("🔒 Koneksi database ditutup.")