Saya sedang mengerjakan aplikasi finansial “Tarik Gaji / Dana Talangan” dan memilih arsitektur HYBRID (NAS + Shared Hosting) dengan tujuan meningkatkan perceived speed tanpa memindahkan database live ke hosting publik. Kondisi & Infrastruktur Saat Ini Backend berjalan di NAS Armbian (STB ARM mod). Backend stack: Python (Flask-style), Gunicorn, Docker. Database utama: SQLite (authoritative, live, write). Internet rumah < 50 Mbps. Akses publik menggunakan Cloudflared Tunnel (HTTPS). Shared hosting (cPanel, non-VPS) digunakan hanya untuk frontend & asset statik. Docker tidak dijalankan di shared hosting. Prinsip Arsitektur Shared hosting tidak menyimpan DB utama. Semua transaksi finansial write ke backend NAS. NAS tidak melayani asset statik. Beban berat (email, laporan, export) dijalankan async. API response kecil & cepat (<300–500ms). Siap migrasi ke VPS Linux di masa depan tanpa rewrite besar. Masalah yang Sedang Dihadapi Aplikasi sering terasa lemot di sisi user. Ingin memastikan apakah bottleneck berasal dari: Logic / desain API Kinerja NAS (ARM, SQLite, concurrency) Arsitektur distribusi (frontend vs backend)

“terasa lemot” biasanya bukan cuma 1 penyebab—sering gabungan: latency jaringan + Cloudflared + cold start/proses Python + SQLite locking + desain endpoint. Cara paling cepat mengunci penyebabnya: ukur tiap hop dulu, baru optimasi yang tepat.

Berikut pendekatan yang praktis (dan cocok dengan prinsip HYBRID kamu).

1) Petakan “lemot”-nya: lemot di apa persis?

Pecah waktu request jadi 4 bagian:

DNS + TLS + TTFB (browser → Cloudflare → tunnel → NAS)

Waktu eksekusi app (Flask/Gunicorn)

Waktu DB (SQLite)

Waktu render frontend (shared hosting, JS bundle, asset)

Cara ukur cepat (tanpa alat rumit)

DevTools → Network di browser:

Lihat TTFB dan Content Download.

Jika TTFB tinggi → masalah di backend / tunnel / NAS / DB.

Jika TTFB rendah tapi load total tinggi → masalah di frontend/assets (bundle besar, render berat, blocking JS).

Jalankan juga 2 tes pembanding:

Dari LAN (akses backend NAS langsung IP lokal) vs dari publik via tunnel
Kalau LAN cepat tapi publik lambat → tunnel/jaringan/handshake dominan.

Endpoint “kosong”:

/ping yang cuma return {"ok":true,"ts":...} tanpa DB

/health/db yang hanya SELECT 1
Ini langsung membedakan jaringan/tunnel vs DB/logic.

Target bagus untuk UX:

/ping publik: ideal < 150–250ms (tergantung ISP), masih oke kalau < 400ms.

Endpoint transaksi kecil: kamu target 300–500ms itu realistis kalau DB tidak ke-lock dan payload kecil.

2) Bottleneck paling umum di arsitektur kamu
A) Cloudflared Tunnel + internet rumah <50 Mbps

Gejala: TTFB naik turun, kadang “nyangkut” walau CPU NAS tidak tinggi.
Penyebab: jalur publik selalu melewati edge Cloudflare + tunnel; ditambah uplink rumah (biasanya upload jauh lebih kecil).

Mitigasi cepat

Pastikan frontend di shared hosting hanya hit API untuk data yang perlu, jangan “chatty” (banyak request kecil).

Tambahkan cache untuk response read-only (mis. daftar produk, konfigurasi, FAQ, master data).

Gunakan compression (gzip/br) untuk JSON.

Kurangi roundtrip: gabungkan endpoint yang sering dipanggil beruntun.

B) Gunicorn concurrency di ARM + Docker

Gejala: request menumpuk saat beberapa user bersamaan, latensi melonjak, tapi sekali request selesai, cepat lagi.
Penyebab: worker kurang / konfigurasi worker tidak cocok / event loop tidak ada / overhead container + I/O.

Mitigasi cepat

Pastikan Gunicorn punya cukup worker (rule of thumb CPU-bound: 2*core+1, I/O heavy bisa pakai worker lebih banyak).

Gunakan thread kalau banyak I/O (HTTP calls, DB waits).

