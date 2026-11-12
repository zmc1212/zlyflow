#!/usr/bin/env bash
# GitBlit → Gitea 一次性迁移:仓库(全分支/标签/历史)+ 用户(同名账号),为"接管老地址"做准备。
#
# 无感原理:Gitea 组织名 = r(与 GitBlit 的 /r git 上下文同名),迁移后 Gitea 的 clone 地址
#          /r/<仓库>.git 与 GitBlit 老 URL 逐字符相同;切换时 Gitea 接管 8899 端口即完成无感。
#
# 用法(在 CI 服务器 /opt/zly-ci 下,依赖同目录 .env):
#   bash gitblit-migrate.sh                 # 可重复运行(断点续迁:已迁仓库增量 fetch+push,已建用户跳过)
#   bash gitblit-migrate.sh --repos-only    # 只迁仓库,不动用户
# 迁移报告写入 migrate-report.txt(密码哈希不可逆,需重置的账号会在报告与控制台列出)。
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
[[ -f .env ]] || { echo "[migrate] 错误: 缺少 .env(先 cp .env.example .env 并配置)" >&2; exit 1; }
# shellcheck disable=SC1091
set -a; . ./.env; set +a

die_() { echo "[migrate] 错误: $*" >&2; exit 1; }
log() { echo "[migrate] $*"; }
esc_json() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
mask_url() { printf '%s' "$1" | sed 's#://[^@]*@#://***@#'; }

REPOS_ONLY=0
[[ "${1:-}" == "--repos-only" ]] && REPOS_ONLY=1

# ---------- 前置 ----------
: "${GITBLIT_URL:?请在 .env 配置 GITBLIT_URL(如 http://124.70.90.30:8899)}"
: "${GITEA_ADMIN_USER:?请在 .env 配置 GITEA_ADMIN_USER}"
: "${GITEA_ADMIN_PASSWORD:?请在 .env 配置 GITEA_ADMIN_PASSWORD}"
[[ -n "${GITBLIT_ADMIN_USER:-}" && -z "${GITBLIT_ADMIN_PASSWORD:-}" ]] && die_ "GITBLIT_ADMIN_USER 已设置但 GITBLIT_ADMIN_PASSWORD 为空"

GITBLIT_SERVLET="${GITBLIT_SERVLET:-r}"
ORG="${GITEA_ORG:-r}"
DOMAIN="${GITEA_DOMAIN:-127.0.0.1}"
PORT="${GITEA_PORT:-3080}"
API="http://${DOMAIN}:${PORT}/api/v1"
ADMIN_BASIC="${GITEA_ADMIN_USER}:${GITEA_ADMIN_PASSWORD}"
CACHE_DIR="${SCRIPT_DIR}/.migrate-cache"
REPORT="${SCRIPT_DIR}/migrate-report.txt"
PRIVATE="${MIGRATE_REPO_PRIVATE:-false}"

: "${GITBLIT_ADMIN_USER:=}"; : "${GITBLIT_ADMIN_PASSWORD:=}"
: "${GITBLIT_REPOS:=}"; : "${GITBLIT_USERS_CONF:=}"

command -v git >/dev/null || die_ "未找到 git"
command -v curl >/dev/null || die_ "未找到 curl"
curl -sf -u "$ADMIN_BASIC" "${API}/version" >/dev/null || die_ "连不上 Gitea API(${API}),确认 .env 与 docker compose up 状态"
mkdir -p "$CACHE_DIR" && chmod 700 "$CACHE_DIR"
export GIT_TERMINAL_PROMPT=0

: > "$REPORT"
fail_count=0

# GitBlit 拉取 URL(带凭据)
gb_auth() {
  if [[ -n "$GITBLIT_ADMIN_USER" ]]; then
    proto="${GITBLIT_URL%%://*}"; rest="${GITBLIT_URL#*://}"
    printf '%s://%s:%s@%s' "$proto" "$GITBLIT_ADMIN_USER" "$GITBLIT_ADMIN_PASSWORD" "$rest"
  else
    printf '%s' "${GITBLIT_URL%/}"
  fi
}
GB_BASE="$(gb_auth)"
GB_GIT="${GB_BASE%/}/${GITBLIT_SERVLET%/}"

# ---------- 1. 仓库清单 ----------
repos=""
if [[ -n "$GITBLIT_REPOS" ]]; then
  repos="$GITBLIT_REPOS"
  log "使用手工清单: $repos"
