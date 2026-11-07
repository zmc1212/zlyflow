#!/usr/bin/env bash
# ZLY 自建 CI 一键安装:Gitea(代码托管 + Actions + 镜像仓库)+ act_runner
# 用法(在 Linux 服务器上):
#   cp -r ops/gitea /opt/zly-ci && cd /opt/zly-ci
#   cp .env.example .env && vi .env          # 修改域名/端口/管理员密码
#   bash setup.sh                            # 幂等,可重复运行
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[提醒] %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[错误] %s\033[0m\n' "$*" >&2; exit 1; }

# ---------- 前置检查 ----------
command -v docker >/dev/null 2>&1 || die "未找到 docker,请先安装 Docker Engine"
docker compose version >/dev/null 2>&1 || die "未找到 docker compose 插件"
command -v curl >/dev/null 2>&1 || die "未找到 curl"

[[ -f .env ]] || { cp .env.example .env; die "已生成 .env,请先修改其中的域名/端口/管理员密码,再重新运行本脚本"; }
# shellcheck disable=SC1091
set -a; . ./.env; set +a

PORT="${GITEA_PORT:-3080}"
DOMAIN="${GITEA_DOMAIN:-127.0.0.1}"
ADMIN_USER="${GITEA_ADMIN_USER:-zlyadmin}"
ADMIN_PASS="${GITEA_ADMIN_PASSWORD:-}"
ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-admin@zly.local}"
LOCAL_API="http://127.0.0.1:${PORT}"

[[ -n "$ADMIN_PASS" && "$ADMIN_PASS" != "Please-Change-Me-2026" ]] || die "请先在 .env 中修改 GITEA_ADMIN_PASSWORD(不能使用默认值)"

say "[1/6] 启动 Gitea ..."
docker compose up -d gitea

say "[2/6] 等待 Gitea 就绪(最长 3 分钟)..."
ready=0
for _ in $(seq 1 90); do
  if curl -sf "${LOCAL_API}/api/healthz" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
if [[ $ready -ne 1 ]]; then
  docker compose logs --tail 50 gitea >&2 || true
  die "Gitea 未就绪,日志见上;排查后重跑本脚本"
fi

say "[3/6] 创建管理员 ${ADMIN_USER} ..."
if docker compose exec -T -u 1000 gitea gitea admin user list 2>/dev/null | grep -qw "$ADMIN_USER"; then
  echo "管理员已存在,跳过"
else
  docker compose exec -T -u 1000 gitea gitea admin user create \
    --admin --must-change-password=false \
    --username "$ADMIN_USER" \
    --password "$ADMIN_PASS" \
    --email "$ADMIN_EMAIL" || die "管理员创建失败"
fi

say "[4/6] 生成 act_runner 注册 token ..."
reg_token=""
for method in GET POST; do
  reg_token="$(curl -sf -X "$method" -u "${ADMIN_USER}:${ADMIN_PASS}" \
    "${LOCAL_API}/api/v1/admin/actions/runners/registration-token" \
    | grep -oE '"token"[[:space:]]*:[[:space:]]*"[^"]+"' | head -n1 | cut -d'"' -f4 || true)"
  [[ -n "$reg_token" ]] && break
done
if [[ -z "$reg_token" ]]; then
  die "无法通过 API 获取 runner token。请登录 Gitea → 管理后台 → Actions → Runners → 创建注册令牌,填入 .env 的 GITEA_RUNNER_REGISTRATION_TOKEN 后重跑本脚本"
fi
if grep -q '^GITEA_RUNNER_REGISTRATION_TOKEN=' .env; then
  sed -i.bak "s|^GITEA_RUNNER_REGISTRATION_TOKEN=.*|GITEA_RUNNER_REGISTRATION_TOKEN=${reg_token}|" .env && rm -f .env.bak
else
  echo "GITEA_RUNNER_REGISTRATION_TOKEN=${reg_token}" >> .env
fi
echo "token 已写入 .env"

say "[5/6] 启动 act_runner ..."
[[ -f runner-config.yaml ]] || cp runner-config.default.yaml runner-config.yaml
docker compose up -d act-runner
sleep 3
docker compose ps

say "[6/6] 检查宿主机 Docker 的 insecure-registries ..."
if [[ -f /etc/docker/daemon.json ]] && grep -q "${DOMAIN}:${PORT}" /etc/docker/daemon.json; then
  echo "已包含 ${DOMAIN}:${PORT},OK"
else
  cat <<EOF

CI 构建推送与部署服务器拉取镜像,都要求 Docker 把 Gitea 当作 HTTP 私有仓库(insecure registry)。
当前 /etc/docker/daemon.json 未包含 ${DOMAIN}:${PORT},请执行(本机与每台部署服务器都要做):

  1) 编辑 /etc/docker/daemon.json(已有其他键时合并,不要整体覆盖):
     {
       "insecure-registries": ["${DOMAIN}:${PORT}"]
     }
  2) sudo systemctl restart docker

EOF
fi

cat <<EOF

============================================================
 ZLY 自建 CI 安装完成
  Gitea 界面 : http://${DOMAIN}:${PORT}
  管理员账号 : ${ADMIN_USER}
  下一步     : 按 docs/CI-CD-Gitea部署指南.md 操作——
               ① 登录创建组织(如 zly)与机器人账号 ci-bot
               ② 从 GitBlit 迁移仓库
               ③ 配置 Actions Secrets(CI_USER/CI_TOKEN/DEPLOY_*)
               ④ 推送 master 或在 Actions 页手动运行流水线
============================================================
EOF
