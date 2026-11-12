# CI/CD 部署指南(Gitea 自建方案 · GitBlit 接管式无感迁移)

> 目标:把 GitBlit 的仓库与账号**全量迁入 Gitea**,然后让 Gitea **接管原来的 8899 端口与 `/r/` 地址形状**——
> 开发者的 git 远端地址、账号密码、使用习惯**零改动**,服务器上只跑一套 git 服务,push 即秒级触发构建部署,失败自动回滚。
> 替代原来的手工链路:`导出服务器部署镜像.bat` 导出 tar → 人工上传 → 服务器执行 `deploy-server-image.sh`(旧链路保留可用)。

## 0. 总体架构与「无感」原理

```
开发机(一切照旧)                CI 服务器(如 124.70.90.30)                     部署服务器
──────────────                  ─────────────────────────────                  ──────────
git push http://124.70.90.30:8899/r/<仓库>.git    ←—— 老 GitBlit 地址,切换后原样生效
                                              │
                                   Gitea(接管 8899;组织名 = r)
                                   git 托管 + Actions CI + 自带镜像仓库
                                              │ push 事件(秒级)
                                              ▼
                                          act_runner ── docker build(Dockerfile 多阶段)
                                              │ push 镜像 <sha8>/latest → Gitea Registry(同端口)
                                              │
                                              │ SSH(ops/deploy/deploy.sh,CI 自动执行)
                                              ▼
                                部署服务器 docker pull → compose up -d → /api/health 检查,失败自动回滚
```

无感的三个支点:

- **URL 同形,不需要反向代理**:GitBlit 仓库地址是 `http://IP:8899/r/<仓库>.git`;把 Gitea 的**组织名建为 `r`** 后,Gitea 原生 clone 地址 `http://IP:8899/r/<仓库>.git` 与老地址**逐字符相同**——老 remote 直接指向 Gitea,git 协议原生兼容。
- **端口接管**:8899 上只能有一个服务。切换时刻把 GitBlit 挪到 8890(或退役),Gitea 绑定 8899。迁移期 GitBlit 继续在 8899 服务,业务零中断;Gitea 先跑在 3080 上完成迁移与验证。
- **账号同源**:`gitblit-migrate.sh` 从 GitBlit 的 `users.conf` 迁移**同名账号**;明文密码原样带走,哈希存储的密码不可逆、需按迁移报告重置一次(见 FAQ)。

已知边界:GitBlit 的网页是 `/summary?r=xx` 这类查询参数式 URL,Gitea 用 `/owner/repo` 路径——**git 操作完全无感,浏览器书签需要重新收藏**。

机器要求:CI 服务器 2C4G 更稳(构建期峰值内存较高,1C2G 建议加 2G swap);部署服务器即现有运行 Docker 的服务器。若 GitBlit 与 Gitea 同机,注意迁移期两者并存时的内存。

## 1. 安装 Gitea + act_runner(迁移期先跑 3080)

在 CI 服务器(Linux)上执行:

```bash
# 把仓库里的 ops/gitea 拷到服务器
scp -r ops/gitea user@124.70.90.30:/opt/zly-ci

ssh user@124.70.90.30
cd /opt/zly-ci
cp .env.example .env
vi .env          # ① 改 GITEA_ADMIN_PASSWORD(建议与 GitBlit 管理员同名,如 zlyadmin)
                 # ② 迁移期 GITEA_PORT 保持 3080(8899 还被 GitBlit 占着)
bash setup.sh    # 幂等,失败排查后可重跑
```

`setup.sh` 会:启动 Gitea → 创建管理员 → 生成 runner 注册 token → 启动 act_runner → 检查 Docker 的 `insecure-registries` 配置。

**提前配置 insecure-registries(关键)**:切换后 CI 机与每台部署服务器的 Docker 都要把 `124.70.90.30:8899` 声明为 HTTP 私有仓库,否则推/拉镜像报 `server gave HTTP response to HTTPS client`:

```bash
# /etc/docker/daemon.json(已有其他键时合并进去)
{ "insecure-registries": ["124.70.90.30:8899"] }
sudo systemctl restart docker
```