else
  log "尝试通过 RPC 自动列举仓库(${GITBLIT_URL%/}/rpc)..."
  rpc_body="$(curl -s -m 15 -u "${GITBLIT_ADMIN_USER}:${GITBLIT_ADMIN_PASSWORD}" "${GITBLIT_URL%/}/rpc?req=LIST_REPOSITORIES" || true)"
  if printf '%s' "$rpc_body" | grep -q '"name"'; then
    repos="$(printf '%s' "$rpc_body" | grep -oE '"name"[[:space:]]*:[[:space:]]*"[^"]+"' | sed 's/.*"name"[[:space:]]*:[[:space:]]*"//; s/"$//' | sed 's/\.git$//' | tr '\n' ' ')"
    log "RPC 列举到仓库: $repos"
  else
    die_ "RPC 不可用(你的 GitBlit 关闭了 rpc.enabled)。请在 .env 的 GITBLIT_REPOS 里手工列出仓库名(空格分隔,不带 .git),重跑本脚本"
  fi
fi
[[ -n "$(printf '%s' "$repos" | tr -d '[:space:]')" ]] || die_ "仓库清单为空"

# ---------- 2. 组织 ----------
code="$(curl -s -o /dev/null -w '%{http_code}' -u "$ADMIN_BASIC" -X POST \
  -H 'Content-Type: application/json' -d "{\"username\":\"${ORG}\",\"visibility\":\"private\"}" \
  "${API}/orgs" || true)"
case "$code" in
  201) log "已创建组织 ${ORG}" ;;
  422|409) log "组织 ${ORG} 已存在" ;;
  *) die_ "创建组织 ${ORG} 失败: HTTP $code" ;;
esac

# ---------- 3. 迁移仓库 ----------
log "开始迁移仓库 ..."
for repo in $repos; do
  repo="${repo%.git}"
  safe="${repo#~}"          # GitBlit 个人仓 ~user/name 展平
  safe="${safe//\//-}"      # 子目录 teamA/app → teamA-app
  [[ "$safe" == "$repo" ]] || log "  名称映射: ${repo} → ${safe}(Gitea 仓库不含斜杠)"

  code="$(curl -s -o /dev/null -w '%{http_code}' -u "$ADMIN_BASIC" -X POST \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"$(esc_json "$safe")\",\"private\":${PRIVATE},\"auto_init\":false}" \
    "${API}/orgs/${ORG}/repos" || true)"
  case "$code" in
    201) log "  Gitea 已创建 ${ORG}/${safe}" ;;
    409) log "  Gitea 仓库已存在(增量续迁)" ;;
    *)   log "  警告: 创建仓库返回 HTTP $code,继续尝试推送" ;;
  esac

  mirror="${CACHE_DIR}/${safe}.git"
  if [[ ! -d "$mirror" ]]; then
    log "  首次全量克隆: $(mask_url "${GB_GIT}/${repo}.git")"
    git clone --mirror "${GB_GIT}/${repo}.git" "$mirror" || { log "  失败: 克隆 ${repo} 出错"; fail_count=$((fail_count+1)); continue; }
  else
    git -C "$mirror" fetch --prune origin || { log "  失败: 拉取 ${repo} 增量出错"; fail_count=$((fail_count+1)); continue; }
  fi

  dst="http://${GITEA_ADMIN_USER}:${GITEA_ADMIN_PASSWORD}@${DOMAIN}:${PORT}/${ORG}/${safe}.git"
  git -C "$mirror" push --mirror "$dst" >/dev/null 2>&1 || { log "  失败: 推送到 Gitea 出错(${safe})"; fail_count=$((fail_count+1)); continue; }

  src_refs="$(git ls-remote "${GB_GIT}/${repo}.git" | wc -l)"
  dst_refs="$(git ls-remote "$dst" | wc -l)"
  if [[ "$src_refs" -eq "$dst_refs" ]]; then
    log "  完成: ${ORG}/${safe}(引用数一致: ${dst_refs})"
  else
    log "  警告: ${ORG}/${safe} 引用数不一致(GitBlit ${src_refs} / Gitea ${dst_refs}),请人工核对"
    fail_count=$((fail_count+1))
  fi
done

