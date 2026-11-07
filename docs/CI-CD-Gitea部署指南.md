# CI/CD 部署指南(Gitea 自建方案)

> 目标:推代码(或一键手动触发)→ 自动构建 Docker 镜像 → 推送镜像仓库 → SSH 部署到服务器 → 健康检查,失败自动回滚。
> 替代原来的手工链路:`导出服务器部署镜像.bat` 导出 tar → 人工上传 → 服务器执行 `deploy-server-image.sh`。
> 旧链路仍保留可用,两者互不影响。

## 0. 总体架构

```
开发机                    CI 服务器(如 124.70.90.30)                        部署服务器
──────                   ─────────────────────────────                     ──────────
git push ──▶ GitBlit(老地址,零改动)
             │ gitblit-sync.timer 每分钟增量同步(git push --mirror)
             ▼
           Gitea ──push 事件──▶ act_runner
           (git + CI +            │ docker build(Dockerfile 多阶段)
            自带镜像仓库)◀── push 镜像 <sha8>/latest
                   │                                   │
                   │                        SSH(deploy.sh,CI 自动执行)
                   │                                   ▼
                   └────────────── docker pull ◀── compose.yaml(image 固定
                                    本地打 tag      zly-ai-video-studio:latest)
                                    compose up -d
                                    /api/health 检查,失败自动回滚
```