验证:浏览器打开 `http://124.70.90.30:3080`,用 .env 里的管理员登录;「管理后台 → Actions → Runners」能看到 `zly-runner-1` 且在线。

## 2. 初始化:ci-bot 机器人账号 + 令牌(一次性)

登录 Gitea(3080)后:

1. 组织 `r` 若尚未由迁移脚本创建,手动创建(右上角 + → 新建组织,名为 `r`)。
2. **创建机器人账号**:管理后台 → 用户管理 → 创建 `ci-bot`(邮箱随意)。
3. 把 `ci-bot` 加入组织 `r`,角色 **Owner**(需要写镜像仓库与读代码权限)。
4. **生成令牌**:`ci-bot` → 设置 → 应用 → 生成新令牌,勾选 `repository: read` 与 `package: write`。**令牌只显示一次,先存好**。

> 令牌在 Gitea 重启/换端口后依然有效,无需因切换重新生成。

## 3. 迁移与切换(GitBlit → Gitea,一次性核心步骤)

### 阶段一:迁移数据(老地址仍由 GitBlit 服务,业务零中断)

1. **拷贝用户文件**:从 GitBlit 服务器把 `users.conf` 拷到 CI 机(位置:GitBlit 安装目录的 `data/users.conf`,或启动参数 `--baseFolder` 指定目录下):

   ```bash
   scp gitblit-admin@<gitblit服务器>:/path/to/gitblit/data/users.conf /opt/users.conf
   ```

2. **配置迁移参数**(`/opt/zly-ci/.env` 追加/确认):

   ```bash
   GITBLIT_URL=http://124.70.90.30:8899
   GITBLIT_SERVLET=r
   GITBLIT_ADMIN_USER=<gitblit管理员>     # 可选:克隆私有仓库/自动列举需要
   GITBLIT_ADMIN_PASSWORD=<gitblit密码>
   GITBLIT_REPOS=zly-ai-video-studio      # 空格分隔;你们的 RPC 已关闭(实测 /rpc 404),必须手工填
   GITBLIT_USERS_CONF=/opt/users.conf
   ```

3. **执行迁移**(可重复运行,断点续迁):

   ```bash
   bash gitblit-migrate.sh
   ```

   脚本行为:自动建组织 `r` → 逐仓 mirror 克隆 + `push --mirror` 到 Gitea → 校验两边引用数一致 → 从 users.conf 建同名用户(明文密码原样带;哈希密码生成随机值并列入重置名单)→ 普通用户入 `developers` 团队(写权限)、GitBlit 管理员入 `Owners` → 输出 `migrate-report.txt`。

4. **抽查**:对比两边引用与最近提交:

   ```bash
   git ls-remote http://<gitea管理员>:<密码>@124.70.90.30:3080/r/zly-ai-video-studio.git | head
   ```

### 阶段二:切换端口(分钟级,唯一的老地址停机窗口)

5. **GitBlit 挪出 8899**:在 GitBlit 服务器上编辑其配置(`data/gitblit.properties` 或安装目录的 `gitblit.properties`),把 `server.httpPort=8899` 改为 `8890`,重启 GitBlit 服务。(若决定彻底退役 GitBlit,此步改为停止服务。)
6. **Gitea 接管 8899**:CI 机 `.env` 改两行——`GITEA_PORT=8899`、`GITEA_ROOT_URL=http://124.70.90.30:8899/`,然后 `docker compose up -d`(重建,runner 与令牌不受影响)。
7. **验证老地址已被 Gitea 服务**:

   ```bash
   git ls-remote http://124.70.90.30:8899/r/zly-ai-video-studio.git   # 老地址,无任何改动
   ```

   浏览器打开 `http://124.70.90.30:8899` 应显示 Gitea 界面(用原 GitBlit 账号登录)。

8. **团队**:不做任何操作。若有人 push 报 401,说明该账号密码未能原样迁移(哈希不可逆),按 `migrate-report.txt` 重置为新密码——只需输一次,凭据管理器会记住。