Aktifkan access log dengan timing untuk tahu request mana yang lambat.

C) SQLite locking (ini paling sering untuk “transaksi finansial write”)

SQLite bisa kencang, tapi:

Write concurrency terbatas → satu writer bisa memblokir yang lain.

Kalau kamu banyak transaksi write kecil-kecil (insert/update sering), user akan merasa “random lag”.

Mitigasi yang biasanya langsung terasa

Aktifkan WAL mode (Write-Ahead Logging) agar read tidak terlalu keblokir writer.

Set busy_timeout supaya request tidak gagal/nyangkut keras saat lock.

Pastikan query pakai index yang benar (tanpa index, terasa “lemot” walau data belum besar).

Batasi transaksi: kumpulkan beberapa operasi jadi 1 transaction (lebih cepat dan mengurangi lock).

Kalau traffic kamu naik, SQLite tetap bisa dipakai “sementara”, tapi untuk financial app yang mulai ramai, migrasi ke Postgres/MySQL akan jauh lebih stabil untuk concurrency.

D) Desain API: “chatty”, payload besar, dan N+1 query

Gejala: user buka 1 halaman tapi frontend memanggil 10–30 request; atau 1 request return JSON besar.
Mitigasi

Untuk halaman utama, buat 1 endpoint agregasi (mis. /dashboard) yang return data minimal yang dibutuhkan UI.

Pastikan ada pagination dan filter server-side.

Hindari N+1: fetch data relasi dengan query yang efisien.

3) Checklist diagnosis yang paling “high signal”

Kalau kamu lakukan ini, biasanya langsung ketahuan penyebab dominannya.

Logging timing (wajib)

Tambahkan timing di backend:

total request time

waktu DB (per query atau total)

ukuran response (bytes)

status code

Dari sini kamu bisa bikin daftar “Top 10 slow endpoints”.

Monitor NAS (CPU/RAM/IO)

Saat terasa lemot:

CPU 100%? → logic/serialize JSON/crypto hashing/formatting laporan.

I/O tinggi? → SQLite + storage NAS bottleneck.

RAM penuh & swap? → container/worker kebanyakan.

Uji beban kecil (5–20 concurrency)

Cukup pakai tool seperti wrk/hey dari laptop (atau dari VM) untuk:

/ping (tanpa DB)

/health/db

1 endpoint transaksi write

Kalau /ping sudah lambat → fokus tunnel/jaringan/Gunicorn.
Kalau /ping cepat tapi /health/db lambat → fokus SQLite/IO.
Kalau read cepat tapi write lambat → locking/transaction design.

4) Rekomendasi arsitektur HYBRID yang “kerasa” di user (tanpa pindah DB)

Ini yang biasanya memberi perceived speed terbesar:

A) Cache read-only di layer publik

Karena shared hosting tidak bisa Docker, kamu bisa:

Cache di Cloudflare (paling enak): atur endpoint GET tertentu agar bisa di-cache beberapa detik/menit.

Atau cache sederhana di backend (in-memory) untuk master data.

Contoh kandidat cache:

daftar produk/tenor/biaya

konfigurasi UI

“profil ringkas” user (dengan TTL pendek)

B) Pola “submit cepat, proses belakangan”

Untuk transaksi finansial:

Response cepat: “request diterima + id transaksi + status pending”

Proses berat (verifikasi, generate dokumen, email) via async queue.

UI polling / websocket ringan untuk status.

Ini menjaga UX meski NAS/DB sedang sibuk.

C) Kurangi request dari frontend

Gabungkan endpoint

Preload data yang sering dipakai

Hindari render yang memicu call berulang (mis. useEffect tanpa dependency tepat)

5) Agar siap migrasi VPS tanpa rewrite besar

Kalau kamu mau “future-proof” dari sekarang:

Bungkus DB access di layer repo/service (biar migrasi SQLite → Postgres gampang)

Hindari fitur SQLite-specific di business logic

Buat 1 modul “storage/queue/email/report” yang bisa dipindah ke worker di VPS nantinya

Kesimpulan paling mungkin (berdasarkan setup kamu)

Paling sering sumber “terasa lemot” di kasus seperti ini adalah kombinasi:

latency publik via tunnel + internet rumah, dan

SQLite write lock / transaction pattern ketika ada beberapa user/aktivitas bersamaan, dan/atau

API terlalu chatty dari frontend.