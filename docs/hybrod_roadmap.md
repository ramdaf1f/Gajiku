Berikut roadmap bertahap yang paling “high impact” buat arsitektur HYBRID kamu—urutannya sengaja dibuat supaya tiap tahap menghasilkan perbaikan terasa tanpa nunggu migrasi VPS.

Tahap 0 — Definisikan target & baseline (0.5–1 hari)

Output: kamu bisa menunjuk “lemotnya di mana” pakai angka.

Tentukan KPI:

TTFB /ping publik

p95 latency endpoint transaksi

error rate (timeout/5xx)

waktu load halaman utama (LCP)

Buat 3 endpoint test:

GET /ping (no DB)

GET /health/db (SELECT 1)

POST /txn/test (simulasi write kecil, tanpa proses berat)

Aktifkan logging timing per request:

total waktu

waktu DB total

ukuran response

route + status code

Selesai tahap ini, kamu sudah tahu: masalah dominan network/tunnel atau app/DB atau frontend.

Tahap 1 — “Perceived speed” tercepat dari sisi user (1–3 hari)

Output: UI terasa jauh lebih cepat walau backend belum sempurna.

Frontend: kurangi request & payload

Gabungkan request yang beruntun jadi 1 endpoint agregasi (contoh GET /dashboard)

Implement pagination + filter server-side

Pastikan asset statik: cache-control panjang + gzip/brotli (shared hosting biasanya bisa)

Terapkan pola submit cepat, proses belakangan

Saat user klik aksi finansial: backend langsung balas {id, status:"pending"} <300–500ms

Proses berat dipindah async

UI polling status tiap 2–5 detik (atau SSE/WebSocket nanti)

“Cache yang aman”

Cache read-only: master data, konfigurasi, daftar produk/tenor/biaya (TTL 1–10 menit)

Kalau kamu pakai Cloudflare di depan tunnel: cache GET tertentu di edge (paling terasa)

Tahap 2 — Stabilkan backend NAS (2–5 hari)

Output: latency lebih konsisten, tidak “random ngelag” saat ramai.

Gunicorn tuning (umumnya)

Pastikan jumlah worker/thread sesuai karakter beban (I/O vs CPU)

Set timeout wajar, keep-alive, dan limit request size

Pastikan tidak ada “cold start” berat tiap request (import besar, init berulang)

Pisahkan pekerjaan berat dari request thread

Email, laporan, export, PDF, hit API eksternal → async queue

Buat worker terpisah (di NAS juga) agar request thread tetap ringan

Observability ringan

Tambah endpoint metrics internal (count, p95, queue length)

Log slow query (walau SQLite)

Tahap 3 — Rapikan SQLite supaya tahan concurrency (1–4 hari)

Output: write tidak bikin seluruh sistem “seret”.

Konfigurasi SQLite untuk web workload

Aktifkan WAL mode

Set busy_timeout

Pastikan transaksi rapat: banyak operasi digabung 1 transaksi

Index & query hygiene

Index kolom yang sering dipakai filter/sort/join (walau SQLite)

Audit N+1 query (paling sering bikin lambat diam-diam)

Batasi “SELECT *” dan JSON besar

Pola penulisan data

Hindari “write berkali-kali untuk 1 aksi user” (mis. log + update + insert berkali-kali) → gabungkan

Kalau perlu: buat tabel event/ledger append-only (lebih aman & cepat)

Tahap 4 — Perkuat lapisan distribusi (1–3 minggu)

Output: “rasa VPS” tanpa pindah total.

Edge caching + routing

GET publik tertentu di-cache edge (Cloudflare)

Pisahkan subdomain:

app.domain.com → frontend shared hosting

api.domain.com → tunnel ke NAS

Set CORS rapi, cookie/token jelas

Rate limit & proteksi

Limit endpoint sensitif (login, OTP, transaksi)

WAF rule sederhana (kalau pakai Cloudflare)

Monitoring uptime & alert

Ping dari luar (uptime robot)

Alert kalau latency p95 naik atau error rate naik

Tahap 5 — Jalur migrasi ke VPS tanpa rewrite (rencana 1–2 bulan atau saat siap)

Output: kamu bisa pindah bertahap.

Urutan migrasi paling minim risiko:

Pindahkan worker async ke VPS dulu (email/laporan/export)

Pindahkan backend API stateless ke VPS, tapi DB masih di NAS (sementara)

Baru migrasi DB (SQLite → Postgres/MySQL) saat traffic menuntut

Supaya mudah:

Abstraksikan DB layer (repo/service)

Gunakan migration tool (Alembic kalau SQLAlchemy)

Pastikan semua operasi finansial punya idempotency key + audit trail

Checklist deliverable per tahap

Kalau kamu ingin eksekusi rapi, ini “definition of done” singkat:

T0 selesai: ada dashboard kecil (log) yang menunjukkan p50/p95 per endpoint + TTFB /ping

T1 selesai: halaman utama 1–3 request, payload kecil, LCP turun nyata

T2 selesai: endpoint p95 stabil, request tidak ketahan pekerjaan berat

T3 selesai: write tidak memblokir read secara parah, lock jarang bikin spike

T4 selesai: caching aman, proteksi ada, monitoring jalan

T5 siap: modul DB & async sudah “portable”, migrasi bertahap mungkin