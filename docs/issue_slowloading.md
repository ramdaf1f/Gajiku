# Investigasi Slow Loading (Gajiku)

## Ringkasan Temuan Awal
- Polling tiap 1 detik ke `/api/tx_status` berpotensi jadi bottleneck besar. Endpoint ini bisa mengirim email SMTP secara sinkron sehingga request menumpuk.
- `send_email_async` memanggil `_send_email_sync` yang tidak ada, jadi async tidak berjalan dan fallback tetap sync (blocking).
- Banyak query admin pakai `tanggal/status/product` tanpa index khusus. Saat transaksi besar, ini memicu full scan.
- Join `LOWER(p.email)=LOWER(u.email)` menghambat index dan memperlambat query admin/export.
- Model `users` unik di `name`, bukan email, sehingga rawan konflik nama dan data tersambung salah (logic “kusut”).

## Bukti Lokasi Kode
- Polling dashboard: `templates/dashboard.html:104-121`
- Endpoint API & email: `app.py:894-942`, `app.py:373`
- send_email_async: `app.py:360`
- Query transaksi berbasis tanggal: `app.py:1287`, `app.py:1292`, `app.py:1298`, `app.py:1378`
- Index transaksi yang ada: `app.py:168-171`
- Join LOWER email: `app.py:835`, `app.py:1357`, `app.py:1369`, `app.py:1433`
- Unik users pakai name: `app.py:110`, `app.py:457`, `app.py:1635`

## Catatan DB Lokal (snapshot)
- tables: admins, pegawai, pegawai_archive, transactions, user_accounts, users
- counts: transactions=0, users=0, pegawai=155, user_accounts=81
- indexes transaksi hanya `(user_id, periode, ...)`

## Dugaan Penyebab Utama Lambat
1) Polling sangat rapat + email sync di endpoint API.
2) Aplikasi dijalankan single-thread (`app.run(... threaded=False ...)`), request menumpuk.
3) Index DB belum mendukung query paling sering di admin dashboard.
4) Join case-insensitive menonaktifkan optimisasi index.

## Rekomendasi Prioritas
1) Pindahkan pengiriman email ke background job/queue dan hilangkan side-effect dari `/api/tx_status`.
2) Ubah polling jadi interval lebih besar atau gunakan long-polling/websocket.
3) Tambahkan index untuk `transactions(tanggal)`, `transactions(status)`, `transactions(product)` atau komposit sesuai query.
4) Normalisasi email di tabel agar join tanpa `LOWER`.
5) Ganti uniqueness `users` ke email (atau email+pegawai_id) untuk mencegah data “silang”.

## Pertanyaan Lanjutan
- Halaman mana yang paling lambat? dashboard user / admin dashboard / login / export?
- Apakah ada banyak transaksi on-proses yang memicu email?
- Deployment pakai `app.py` langsung atau WSGI server?
