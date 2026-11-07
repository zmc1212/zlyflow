#!/usr/bin/env bash
# 服务器端通用部署脚本(CI 自动调用,也可手动执行;与具体项目无关)
#
# 用法(环境变量 + 可选参数):
#   DEPLOY_IMAGE=<registry>/<org>/<repo>:<tag> \
#   [REGISTRY_USER=...] [REGISTRY_PASSWORD=...] \
#   [LOCAL_IMAGE=zly-ai-video-studio:latest] [SERVICE=zly-ai-video-studio] \
#   [HEALTH_URL=http://127.0.0.1:18189/api/health] \
#   bash deploy.sh [--project-dir /opt/zly-ai-video-studio] [--no-rollback]
#
# 行为:登录仓库(如提供凭据)→ 拉取镜像 → 本地打 tag(与 compose.yaml 的 image 一致)
#       → compose 重建目标服务 → 健康检查;失败自动回滚上一版。
#       每次部署记录到 <项目目录>/.deploy-history(保留最近 20 条),供 rollback.sh 使用。
set -Eeuo pipefail

PROJECT_DIR="."
AUTO_ROLLBACK=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --no-rollback) AUTO_ROLLBACK=0; shift ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

: "${DEPLOY_IMAGE:?必须通过环境变量提供 DEPLOY_IMAGE(如 124.70.90.30:3080/zly/zly-ai-video-studio:abc12345)}"
LOCAL_IMAGE="${LOCAL_IMAGE:-zly-ai-video-studio:latest}"
SERVICE="${SERVICE:-zly-ai-video-studio}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:18189/api/health}"
HISTORY_FILE="${PROJECT_DIR}/.deploy-history"
KEEP=20

fail() { echo "ERROR: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "未找到 docker"
docker compose version >/dev/null 2>&1 || fail "未找到 docker compose 插件"
command -v curl >/dev/null 2>&1 || fail "未找到 curl"

cd "$PROJECT_DIR"
[[ -f compose.yaml || -f docker-compose.yaml || -f docker-compose.yml ]] || fail "项目目录缺少 compose.yaml: $PROJECT_DIR"

echo "[1/5] 登录镜像仓库(如提供凭据)..."
if [[ -n "${REGISTRY_USER:-}" && -n "${REGISTRY_PASSWORD:-}" ]]; then
  echo "${REGISTRY_PASSWORD}" | docker login --username "${REGISTRY_USER}" --password-stdin >/dev/null
fi

echo "[2/5] 拉取镜像: ${DEPLOY_IMAGE}"
docker pull -q "${DEPLOY_IMAGE}"

echo "[3/5] 本地标记为 ${LOCAL_IMAGE} 并记录版本 ..."
docker tag "${DEPLOY_IMAGE}" "${LOCAL_IMAGE}"
mkdir -p "$(dirname "$HISTORY_FILE")"
echo "$(date '+%F %T')|${DEPLOY_IMAGE}" >> "$HISTORY_FILE"
tail -n "$KEEP" "$HISTORY_FILE" > "${HISTORY_FILE}.tmp" && mv "${HISTORY_FILE}.tmp" "$HISTORY_FILE"

compose_up() {
  docker compose up -d --no-build --force-recreate "$SERVICE"
}
compose_up

echo "[4/5] 等待健康检查(最长 60 秒): ${HEALTH_URL}"
ok=0
for _ in $(seq 1 30); do
  if curl -sf --connect-timeout 3 "${HEALTH_URL}" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done

if [[ $ok -eq 1 ]]; then
  echo "[5/5] 部署成功,健康响应: $(curl -sf --connect-timeout 3 "${HEALTH_URL}" || true)"
  echo "当前版本: ${DEPLOY_IMAGE}"
  exit 0
fi

echo "健康检查未通过,服务最近日志:" >&2
docker compose logs --tail 100 "$SERVICE" >&2 || true

if [[ $AUTO_ROLLBACK -eq 0 ]]; then
  fail "部署失败(已按要求关闭自动回滚)"
fi

# 历史里最后一行是本次尝试,倒数第二行即上一版
prev="$(tail -n 2 "$HISTORY_FILE" | head -n1 | cut -d'|' -f2 || true)"
if [[ -z "$prev" || "$prev" == "$DEPLOY_IMAGE" ]]; then
  fail "没有可回滚的上一版,请人工处理"
fi

echo ">>> 自动回滚到上一版: ${prev}"
docker pull -q "$prev" 2>/dev/null || true   # 本地已有该镜像时忽略拉取失败
docker tag "$prev" "$LOCAL_IMAGE"
compose_up
ok=0
for _ in $(seq 1 30); do
  if curl -sf --connect-timeout 3 "${HEALTH_URL}" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [[ $ok -eq 1 ]]; then
  echo "回滚完成,已恢复上一版(部署仍判定为失败)。"
else
  echo "回滚后健康检查仍未通过,需要人工介入!" >&2
fi
exit 1
