## Temuan limit break (M hilan)

### Ringkasan
- Di riwayat admin terlihat total transaksi M hilan melebihi plafon (gaji 4.000.000, plafon 2.000.000).
- Akar masalah: data transaksi terbelah ke dua akun `users` berbeda untuk orang yang sama.

### Bukti DB (sebelum perbaikan)
Users:
- `users.id=503`, email `mhilan@gmail.com`, created_at `2025-11-17T03:08:43`
- `users.id=777`, email `NULL`, created_at `2025-11-18T23:20:47`

User account (formal):
- `user_accounts.email=mhilan@gmail.com`, created_at `2025-11-18T23:20:36`

Transaksi:
- Mayoritas transaksi Des 2025 - Jan 2026 tercatat pada `user_id=777` (email NULL).
- Transaksi 12-01-2026 tercatat pada `user_id=503` (email valid).

Implikasi:
- Limit dihitung by `user_id`, sehingga transaksi pada `user_id=777` tidak dihitung saat login menggunakan akun email (`user_id=503`).

### Analisis penyebab
- Baris `users` dengan email NULL dibuat setelah akun formal terbentuk.
- Di kode saat ini, `INSERT INTO users` selalu mengisi email (berdasarkan `pegawai.email`).
- Indikasi kuat data `users` tanpa email berasal dari flow lama/import manual/seed, bukan dari flow kode saat ini.

## Tindakan perbaikan

### 1) Patch logic limit
- Perhitungan `total_sukses` sekarang berdasarkan email pegawai (join `transactions -> users` by email),
  sehingga duplikat `user_id` dengan email sama tidak bisa lolos limit.
- Jika email kosong, fallback tetap ke `user_id`.

Lokasi:
- `app/routes/web.py` (fungsi `compute_limits`)

### 2) Perapihan data
- Merge transaksi `user_id=777` -> `user_id=503`
- Hapus `users.id=777` (email NULL)

## Audit users dengan email NULL

### Sesudah perapihan lanjutan
Total users email NULL: 0

Tindakan:
- Hapus user demo `id=47` dan `id=50` beserta transaksinya.
- Merge `id=303` -> user email `baim@gmail.com` (`users.id=54`).
