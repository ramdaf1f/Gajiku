import sqlite3
import os

# 📁 SESUAIKAN PATH INI dengan lokasi database SQLite lu (misal: 'data/tarikgaji-live.db')
DB_PATH = "data/tarikgaji-live.db"

def cek_struktur_sqlite():
    if not os.path.exists(DB_PATH):
        print(f"❌ Waduh, file database gak ketemu di path: {DB_PATH}")
        print("Coba cek lagi posisinya ya, bro!")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 1. Ambil semua daftar nama tabel di SQLite
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        if not tables:
            print("ℹ️ Database berhasil dibuka, tapi kosong (gak ada tabelnya), bro!")
            return
            
        print("=" * 50)
        print(f"📊 STRUKTUR DATABASE SQLITE: {DB_PATH}")
        print("=" * 50)
        
        # 2. Looping tiap tabel untuk ambil info field / kolomnya
        for table in tables:
            table_name = table[0]
            print(f"\n📂 TABEL: [{table_name}]")
            print("-" * 40)
            print(f"{'Nama Field / Kolom':<25} | {'Tipe Data':<15}")
            print("-" * 40)
            
            # PRAGMA table_info itu bawaan SQLite buat intip struktur kolom
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()
            
            for col in columns:
                # col[1] = nama kolom, col[2] = tipe data
                col_name = col[1]
                col_type = col[2] if col[2] else "TEXT/BLOB"
                print(f"{col_name:<25} | {col_type:<15}")
                
            print("-" * 40)
            
        conn.close()
        
    except Exception as e:
        print(f"❌ Terjadi error pas baca SQLite: {e}")

if __name__ == "__main__":
    cek_struktur_sqlite()