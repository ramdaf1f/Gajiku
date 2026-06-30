import sqlite3
import os

def jalankan_migrasi():
    # Menggunakan nama database live sesuai info dari lu
    db_path = os.path.join("data", "tarikgaji-live.db")

    if not os.path.exists(db_path):
        print(f"❌ Database tidak ditemukan di path: {db_path}")
        print("Pastikan lu menjalankan script ini dari root folder proyek lu (tempat folder 'data' berada).")
        return

    print(f"🔄 Menghubungkan ke database live: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. Mulai transaksi aman
        cursor.execute("BEGIN TRANSACTION;")

        print("📦 1. Mengubah nama tabel lama (backup)...")
        cursor.execute("ALTER TABLE transactions RENAME TO transactions_old;")

        print("🛠️ 2. Membuat tabel transactions baru dengan Foreign Key ke 'users'...")
        cursor.execute("""
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                tanggal TEXT,
                periode TEXT,
                nominal INTEGER,
                admin_fee INTEGER,
                status TEXT,
                keterangan TEXT,
                rekening_tujuan TEXT,
                rekening_tujuan_label TEXT,
                created_at TEXT,
                product TEXT,
                cancel_until TEXT,
                urg_lock_until TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        print("🚚 3. Memindahkan data transaksi lama ke tabel baru...")
        cursor.execute("""
            INSERT INTO transactions (
                id, user_id, tanggal, periode, nominal, admin_fee, status, 
                keterangan, rekening_tujuan, rekening_tujuan_label, created_at, 
                product, cancel_until, urg_lock_until
            )
            SELECT 
                id, user_id, tanggal, periode, nominal, admin_fee, status, 
                keterangan, rekening_tujuan, rekening_tujuan_label, created_at, 
                product, cancel_until, urg_lock_until 
            FROM transactions_old;
        """)

        print("🗑️ 4. Menghapus tabel backup 'transactions_old'...")
        cursor.execute("DROP TABLE transactions_old;")

        # Simpan permanen jika semua proses sukses
        conn.commit()
        print("✅ MIGRASI BERHASIL! Data live aman dipindahkan dan skema DB sudah diperbaiki.")

    except sqlite3.Error as e:
        # Batalkan semua perubahan jika di tengah jalan ada error
        conn.rollback()
        print(f"❌ GAGAL MIGRASI: {e}")
        print("⚠️ Database live lu otomatis di-rollback ke kondisi semula. Tidak ada data yang hilang.")
    
    finally:
        conn.close()

if __name__ == "__main__":
    jalankan_migrasi()