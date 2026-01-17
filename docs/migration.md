# Data Migration Notes

Dokumen ini mencatat perubahan skema dan langkah migrasi yang sudah diterapkan di aplikasi.

## 2025-12-31 - Users key: name -> email
### Tujuan
- Hindari konflik data karena `users` sebelumnya unik di `name`.
- Menjadikan `email` sebagai kunci unik yang stabil untuk identitas pegawai.

### Perubahan Skema
- `users.name` tidak lagi unik.
- `users.email` menjadi `UNIQUE`.
- Index baru `idx_users_email`.

### Strategi Migrasi (otomatis saat startup)
1) Deteksi apakah `users` masih punya index unik pada `name` tanpa index unik pada `email`.
2) Ambil semua row `users` lama.
3) Kelompokkan berdasarkan email (case-insensitive):
   - Pilih row pertama sebagai user kanonikal.
   - Semua row duplikat diarahkan ke user kanonikal.
4) Buat ulang tabel `users` dengan skema baru.
5) Salin data user kanonikal.
6) Update `transactions.user_id` yang menunjuk user duplikat.
7) Buat ulang index (`idx_users_name`, `idx_users_email`).

### Dampak
- Login/signin sekarang `UPSERT` berdasarkan `email`, bukan `name`.
- Resiko data “silang” karena nama sama berkurang.

### Catatan Operasional
- Backup `data/tarikgaji.db` sebelum migrasi jika di production.
- Jalankan audit setelah migrasi:
  ```
  python scripts/audit_db.py
  ```

### Referensi Kode
- `app/db.py` (migrasi otomatis `_migrate_users_email_unique`)
- `app/routes/web.py` (UPSERT email)
- `app/repositories/user_repo.py` (lookup user by email)
