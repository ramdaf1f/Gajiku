#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/mnt/ssd/hosting/tarikgaji-app"
CONTAINER_NAME="tarikgaji-app"
IMAGE_NAME="hosting-tarikgaji-app"
PORT="5001"
TZ="Asia/Jakarta"
DB_PATH_HOST="$APP_DIR/data/tarikgaji.db"
DB_PATH_CONTAINER="/app/data/tarikgaji.db"
NETWORK_NAME="hosting_web"

cd "$APP_DIR"

# Stop running container (ignore if not running)
docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true

# Backup DB if exists
if [ -f "$DB_PATH_HOST" ]; then
  ts=$(date +%Y%m%d_%H%M%S)
  cp -av "$DB_PATH_HOST" "$APP_DIR/data/tarikgaji.db.bak_$ts"
fi

# Pull latest code (stash data/ changes so DB exports don't block pull)
if [ -d .git ]; then
  had_stash=0
  if ! git diff --quiet -- data || ! git diff --cached --quiet -- data || [ -n "$(git ls-files -o --exclude-standard -- data)" ]; then
    git stash -u -- data >/dev/null 2>&1 || true
    had_stash=1
  fi
  git pull origin main
  if [ "$had_stash" -eq 1 ]; then
    git stash pop >/dev/null 2>&1 || true
  fi
else
  echo "ERROR: $APP_DIR is not a git repo (.git missing)" >&2
  exit 1
fi

# Build image
docker build -t "$IMAGE_NAME" .

# Remove old container if exists
docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true

# Run new container
docker run -d --name "$CONTAINER_NAME" \
  -p "$PORT:$PORT" \
  -e DB_PATH="$DB_PATH_CONTAINER" \
  -e PORT="$PORT" \
  -e TZ="$TZ" \
  -v "$APP_DIR/data:/app/data" \
  -v /etc/localtime:/etc/localtime:ro \
  -v /etc/timezone:/etc/timezone:ro \
  --restart unless-stopped \
  "$IMAGE_NAME"

# Connect to shared network (ignore if already connected or missing)
docker network connect "$NETWORK_NAME" "$CONTAINER_NAME" >/dev/null 2>&1 || true

# Health check
sleep 2
curl -fsS "http://127.0.0.1:$PORT/ping" >/dev/null && echo "Health check OK" || echo "Health check FAILED"

echo "Deploy complete."
