# Architecture (Target)

## Objectives
- Modularitas tinggi, mudah di-scale dan di-maintain.
- Beban berat dijalankan async (email, export, notifikasi).
- Observability siap produksi (log terstruktur, metrics).

## High-Level Diagram
```
[Client UI]
    |
    v
[Routes / Blueprints] -> [Services] -> [Repositories] -> [SQLite / Postgres]
                |               |
                |               +-> [Caching]
                |
                +-> [Async Tasks Queue] -> [SMTP / Notifications]
```

## Components
- `app/routes`: controller HTTP, validasi input, response.
- `app/services`: business logic + aturan talangan.
- `app/repositories`: akses data, query SQL terpusat.
- `app/models`: schema dan mapping data.
- `app/tasks`: background job (email, export, laporan).
- `app/utils`: helper umum (format, tanggal, logging).

## Data Flow
1) Request masuk ke route.
2) Route memanggil service.
3) Service mengambil/menyimpan data lewat repository.
4) Pekerjaan berat dikirim ke queue.
5) Response segera kembali ke user.

## Database Strategy
- Index sesuai pola query utama (tanggal/status/periode).
- Normalisasi email agar join tanpa `LOWER()`.
- Migrasi terkontrol (SQLAlchemy + Alembic atau skrip migrasi manual).

## Observability
- Log JSON dengan request id.
- Metrics: latency endpoint, antrian job, error rate.

## Security
- Secrets via env vars.
- Password hashing standar.
- Admin area dilindungi RBAC.

## Deployment
- Gunakan WSGI server (gunicorn/uwsgi).
- Jalankan worker async terpisah.
