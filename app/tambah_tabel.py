import sqlite3
import os

DB_PATH = "data/tarikgaji-live.db"

if not os.path.exists(DB_PATH):
    print(f"❌ Database tidak ditemukan di {DB_PATH}!")
    exit()

try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    print(f"🟢 Berhasil konek ke database: {DB_PATH}")
    print("🔄 Memulai proses UNDO data perusahaan...")

    # 🟢 BALIKIN POSISI: 
    # 1. Jika anak_perusahaan adalah 'Springhill', maka kembalikan perusahaan jadi 'Springhill' (atau 'springhill' kecil)
    # 2. Selain itu, kembalikan nilai dari kolom 'anak_perusahaan' ke kolom 'perusahaan' utama
    cursor.execute("""
        UPDATE pegawai
        SET 
            perusahaan = CASE 
                WHEN anak_perusahaan = 'Springhill' THEN 'springhill'
                ELSE anak_perusahaan
            END,
            anak_perusahaan = '' -- Kosongkan kembali kolom anak perusahaan
        WHERE anak_perusahaan IS NOT NULL AND anak_perusahaan <> ''
    """)

    conn.commit()
    print(f"⏪ BERHASIL UNDO! Sebanyak {cursor.rowcount} data pegawai kembali ke struktur semula.")

except Exception as e:
    print(f"❌ Terjadi error saat undo data: {e}")
finally:
    if 'conn' in locals():
        conn.close()
        print("🔒 Koneksi database ditutup.")