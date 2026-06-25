import sqlite3
import os
from werkzeug.security import generate_password_hash

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
db_path = os.path.join(PROJECT_ROOT, "data", "tarikgaji-live.db")

print(f"Mencoba membuka database di: {db_path}\n")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Data Superadmin
super_email = "superadmin@example.com"
super_password = "superadmin123"
super_name = "Super Admin"

# Enkripsi password
password_terenkripsi = generate_password_hash(super_password)

# Cek apakah akun superadmin@example.com sudah ada
cursor.execute("SELECT * FROM admins WHERE email = ?", (super_email,))
exist = cursor.fetchone()

if not exist:
    # 🔥 FIX: Kolom company diisi 'Superadmin' (Bukan NULL) biar lolos NOT NULL constraint
    cursor.execute("""
        INSERT INTO admins (name, email, password_hash, role, company, status_aktif, no_telp, created_at) 
        VALUES (?, ?, ?, 'superadmin', 'Superadmin', 1, '-', datetime('now'))
    """, (super_name, super_email, password_terenkripsi))
    print(f"🚀 BERHASIL: Akun Superadmin baru telah dibuat!")
else:
    # 🔥 FIX: Pas UPDATE juga kita set company ke 'Superadmin'
    cursor.execute("""
        UPDATE admins 
        SET password_hash = ?, role = 'superadmin', name = ?, status_aktif = 1, company = 'Superadmin'
        WHERE email = ?
    """, (password_terenkripsi, super_name, super_email))
    print(f"🔒 REFRESHED: Akun Superadmin berhasil diperbarui!")

conn.commit()
conn.close()

print("\n🔥 Selesai bro! Akun Superadmin aman dari NOT NULL constraint!")