#!/usr/bin/env bash
# GitBlit → Gitea 定时同步:团队继续 push 老 GitBlit 地址(无感迁移),
# 本脚本把增量提交以正常 git push 推进 Gitea,push 事件必然触发 Actions CI。
#
# 为什么不用 Gitea 自带镜像:镜像同步不触发 push 钩子/Actions(已知行为),
# 因此这里用「裸镜像缓存 + push --mirror」实现同等效果且触发确定。
#
# 用法:依赖同目录 .env(setup.sh 生成后,补充 GITBLIT_*/SYNC_REPOS 配置),
#       由 systemd timer(见 systemd/gitblit-sync.timer)或 cron 每分钟调用:
#         bash gitblit-sync.sh
# 注意:本地缓存目录 .sync-cache 内嵌 GitBlit 凭据(700 权限),只放在 CI 服务器上。
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
[[ -f .env ]] && { # shellcheck disable=SC1091
  set -a; . ./.env; set +a; }

log() { echo "[gitblit-sync $(date '+%F %T')] $*"; }
die() { echo "[gitblit-sync $(date '+%F %T')] 错误: $*" >&2; exit 1; }

: "${GITBLIT_BASE:?请在 .env 配置 GITBLIT_BASE(如 http://124.70.90.30:8899/r)}"
: "${SYNC_REPOS:?请在 .env 配置 SYNC_REPOS(空格分隔的 GitBlit 仓库名列表)}"
: "${GITEA_ADMIN_USER:?请在 .env 配置 GITEA_ADMIN_USER}"
: "${GITEA_ADMIN_PASSWORD:?请在 .env 配置 GITEA_ADMIN_PASSWORD}"

[[ -z "${GITBLIT_USER:-}" || -n "${GITBLIT_PASSWORD:-}" ]] \
  || die "GITBLIT_USER 已设置但 GITBLIT_PASSWORD 为空(GitBlit 私有仓库需要密码;匿名可读则两个都留空)"

GITEA_ORG="${GITEA_ORG:-zly}"
DOMAIN="${GITEA_DOMAIN:-127.0.0.1}"
PORT="${GITEA_PORT:-3080}"
API="http://${DOMAIN}:${PORT}/api/v1"
GITEA_GIT="http://${GITEA_ADMIN_USER}:${GITEA_ADMIN_PASSWORD}@${DOMAIN}:${PORT}/${GITEA_ORG}"
CACHE_DIR="${SYNC_CACHE_DIR:-${SCRIPT_DIR}/.sync-cache}"
mkdir -p "$CACHE_DIR" && chmod 700 "$CACHE_DIR"
export GIT_TERMINAL_PROMPT=0   # 防止凭据错误时交互挂起(systemd 下必须)

for repo in $SYNC_REPOS; do
  log "== ${repo} =="

  # 1) Gitea 侧仓库不存在则自动创建(空仓、私有;已存在则忽略)
  code="$(curl -s -o /dev/null -w '%{http_code}' -u "${GITEA_ADMIN_USER}:${GITEA_ADMIN_PASSWORD}" \
    -X POST -H 'Content-Type: application/json' \
    -d "{\"name\":\"${repo}\",\"private\":true,\"auto_init\":false}" \
    "${API}/orgs/${GITEA_ORG}/repos" || true)"
  case "$code" in
    201) log "  Gitea 已自动创建 ${GITEA_ORG}/${repo}" ;;
    409) log "  Gitea 仓库已存在" ;;
    *)   log "  警告: 创建/确认仓库返回 HTTP ${code}(仓库已存在时可忽略)" ;;
  esac

  # 2) 本地裸镜像缓存:首次全量 clone,此后增量 fetch
  mirror="${CACHE_DIR}/${repo}.git"
  if [[ ! -d "$mirror" ]]; then
    if [[ -n "${GITBLIT_USER:-}" ]]; then
      proto="${GITBLIT_BASE%%://*}"
      rest="${GITBLIT_BASE#*://}"
      src="${proto}://${GITBLIT_USER}:${GITBLIT_PASSWORD}@${rest}/${repo}.git"
    else
      src="${GITBLIT_BASE}/${repo}.git"
    fi
    log "  首次从 GitBlit 全量克隆 ..."
    git clone --mirror "$src" "$mirror" || die "从 GitBlit 克隆 ${repo} 失败(检查 GITBLIT_BASE/账号权限)"
  else
    git -C "$mirror" fetch --prune origin || die "从 GitBlit 拉取 ${repo} 增量失败"
  fi

  # 3) 推送到 Gitea(有新提交才会产生实际 push,push 事件触发 CI)
  if git -C "$mirror" push --mirror "${GITEA_GIT}/${repo}.git" 2>&1 | grep -q 'Everything up-to-date'; then
    log "  无新提交"
  else
    log "  已同步到 Gitea,push 事件将触发 CI"
  fi
done

log "同步完成"