- **Gitea**:自建 git 托管 + Actions CI + 容器镜像仓库(Registry)三合一,SQLite 存储,百 MB 级内存占用。
- **act_runner**:Gitea 的 CI 执行器,跑在同一台机器,通过宿主机 Docker 构建/推送镜像。
- **gitblit-sync(老地址无感)**:CI 机上的 systemd timer 每分钟把 GitBlit 的增量提交以真实 `git push` 同步到 Gitea——团队 push 老 GitBlit 地址即可,约 1 分钟内触发 CI。刻意不用 Gitea 自带的 pull 镜像,因为镜像同步不触发 push 钩子/Actions(已知行为),真实 push 才能保证 CI 必触发。
- **ops/deploy/**:项目无关的服务器端部署/回滚脚本,每个项目复制一份,CI 每次部署会自动用仓库里的最新版覆盖。
- 保留 GitBlit 也不用迁移公司其他团队;只是本团队项目把 Gitea 当远端。

**机器要求**:CI 服务器 2C4G 更稳(构建期峰值内存较高,1C2G 建议加 2G swap);部署服务器即现有运行 Docker 的服务器。

---

## 1. 安装 Gitea + act_runner(一次性,约 10 分钟)

在 CI 服务器(Linux)上执行:

```bash
# 把仓库里的 ops/gitea 拷到服务器(scp / sftp 均可)
scp -r ops/gitea user@124.70.90.30:/opt/zly-ci

ssh user@124.70.90.30
cd /opt/zly-ci
cp .env.example .env
vi .env          # ① 改 GITEA_ADMIN_PASSWORD ② 确认 GITEA_DOMAIN/PORT/ROOT_URL
bash setup.sh    # 幂等,失败排查后可重跑
```

`setup.sh` 会:启动 Gitea → 创建管理员 → 生成 runner 注册 token → 启动 act_runner → 检查 Docker 的 `insecure-registries` 配置。

**关键一步(HTTP 私有仓库)**:CI 服务器与每台部署服务器的 Docker 都要把 Gitea 声明为 insecure registry,否则拉/推镜像会报 `server gave HTTP response to HTTPS client`:

```bash
# /etc/docker/daemon.json(已有其他键时合并进去)
{ "insecure-registries": ["124.70.90.30:3080"] }
sudo systemctl restart docker
```

验证:浏览器打开 `http://124.70.90.30:3080`,用 .env 里的管理员登录;「管理后台 → Actions → Runners」能看到 `zly-runner-1` 且在线。

---

## 2. 初始化:组织 + 机器人账号(一次性)

登录 Gitea 后:

1. **创建组织**(右上角 + → 新建组织),如 `zly`。组织级 Secrets/仓库都放这里,方便多项目复用。
2. **创建机器人账号**:管理员 → 管理后台 → 用户管理 → 创建用户 `ci-bot`(不需要登录界面,邮箱可随意)。
3. 把 `ci-bot` 加入组织,角色 **Owner**(需要有写包和读仓库权限)。
4. **生成令牌**:`ci-bot` 登录(或管理员代操作)→ 右上角头像 → 设置 → 应用 → 生成新令牌,勾选 `repository: read` 与 `package: write`(可再加 `user: read`)。**令牌只显示一次,先存好**。

---

## 3. 接入仓库:老地址无感(推荐)/ 一次性切换(可选)

### 方式 A:GitBlit 老地址无感(推荐——真正的无感迁移)

团队什么都不用改:继续 push 老 GitBlit 地址,同步定时器把增量推到 Gitea 并触发 CI。

1. 在 CI 机的 `/opt/zly-ci/.env` 里配置同步来源:

   ```bash
   GITEA_ORG=zly
   GITBLIT_BASE=http://124.70.90.30:8899/r        # 以实际 GitBlit 地址为准
   GITBLIT_USER=                                  # GitBlit 私有仓库才填,匿名可读留空
   GITBLIT_PASSWORD=
   SYNC_REPOS=zly-ai-video-studio                 # 空格分隔,要接几个填几个
   ```

2. 安装同步定时器(每 1 分钟增量同步;Gitea 侧缺仓库会自动创建):

   ```bash
   cp systemd/gitblit-sync.service systemd/gitblit-sync.timer /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now gitblit-sync.timer
   journalctl -u gitblit-sync -f          # 观察首次全量同步
   ```

3. 验证:Gitea 上出现 `zly/zly-ai-video-studio` 且分支/标签齐全;之后 GitBlit 收到新 push,约 1 分钟内 Gitea 仓库 → Actions 自动出现任务。

行为说明:

- 同步是「GitBlit → Gitea」单向覆盖:**不要往 Gitea 上的这些仓库 push**,会被下一次同步覆盖。
- CI 触发延迟 ≤ 同步周期(默认 1 分钟);改 `/etc/systemd/system/gitblit-sync.timer` 的 `OnUnitActiveSec` 后 `systemctl daemon-reload` 即可调整。
- 将来想切换正式地址:把仓库名从 `SYNC_REPOS` 移除并 `systemctl restart gitblit-sync`,然后每人一条 `git remote set-url origin http://124.70.90.30:3080/zly/<仓库>.git`,Gitea 仓库转为正常可写仓库,CI 触发从分钟级变秒级。

### 方式 B:直接切换地址(一次性)

```bash
git remote add gitea http://124.70.90.30:3080/zly/zly-ai-video-studio.git
git push gitea --all --tags
```

适合没有「地址必须不变」约束的项目:Gitea 网页「迁移外部仓库 → Git」也能从 GitBlit 迁入(填 `http://124.70.90.30:8899/r/<仓库>.git` 与凭据,分支/标签/历史全保留),迁移后 GitBlit 侧设为只读存档。方式 A/B 共用同一套 CI 文件,随时可互转。

---

## 4. 配置 Actions Secrets(组织级,一次配置全项目复用)

Gitea → 组织 `zly` → 设置 → Actions → 添加 Secret:

| Secret 名称 | 值 | 说明 |
|---|---|---|
| `CI_USER` | `ci-bot` | 机器人账号 |
| `CI_TOKEN` | 第 2 步生成的令牌 | read:repository + write:package |
| `DEPLOY_HOST` | 部署服务器 IP,如 `192.168.10.60` | |
| `DEPLOY_USER` | SSH 用户 | 需在 docker 用户组或有 sudo docker 权限 |
| `DEPLOY_SSH_KEY` | 私钥全文(含 BEGIN/END 行) | 专用部署密钥:`ssh-keygen -t ed25519 -f deploy_key -N ""` |
| `DEPLOY_PORT` | `22`(可选) | 默认 22 |

把私钥对应的公钥(`deploy_key.pub`)追加到部署服务器 `~/.ssh/authorized_keys`,并在服务器上手动验证一次 `ssh -i deploy_key <user>@<host>` 免密可用。

> Secret 的值在日志中会被自动打码;令牌/密码建议保持「无空格、无引号」的 token 形式。

---

## 5. 部署服务器准备(每个项目一次)

目录布局(以本项目为例):

```
/opt/zly-ai-video-studio/
├── compose.yaml          # 从仓库复制(或由 CI 同步);image 固定 zly-ai-video-studio:latest
├── .env                  # 服务器专属配置(ZLY_AI_VIDEO_STUDIO_COMFY_URL、MySQL 密码等),不进 Git
├── ops/
│   ├── deploy.sh         # 首次手动复制过去,之后 CI 每次部署自动用仓库版覆盖
│   └── rollback.sh
└── .deploy-history       # 自动生成,记录版本历史
```

```bash
mkdir -p /opt/zly-ai-video-studio/ops
# 从仓库复制 ops/deploy/*.sh、compose.yaml;手工创建/迁移现有 .env
```

- compose.yaml 里 `build:` 段在服务器上无效也无害;部署脚本用 `--no-build`,只按镜像名更新。
- 前置:服务器 Docker 已配置 insecure-registries(见第 1 步),并能访问 `124.70.90.30:3080`。
- 手动试拉验证:`docker login 124.70.90.30:3080`(ci-bot 账号)→ `docker pull 124.70.90.30:3080/zly/zly-ai-video-studio:latest`(首次部署成功后才有镜像)。

---

## 6. 首次部署验证

先把 CI 文件提交并推送(方式 A 推到 GitBlit 老地址,由同步定时器搬运;方式 B 直接推 Gitea):

```bash
git add .gitea ops docs/CI-CD-Gitea部署指南.md
git commit -m "ci: 接入 Gitea 自动构建部署"
git push origin master        # 方式 A;方式 B 改为 git push gitea master
```

1. Gitea → 仓库 → **Actions**:出现 `build-and-deploy` 运行,看两步日志(`构建并推送镜像` → `部署到服务器`)。
2. 构建产物:仓库 → **软件包**(Packages)里出现 `zly-ai-video-studio`,tag 为 `<sha8>` 和 `latest`。
3. 服务器:`docker ps` 看容器重建时间;`curl http://127.0.0.1:18189/api/health` 正常返回。
4. 之后每次推 master 自动构建部署;也可在 Actions 页右上角「运行工作流」手动触发(选分支 master)。

## 7. 日常操作

- **看当前版本**:服务器 `tail -5 /opt/zly-ai-video-studio/.deploy-history`,或 Actions 历史里最近一次成功运行的提交号。
- **手动回滚**(服务器上):

  ```bash
  cd /opt/zly-ai-video-studio
  bash ops/rollback.sh --list      # 列出最近版本(新→旧)
  bash ops/rollback.sh             # 回滚到上一版
  bash ops/rollback.sh --to 3      # 回滚到列表第 3 条
  ```

  回滚会重打本地 tag 并重启服务,同样做健康检查;若旧镜像已不在本地会先尝试从仓库拉取。

- **部署失败自动回滚**:deploy.sh 健康检查 60 秒不过 → 输出容器日志 → 自动切回上一版镜像;CI 的 deploy 步骤会标红,但服务器保持可用旧版。

## 8. 接入新项目(约 5 分钟/项目)

前置:第 1、2 步全公司只做一次;组织 Secrets(第 4 步)全项目共享。

1. 项目根目录放入与本项目相同的两个脚本目录(可直接复制):`ops/deploy/{deploy,rollback}.sh`、`.gitea/workflows/deploy.yml`。
2. 只改 `deploy.yml` 顶部 `env:` 的 4 行:`DEPLOY_DIR`、`LOCAL_IMAGE`、`SERVICE_NAME`、`HEALTH_URL`(`REGISTRY` 全公司一致)。
3. 项目要有 Dockerfile,`LOCAL_IMAGE` 与 compose.yaml 的 `image:` 一致。
4. 服务器准备第 5 步的项目目录 + `.env` + insecure-registries(已在第 1 步做过则跳过)。
5. 代码接入:CI 机 `.env` 的 `SYNC_REPOS` 追加仓库名并 `systemctl restart gitblit-sync`(老地址无感),或按第 3 节方式 B 直接迁移。
6. 推 master 即自动部署;部署/回滚脚本零修改。

## 9. 常见问题

| 现象 | 原因与处理 |
|---|---|
| `server gave HTTP response to HTTPS client` | Docker 未把 `124.70.90.30:3080` 加入 `insecure-registries` 或改完没 `systemctl restart docker` |
| push 镜像 `unauthorized` / `denied` | `CI_TOKEN` 过期或未勾 `package: write`;重新生成令牌并更新组织 Secret |
| Actions 页没有 runner / 任务一直排队 | runner 未注册成功:查看 `docker logs zly-act-runner`;token 失效时重跑 `setup.sh` 或手动重新注册 |
| 「运行工作流」按钮不出现 | Gitea 需 ≥ 1.22 才支持 `workflow_dispatch`(本安装包为 1.24) |
| 构建阶段 OOM / 被杀 | CI 机加 swap,或把 `runner-config.yaml` 的 `capacity` 保持为 1 排队执行 |
| 拉不动 `docker:27-cli` / `gitea/gitea` 镜像 | CI 机配置 Docker Hub 镜像加速(registry-mirrors)或手动导入 |
| git push 401 | 令牌无 `read:repository`,或账号被禁用 |
| 推了代码但 Actions 没动静 | `journalctl -u gitblit-sync -n 50` 看同步日志;确认 Gitea 仓库的 Actions 单元已启用;确认改动推到了 master/main |
| gitblit-sync 克隆/拉取失败 | `GITBLIT_BASE` 上下文路径不对(默认 `/r`),或 GitBlit 私有仓库缺 `GITBLIT_USER/GITBLIT_PASSWORD` |
| 同步后 Gitea 仓库被"回退" | 有人直接往 Gitea 上的被同步仓库 push 了——同步是单向覆盖,不要往 Gitea 推这些仓库 |
| 部署步骤卡在健康检查 | 服务器内 `curl http://127.0.0.1:18189/api/health` 与 `docker compose logs` 定位;注意 compose 的 `.env` 是否齐全(如 `ZLY_AI_VIDEO_STUDIO_COMFY_URL`) |

## 10. 安全建议

- Gitea 当前为 HTTP + 公网端口:建议防火墙限制 3080 端口来源(公司出口/VPN),或后续加 Nginx HTTPS 反代(`runner-config.yaml` 的 `insecure` 与 `GITEA_ROOT_URL` 需同步改)。
- `DEPLOY_SSH_KEY` 使用专用密钥对,服务器上可进一步用 `command=""` 限制该公钥只能执行部署脚本。
- `ci-bot` 令牌只给 `read:repository + write:package`,不给 admin;定期轮换。
- `ops/gitea/.env` 已被 `.gitignore` 忽略,严禁提交真实密码/令牌到仓库。
