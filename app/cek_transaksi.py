import sqlite3

def get_db():
    conn = sqlite3.connect("data/tarikgaji-live.db")
    conn.row_factory = sqlite3.Row  # Biar bisa dipanggil pake nama kolom
    return conn

# ===== SEKARANG KITA TEST PANGGIL & PRINT DI SINI =====
try:
    db = get_db()
    cursor = db.cursor()
    
    # Ambil 1 data admin teratas buat di-test
    cursor.execute("SELECT * FROM admins LIMIT 1")
    row = cursor.fetchone()
    
    if row:
        print("--- BERHASIL KONEK DB & AMBIL DATA ---")
        # 1. Kita print semua key / nama kolom yang terdeteksi
        print("Nama-nama Kolom di DB:", list(row.keys()))
        print("-" * 40)
        
        # 2. Kita test ambil value kolom 'company' atau nama lain
        # Kita pakai dict(row) biar kelihatan semua pasangan kolom dan isinya
        print("Isi Data Mentah:", dict(row))
    else:
        print("Konek berhasil, tapi tabel 'admins' lu kosong, bro!")
        
    db.close()

except Exception as e:
    print(f"Waduh Error, Bro! Penyebabnya: {e}")