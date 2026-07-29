# running_page

个人跑步数据可视化。后端从 Garmin 同步活动数据，前端渲染为可视化页面。

> 本仓库由 [running_page](https://github.com/yihong0618/running_page) 重构而来，
> 数据源精简为 **Garmin（佳明）**，后端认证迁移到 [python-garminconnect](https://github.com/cyberjunky/python-garminconnect)。

## 目录结构

```
backend/          # Python 后端(独立闭环)
├── sync_garmin/  # 佳明同步: 认证 / 下载 / 落库
├── generator/    # 数据模型(SQLAlchemy ORM) + Generator
├── gpxtrackposter/  # gpx/tcx/fit 文件解析
├── config.py     # 路径与常量
├── utils.py      # make_activities_file(落库 + 写 activities.json)
└── data.db       # 活动数据(sqlite)
src/              # 前端(React + Vite, 待重构)
```

## 环境

- Python 3.12+
- Node 20+ / pnpm

```bash
uv sync            # 或 pip install -r requirements.txt
pnpm install
```

## 后端：同步 Garmin 数据

Garmin 已于 2026 年更改认证流程，旧的 garth 库新登录失效。本项目用
python-garminconnect（curl_cffi 绕过 Cloudflare），支持账密登录与中国区。

### 1. 生成 token

```bash
# 账密登录一次, 产出可复用的 token 串(中国区加 --is-cn)
python -m backend.sync_garmin.make_secret <email> <password> --is-cn
```

把输出的 token 串存入 GitHub secret `GARMIN_SECRET_STRING_CN`，供 CI 复用。

### 2. 同步活动

```bash
# 用 token 同步(中国区)
python -m backend.sync_garmin.sync '<token>' --is-cn

# 可选: 下载 tcx / fit 格式
python -m backend.sync_garmin.sync '<token>' --is-cn --tcx
python -m backend.sync_garmin.sync '<token>' --is-cn --fit
```

同步流程：下载活动文件到 `GPX_OUT/` → 落库 `backend/data.db` → 写出
`src/static/activities.json`(前端消费)。

### CN → Global 互传 (可选)

```bash
python -m backend.sync_garmin.cn_to_global '<cn_token>' '<global_token>'
```

## 前端

```bash
pnpm dev      # 本地开发
pnpm build    # 构建到 dist/
```

## CI

`.github/workflows/run_data_sync.yml` 每日定时同步 Garmin 数据并发布 GitHub Pages。
需在仓库 secret 配置 `GARMIN_SECRET_STRING_CN`。

## License

MIT(见 [LICENSE](LICENSE))。基于 yihong0618/running_page。
