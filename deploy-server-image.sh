#!/usr/bin/env bash
set -Eeuo pipefail

readonly SERVICE="zly-ai-video-studio"
readonly HEALTH_URL="http://127.0.0.1:18189/api/health"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -gt 0 ]]; then
  ARCHIVE="$1"
elif [[ -f "${SCRIPT_DIR}/packages/zly-ai-video-studio_latest.tar" ]]; then
  ARCHIVE="${SCRIPT_DIR}/packages/zly-ai-video-studio_latest.tar"
else
  ARCHIVE="${SCRIPT_DIR}/zly-ai-video-studio_latest.tar"
fi
readonly ARCHIVE

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "Docker is not installed or not on PATH."
docker compose version >/dev/null 2>&1 || fail "Docker Compose Plugin is unavailable."
command -v curl >/dev/null 2>&1 || fail "curl is not installed or not on PATH."
[[ -f "${SCRIPT_DIR}/compose.yaml" ]] || fail "compose.yaml was not found next to this script."
[[ -f "${ARCHIVE}" ]] || fail "Image archive was not found: ${ARCHIVE}"

cd "${SCRIPT_DIR}"

echo "[1/4] Loading image archive: ${ARCHIVE}"
docker load -i "${ARCHIVE}"

echo "[2/4] Recreating ${SERVICE} without rebuilding"
docker compose up -d --no-build --force-recreate "${SERVICE}"

echo "[3/4] Container status"
docker compose ps "${SERVICE}"

echo "[4/4] Waiting for ${HEALTH_URL}"
for attempt in $(seq 1 15); do
  if health_payload="$(curl --fail --silent --show-error --connect-timeout 3 "${HEALTH_URL}")"; then
    echo "Deployment completed. Health response: ${health_payload}"
    exit 0
  fi
  sleep 2
done

echo "Health check did not succeed within 30 seconds. Recent container logs:" >&2
docker compose logs --tail 100 "${SERVICE}" >&2 || true
exit 1
