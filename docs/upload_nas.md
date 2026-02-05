Berikut perintah rebuild + jalankan ulang. Pilih sesuai cara kamu pakai:

Kalau pakai `docker run` biasa:
```
docker build -t gajiku-app:latest .
docker stop gajiku-app
docker rm gajiku-app
docker run -d --name gajiku-app ... gajiku-app:latest
```
`rm` perlu supaya container lama diganti dengan image baru.

Kalau pakai `docker compose`:
```
docker compose build --no-cache
docker compose up -d --force-recreate
```
Di compose, `rm` tidak perlu.

Kamu pakai `docker run` atau `docker compose`?

cd /mnt/ssd/hosting && \
docker compose build gajiku-app && \
docker stop gajiku-app && docker rm gajiku-app && \
docker compose up -d gajiku-app && \
docker network connect hosting_web gajiku-app || true && \
docker logs gajiku-app --tail=30

Troubleshooting web down setelah rebuild compose
```
[CRITICAL] WORKER TIMEOUT
[ERROR] Worker was sent SIGKILL! Perhaps out of memory?
```
Ini biasanya karena worker Gunicorn kehabisan memory atau request terlalu lama.
- Cek memory host dan container: `docker stats`, lalu pastikan swap/memory cukup.
- Cek log OOM: `dmesg | tail -n 50` (kalau ada OOM killer).
- Kurangi jumlah worker atau limit concurrency (di env/command Gunicorn).
- Tambah timeout Gunicorn jika request memang lama (mis. export `GUNICORN_TIMEOUT=120`).
- Pastikan tidak ada job berat synchronous yang harus dipindah ke background.

Catatan compose yang dipakai: `C:\Users\Administrator\Downloads\docker-compose (3).yml`.
