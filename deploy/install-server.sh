#!/usr/bin/env bash
set -euo pipefail

REVISION="${1:?revision is required}"
SOURCE_ARCHIVE="/tmp/minutestrace-source-${REVISION}.tar.gz"
WEB_ARCHIVE="/tmp/minutestrace-web-${REVISION}.tar.gz"
APP_ROOT="/opt/minutestrace"
RELEASE_DIR="${APP_ROOT}/releases/${REVISION}"
WEB_RELEASE_DIR="${APP_ROOT}/web-releases/${REVISION}"

test -f "${SOURCE_ARCHIVE}"
test -f "${WEB_ARCHIVE}"
install -d -m 0755 "${RELEASE_DIR}" "${WEB_RELEASE_DIR}/minutestrace" "${APP_ROOT}/data/uploads"
tar -xzf "${SOURCE_ARCHIVE}" -C "${RELEASE_DIR}"
tar -xzf "${WEB_ARCHIVE}" -C "${WEB_RELEASE_DIR}/minutestrace"

if [ ! -x "${APP_ROOT}/venv/bin/python" ]; then
  /opt/py312/bin/python3.12 -m venv "${APP_ROOT}/venv"
fi
"${APP_ROOT}/venv/bin/python" -m pip install --disable-pip-version-check -r "${RELEASE_DIR}/backend/requirements.txt"

if [ ! -f "${APP_ROOT}/minutestrace.env" ]; then
  DB_PASSWORD="$(openssl rand -hex 24)"
  JWT_SECRET="$(openssl rand -hex 32)"
  DEMO_PASSWORD="$(openssl rand -hex 24)"
  mysql --protocol=socket <<SQL
CREATE DATABASE IF NOT EXISTS minutestrace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'minutestrace'@'127.0.0.1' IDENTIFIED BY '${DB_PASSWORD}';
ALTER USER 'minutestrace'@'127.0.0.1' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON minutestrace.* TO 'minutestrace'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
  LLM_KEY=""
  if [ -r /opt/hospital-v2/hospital-v2.env ]; then
    LLM_KEY="$(sed -n 's/^LLM_API_KEY=//p' /opt/hospital-v2/hospital-v2.env | head -n 1)"
  fi
  umask 077
  {
    printf '%s\n' 'MINUTESTRACE_ENVIRONMENT=production'
    printf 'MINUTESTRACE_DATABASE_URL=mysql+pymysql://minutestrace:%s@127.0.0.1:3306/minutestrace?charset=utf8mb4\n' "${DB_PASSWORD}"
    printf 'MINUTESTRACE_JWT_SECRET=%s\n' "${JWT_SECRET}"
    printf '%s\n' 'MINUTESTRACE_STORAGE_DIR=/opt/minutestrace/data/uploads'
    printf '%s\n' 'MINUTESTRACE_PUBLIC_BASE_URL=http://114.215.186.113/minutestrace/api'
    printf 'MINUTESTRACE_LLM_API_KEY=%s\n' "${LLM_KEY}"
    printf '%s\n' 'MINUTESTRACE_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1'
    printf '%s\n' 'MINUTESTRACE_LLM_MODEL=qwen-plus'
    printf '%s\n' 'MINUTESTRACE_ASR_BASE_URL=https://dashscope.aliyuncs.com/api/v1'
    printf '%s\n' 'MINUTESTRACE_ASR_MODEL=paraformer-v2'
    printf 'MINUTESTRACE_DEMO_PASSWORD=%s\n' "${DEMO_PASSWORD}"
    printf '%s\n' 'MINUTESTRACE_UPLOAD_LIMIT_MB=512'
    printf '%s\n' 'MINUTESTRACE_WORKER_STALE_SECONDS=180'
  } > "${APP_ROOT}/minutestrace.env"
fi

ln -sfn "${RELEASE_DIR}" "${APP_ROOT}/current"
ln -sfn "${WEB_RELEASE_DIR}" "${APP_ROOT}/web"
chown -R www-data:www-data "${APP_ROOT}/data"
chmod 0600 "${APP_ROOT}/minutestrace.env"

install -m 0644 "${RELEASE_DIR}/deploy/minutestrace-api.service" /etc/systemd/system/minutestrace-api.service
install -m 0644 "${RELEASE_DIR}/deploy/minutestrace-worker.service" /etc/systemd/system/minutestrace-worker.service
install -m 0644 "${RELEASE_DIR}/deploy/minutestrace-locations.conf" /etc/nginx/minutestrace-locations.conf

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/etc/nginx/backups/${STAMP}"
install -d -m 0700 "${BACKUP_DIR}"
for site in /etc/nginx/sites-enabled/crossborder /etc/nginx/sites-enabled/domain-https /etc/nginx/sites-enabled/ip-root; do
  if ! grep -q 'minutestrace-locations.conf' "${site}"; then
    cp -a "${site}" "${BACKUP_DIR}/$(basename "${site}")"
    sed -i '/include \/etc\/nginx\/hospital-v2-locations.conf;/a\    include /etc/nginx/minutestrace-locations.conf;' "${site}"
  fi
done

nginx -t
systemctl daemon-reload
systemctl enable --now minutestrace-api.service minutestrace-worker.service
systemctl restart minutestrace-api.service minutestrace-worker.service
systemctl reload nginx

for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18119/health >/dev/null; then
    exit 0
  fi
  sleep 1
done
systemctl --no-pager --full status minutestrace-api.service
exit 1