# ---------- 4. 迁移用户 ----------
need_reset=""
if [[ $REPOS_ONLY -eq 0 ]]; then
  if [[ -n "$GITBLIT_USERS_CONF" && -f "$GITBLIT_USERS_CONF" ]]; then
    log "从 ${GITBLIT_USERS_CONF} 迁移用户 ..."

    # 开发者团队(写权限)+ Owners 团队(管理员归入)
    dev_team_id="$(curl -sf -u "$ADMIN_BASIC" "${API}/orgs/${ORG}/teams" | grep -oE '"id":[0-9]+,"name":"developers"' | cut -d: -f2 | cut -d, -f1 || true)"
    if [[ -z "$dev_team_id" ]]; then
      curl -s -o /dev/null -u "$ADMIN_BASIC" -X POST -H 'Content-Type: application/json' \
        -d '{"name":"developers","permission":"write"}' "${API}/orgs/${ORG}/teams" || true
      dev_team_id="$(curl -sf -u "$ADMIN_BASIC" "${API}/orgs/${ORG}/teams" | grep -oE '"id":[0-9]+,"name":"developers"' | cut -d: -f2 | cut -d, -f1 || true)"
    fi
    owners_team_id="$(curl -sf -u "$ADMIN_BASIC" "${API}/orgs/${ORG}/teams" | grep -oE '"id":[0-9]+,"name":"Owners"' | cut -d: -f2 | cut -d, -f1 || true)"
    log "  团队: developers=${dev_team_id:-未建} Owners=${owners_team_id:-未找到}"

    user_count=0
    while IFS=$'\t' read -r u p e a; do
      [[ -z "$u" ]] && continue
      [[ "$e" == "" ]] && e="${u}@users.local"
      e="$(esc_json "$e")"

      if curl -sf -u "$ADMIN_BASIC" "${API}/users/$(esc_json "$u")" >/dev/null 2>&1; then
        log "  用户 ${u} 已存在,跳过"
        continue
      fi

      pw="$p"; state="密码原样迁移"
      if [[ -z "$pw" || "$pw" =~ ^[0-9a-fA-F]{32}$ || "$pw" =~ ^[0-9a-fA-F]{40}$ ]]; then
        pw="$(head -c 16 /dev/urandom | md5sum | cut -c1-16)"
        state="密码哈希不可逆,需重置"
        need_reset="$need_reset $u"
      fi
      pw="$(esc_json "$pw")"

      code="$(curl -s -o /dev/null -w '%{http_code}' -u "$ADMIN_BASIC" -X POST -H 'Content-Type: application/json' \
        -d "{\"username\":\"$(esc_json "$u")\",\"email\":\"${e}\",\"password\":\"${pw}\",\"must_change_password\":false,\"send_notify\":false}" \
        "${API}/admin/users" || true)"
      if [[ "$code" != 201 ]]; then
        log "  失败: 建用户 ${u} 返回 HTTP $code(邮箱冲突/格式问题常见)"
        fail_count=$((fail_count+1)); continue
      fi

      team="$dev_team_id"; [[ "$a" == "1" && -n "$owners_team_id" ]] && team="$owners_team_id"
      if [[ -n "$team" ]]; then
        curl -sf -u "$ADMIN_BASIC" -X PUT "${API}/teams/${team}/members/$(esc_json "$u")" >/dev/null 2>&1 \
          || log "  警告: ${u} 加入团队失败(HTTP),稍后手工处理"
      fi
      echo "$(date '+%F %T')  用户 ${u}(${state};GitBlit 角色: $( [[ $a == 1 ]] && echo 管理员 || echo 普通 ))" >> "$REPORT"
      user_count=$((user_count+1))
      log "  已建用户 ${u}(${state})"
    done < <(awk '
      function trim(s){gsub(/^[ \t]+|[ \t]+$/,"",s);return s}
      /^\[user / {
        if(u!="") print u "\t" p "\t" e "\t" a
        line=$0; sub(/^\[user "/,"",line); sub(/"\][ \t]*$/,"",line)
        u=trim(line); p=""; e=""; a=""
        next
      }
      {
        idx=index($0,"=")
        if(idx>0){
          key=trim(substr($0,1,idx-1)); val=trim(substr($0,idx+1))
          if(key=="password") p=val
          else if(key=="emailAddress"||key=="emailAddresses") e=val
          else if(key=="role" && val ~ /(^|,)administrator(,|$)/) a="1"
        }
      }
      END{ if(u!="") print u "\t" p "\t" e "\t" a }
    ' "$GITBLIT_USERS_CONF")
    log "用户迁移完成: 新建 ${user_count} 个"
  else
    log "未配置 GITBLIT_USERS_CONF,跳过用户迁移。请在 Gitea 手工创建与 GitBlit 同名的账号(密码一致则 push 凭据无感),或配置该文件后重跑"
  fi
fi

# ---------- 5. 报告 ----------
{
  echo "================ GitBlit → Gitea 迁移报告 $(date '+%F %T') ================"
  echo "组织: ${ORG}   Gitea: http://${DOMAIN}:${PORT}"
  echo "失败/警告项: ${fail_count}(见上方日志)"
  if [[ -n "$need_reset" ]]; then
    echo "密码需重置的账号:${need_reset}"
    echo "  (Gitea 管理后台 → 用户管理 → 编辑 → 重设密码;密码与 GitBlit 一致则客户端凭据无感)"
  fi
  echo "下一步(切换): 1) GitBlit 挪到 8890 或停止  2) .env 改 GITEA_PORT=8899 与 ROOT_URL  3) docker compose up -d"
  echo "         4) git ls-remote http://${DOMAIN}:8899/${ORG}/<仓库>.git 验证老地址已被 Gitea 服务"
} >> "$REPORT"

cat "$REPORT"
log "迁移结束,报告: ${REPORT}"
exit 0
