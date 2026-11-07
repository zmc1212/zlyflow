#!/usr/bin/env bash
# 服务器端手动回滚(与具体项目无关):基于 deploy.sh 写下的 .deploy-history
#
# 用法(环境变量同 deploy.sh):
#   bash rollback.sh --list                  # 列出最近的部署版本(新→旧)
#   bash rollback.sh                         # 回滚到上一版
#   bash rollback.sh --to 3                  # 回滚到列表中的第 3 条
#   bash rollback.sh --project-dir /opt/zly-ai-video-studio --to 2
set -Eeuo pipefail

PROJECT_DIR="."
TO=""
LIST=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --list) LIST=1; shift ;;
    --to) TO="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

: "${LOCAL_IMAGE:=zly-ai-video-studio:latest}"
: "${SERVICE:=zly-ai-video-studio}"
: "${HEALTH_URL:=http://127.0.0.1:18189/api/health}"
HISTORY_FILE="${PROJECT_DIR}/.deploy-history"

fail() { echo "ERROR: $*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || fail "未找到 docker"
[[ -f "$HISTORY_FILE" ]] || fail "没有部署历史: $HISTORY_FILE"

# 每行格式:时间|镜像ref;输出为最新在前
mapfile -t LINES < <(tac "$HISTORY_FILE")
if [[ ${#LINES[@]} -eq 0 ]]; then
  fail "部署历史为空"
fi

if [[ $LIST -eq 1 ]]; then
  echo "最近部署(新 → 旧;--to N 中的 N 即行号):"
  i=1
  for l in "${LINES[@]}"; do
    echo "  ${i}. ${l%%|*}   ${l#*|}"
    i=$((i + 1))
  done
  exit 0
fi

TO="${TO:-2}"
[[ "$TO" =~ ^[0-9]+$ && "$TO" -ge 1 && "$TO" -le ${#LINES[@]} ]] || fail "--to 需为 1..${#LINES[@]} 的行号(先用 --list 查看)"
entry="${LINES[$((TO - 1))]}"
ref="${entry#*|}"

echo "回滚目标: ${ref}"
docker pull -q "$ref" 2>/dev/null || echo "(使用本地已有镜像)"

cd "$PROJECT_DIR"
docker tag "$ref" "$LOCAL_IMAGE"
echo "$(date '+%F %T')|${ref}" >> "$HISTORY_FILE"
docker compose up -d --no-build --force-recreate "$SERVICE"

echo "等待健康检查(最长 60 秒): ${HEALTH_URL}"
ok=0
for _ in $(seq 1 30); do
  if curl -sf --connect-timeout 3 "${HEALTH_URL}" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [[ $ok -eq 1 ]]; then
  echo "回滚成功,当前运行: ${ref}"
else
  echo "回滚后健康检查未通过,请查看: docker compose logs --tail 100 ${SERVICE}" >&2
  exit 1
fi
