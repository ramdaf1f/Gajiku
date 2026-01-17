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