> 如果公司决定**不动 8899**(GitBlit 必须原地继续服务),则"地址不变"无法实现(端口只有一个),只能退回到"每人一条 `git remote set-url` 切到 Gitea 新地址"的方案——届时本指南第 1 步的端口直接用最终值即可。

## 4. 配置 Actions Secrets(组织级,一次配置全项目复用)

Gitea → 组织 `r` → 设置 → Actions → 添加 Secret:

| Secret 名称 | 值 | 说明 |
|---|---|---|
| `CI_USER` | `ci-bot` | 机器人账号 |
| `CI_TOKEN` | 第 2 步生成的令牌 | read:repository + write:package |
| `DEPLOY_HOST` | 部署服务器 IP,如 `192.168.10.60` | |
| `DEPLOY_USER` | SSH 用户 | 需在 docker 用户组或有 sudo docker 权限 |
| `DEPLOY_SSH_KEY` | 私钥全文(含 BEGIN/END 行) | 专用部署密钥:`ssh-keygen -t ed25519 -f deploy_key -N ""` |
| `DEPLOY_PORT` | `22`(可选) | 默认 22 |

把私钥公钥追加到部署服务器 `~/.ssh/authorized_keys`,并手动验证一次免密登录。

## 5. 部署服务器准备(每个项目一次)

目录布局(以本项目为例):

```
/opt/zly-ai-video-studio/
├── compose.yaml          # 从仓库复制;image 固定 zly-ai-video-studio:latest
├── .env                  # 服务器专属配置(ZLY_AI_VIDEO_STUDIO_COMFY_URL、MySQL 密码等),不进 Git
├── ops/
│   ├── deploy.sh         # 首次手动复制,之后 CI 每次部署自动用仓库版覆盖
│   └── rollback.sh
└── .deploy-history       # 自动生成,记录版本历史
```

- 前置:部署服务器 Docker 已按第 1 步配置 insecure-registries(目标值 `124.70.90.30:8899`),能访问 CI 机。
- 手动试拉(切换后):`docker login 124.70.90.30:8899`(ci-bot)→ `docker pull 124.70.90.30:8899/r/zly-ai-video-studio:latest`(首次 CI 成功后才有镜像)。

## 6. 首次部署验证

把 CI 文件提交并推送到**老地址**(此刻它已经是 Gitea):

```bash
git add .gitea ops docs/CI-CD-Gitea部署指南.md
git commit -m "ci: 接入 Gitea 自动构建部署"
git push origin master       # origin = 原 GitBlit 地址,现在由 Gitea 直接接收,秒级触发
```

1. Gitea → 仓库 → **Actions**:出现 `build-and-deploy` 运行,看两步日志(`构建并推送镜像` → `部署到服务器`)。
2. 仓库 → **软件包**(Packages)出现 `zly-ai-video-studio`,tag 为 `<sha8>` 与 `latest`。
3. 服务器:`curl http://127.0.0.1:18189/api/health` 正常;`docker ps` 看容器重建时间。

## 7. 日常操作

- **发版** = `git push origin master`(老地址,秒级触发);或 Actions 页手动「运行工作流」;发版定版可打 `v*` 标签。
- **看当前版本**:`tail -5 /opt/zly-ai-video-studio/.deploy-history`。
- **手动回滚**(服务器上):

  ```bash
  cd /opt/zly-ai-video-studio
  bash ops/rollback.sh --list      # 列出最近版本(新→旧)
  bash ops/rollback.sh             # 回滚到上一版
  bash ops/rollback.sh --to 3      # 回滚到列表第 3 条
  ```

- **失败自动回滚**:deploy.sh 健康检查 60 秒不过 → 输出容器日志 → 自动切回上一版镜像,服务器保持可用旧版。

## 8. 接入新项目(约 5 分钟/项目)

前置:第 1、2 步全公司只做一次;组织 Secrets 全项目共享。

1. **建仓**:Gitea 网页在组织 `r` 下新建空仓库——clone 地址自动就是老地址形状 `http://124.70.90.30:8899/r/<新仓库>.git`;已有 GitBlit 仓库则把名字加进 `.env` 的 `GITBLIT_REPOS` 后重跑 `gitblit-migrate.sh`。
2. 项目根目录放入 `ops/deploy/{deploy,rollback}.sh` 与 `.gitea/workflows/deploy.yml`(可直接复制)。
3. 只改 `deploy.yml` 顶部 `env:` 的 4 行:`DEPLOY_DIR`、`LOCAL_IMAGE`、`SERVICE_NAME`、`HEALTH_URL`(`REGISTRY` 全公司一致)。
4. 项目要有 Dockerfile,`LOCAL_IMAGE` 与 compose.yaml 的 `image:` 一致。
5. 服务器准备第 5 步的项目目录 + `.env`。
6. 推 master 即自动部署;部署/回滚脚本零修改。

## 9. 常见问题

| 现象 | 原因与处理 |
|---|---|
| 切换后 push 报 401 | 该账号密码未能原样迁移(哈希不可逆):管理后台重置密码;Windows 用户若凭据管理器存了旧凭据,先「Windows 凭据管理器 → 删除对应普通凭据」再输入新密码 |
| 匿名 clone 失败 | 迁移后仓库可见性由 `MIGRATE_REPO_PRIVATE` 决定;GitBlit 原来匿名可读的仓库请保持 `false` |
| 迁移脚本报 RPC 404 | 你们 GitBlit 的 rpc.enabled 已关闭——在 `.env` 的 `GITBLIT_REPOS` 手工填仓库名即可 |
| 迁移脚本找不到 users.conf | 位置在 GitBlit 安装目录 `data/users.conf`(或 `--baseFolder` 下);没有则跳过用户迁移、手工建账号 |
| 仓库名带子目录(如 `teamA/app`) | Gitea 仓库不含斜杠,脚本自动展平为 `teamA-app`,报告中有映射表 |
| 推镜像 `server gave HTTP response to HTTPS client` | Docker 未把 `124.70.90.30:8899` 加入 insecure-registries 或改完没 `systemctl restart docker` |
| 推镜像 `unauthorized` / `denied` | `CI_TOKEN` 过期或未勾 `package: write`;重新生成并更新组织 Secret |
| Actions 页没有 runner / 任务一直排队 | runner 未注册成功:看 `docker logs zly-act-runner`;token 失效时重跑 `setup.sh` |
| 切换后 Gitea 起不来(端口占用) | GitBlit 没挪走:确认 `server.httpPort=8890` 已改并重启 GitBlit,`ss -lntp \| grep 8899` 检查占用 |
| 构建阶段 OOM / 被杀 | CI 机加 swap;`runner-config.yaml` 的 `capacity` 保持 1 排队执行 |
| 拉不动 `docker:27-cli` / `gitea/gitea` 镜像 | CI 机配置 Docker Hub 镜像加速(registry-mirrors)或手动导入 |
| 浏览器书签 404 | GitBlit 网页 URL(`/summary?r=xx`)与 Gitea 路径不同,按 Gitea 的新路径重新收藏 |
| 部署步骤卡在健康检查 | 服务器内 `curl http://127.0.0.1:18189/api/health` 与 `docker compose logs` 定位;检查 compose 的 `.env` 是否齐全(如 `ZLY_AI_VIDEO_STUDIO_COMFY_URL`) |

## 10. 安全建议

- 8899 当前为 HTTP:与原 GitBlit 的传输方式一致(未降级);建议防火墙限制来源(公司出口/VPN),后续加 Nginx HTTPS 反代时同步改 `GITEA_ROOT_URL` 与 Docker registry 配置。
- `DEPLOY_SSH_KEY` 使用专用密钥对;服务器上可用 `command=""` 限制该公钥只能执行部署脚本。
- `ci-bot` 令牌只给 `read:repository + write:package`;定期轮换。
- `ops/gitea/.env`、`migrate-report.txt`(含临时密码记录)已加入 `.gitignore`,严禁提交真实密码/令牌;迁移完成后建议删除 `.migrate-cache` 与报告文件。
