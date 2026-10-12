# 诗影工坊 PoemVideo Studio

整首诗一次输入、一次提交、自动排队、逐段生成。PoemVideo Studio 是现有 MiniMax H3 / ComfyUI 视频工作流之上的轻量控制层:**不改模型链路、不重做推理**,只负责批量组织与可靠执行。

## 1. 项目简介

对一首绝句/律诗,传统流程需要逐段「复制 Prompt → 粘贴 → 选首帧 → 提交生成」。本工具把流程收敛为:

1. 一次上传封面 + N 张诗句场景图;
2. 一次粘贴整首诗的 `POEM_VIDEO_BATCH_V1` 批量文本;
3. 页面解析预览、绑定图片;
4. 一次点击「全部加入生成队列」;
5. 自动逐段提交 ComfyUI Queue、实时状态跟踪、逐段下载 MP4。

单个任务失败可单独重试,不影响已完成任务;API 重启后可按 prompt_id 与 ComfyUI history 对账恢复。

## 2. 架构

```text
浏览器(Vue 3 + Element Plus)
   ↓ REST / WebSocket
PoemVideo Studio API(FastAPI)
   - Batch Parser      批量文本解析
   - Upload Service    图片上传与绑定
   - Workflow Adapter  模板注入(节点映射可配置)
   - ComfyUI Client    /prompt /queue /history /view /ws
   - Task Tracker      提交、重试、状态同步、输出落地
   ↓
ComfyUI(现有 MiniMax H3 Workflow,不在本项目中)
   ↓
MiniMax H3 / vLLM(现有服务,不改动)
   ↓
outputs/{batch_id}/00_cover.mp4、01_scene_1.mp4 …
```

## 3. 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite + TypeScript + Element Plus |
| 后端 | Python 3.11+(本地 3.10 亦可运行)+ FastAPI |
| 数据 | SQLAlchemy + SQLite |
| ComfyUI 交互 | httpx(REST)+ websockets(WS) |
| 部署 | Docker Compose(api + web 两容器) |

## 4. 前置条件

- 已能正常生成视频的 ComfyUI + MiniMax H3 环境(本项目不包含、不修改它们);
- 从该工作流导出的 **API Format Workflow JSON**(见下节);
- Node 18+/pnpm(前端构建)、Python 3.10+(本地开发)或 Docker(部署)。

## 5. 导出 ComfyUI API Workflow(必做)

1. 在 ComfyUI 打开当前**正在成功生成视频**的 MiniMax H3 工作流;
2. 菜单选择「导出(API)」/「Export (API)」,得到 API Format JSON;
3. 保存为 `workflows/minimax_h3_poem_v1.json`;
4. 对照该 JSON,确认以下节点 ID 与 input key:
   - 首帧 image 节点、正向 Prompt 节点、Negative Prompt 节点、speech/audio 文本节点;
   - width / height / fps / num_frames(及 seed,若需要);
   - SaveVideo 的 filename_prefix。

> 仓库只提供 `minimax_h3_poem_v1.example.json` 结构示例,**禁止**把示例当真实模板用于生产。真实模板缺失时,健康检查会显示 Workflow Template 失效,提交任务会失败并给出可诊断原因。

## 6. Workflow 映射配置

复制 `workflows/workflow-map.example.yaml` 为 `workflows/workflow-map.yaml`,按真实 Workflow 填写:

```yaml
name: minimax_h3_poem_v1
nodes:
  image:            { id: "12", input: "image" }
  prompt:           { id: "35", input: "prompt" }
  negative_prompt:  { id: "36", input: "negative_prompt" }
  speech:           { id: "41", input: "text" }
  width:            { id: "45", input: "width" }
  height:           { id: "45", input: "height" }
  fps:              { id: "45", input: "fps" }
  num_frames:       { id: "45", input: "num_frames" }
  seed:             { id: "45", input: "seed" }   # 可选
  save:             { id: "50", input: "filename_prefix" }
```

服务启动与每次健康检查都会校验映射:节点不存在或 input key 不存在时直接报出具体字段,不允许进入生成。输出命名固定为 `{batch_id}/{scene_order:02d}_{scene_key}`。

## 7. 开发启动

```bash
# 后端(仓库根目录)
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/macOS 用 .venv/bin/python
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
pnpm install
pnpm run dev        # http://localhost:5173,/api 自动代理到 127.0.0.1:8000
```

验证命令:

```bash
cd backend && .venv/Scripts/python -m pytest tests/ -q   # 后端单元测试
cd frontend && pnpm run typecheck && pnpm run build      # 前端类型检查与构建
cd frontend && pnpm run e2e                              # Playwright E2E(自动起后端+preview)
```

## 8. Docker 部署

```bash
cp .env.example .env          # 按实际修改 ComfyUI 地址等
# 准备 workflows/minimax_h3_poem_v1.json 与 workflow-map.yaml
docker compose up -d --build
# Web:  http://<服务器>:8080    API: http://<服务器>:8000/docs
```

- `poem-video-api`、`poem-video-web` 两容器,`restart: unless-stopped` 支持服务器重启自启;
- SQLite、uploads、outputs、logs 全部持久化在命名卷 `/data/poem-video-studio`;
- `extra_hosts: host-gateway` 使容器可用 `host.docker.internal` 访问宿主 ComfyUI;
- MiniMax H3 / vLLM / ComfyUI 保持独立运行,不打入本项目镜像。

## 9. 数据目录

```text
/data/poem-video-studio/(本地开发为仓库内 data/poem-video-studio)
├── uploads/      # {batch_id}/ 下为各场景首帧副本(创建批次时从暂存区复制)
├── outputs/      # {batch_id}/00_cover.mp4、01_scene_1.mp4 …(由 ComfyUI /view 下载落地)
├── database/     # poem_video_studio.db
└── logs/
```

## 10. 批量 Prompt 格式

```text
POEM_VIDEO_BATCH_V1

title: 宿建德江
dynasty: 唐
author: 孟浩然

[GLOBAL]
width: 768
height: 1024
fps: 24
num_frames: 121

negative_prompt:
文字变形,文字模糊,文字漂移,画面闪烁,主体扭曲,镜头剧烈晃动

[SCENE:cover]
speech: 宿建德江,唐,孟浩然。
prompt:
水墨风格封面……(支持多行)

[SCENE:1]
speech: 移舟,泊烟渚。
prompt:
一叶扁舟缓缓停靠烟雾迷蒙的小洲……
```

规则:

- 首个非空行必须是 `POEM_VIDEO_BATCH_V1`;
- `[GLOBAL]` 可缺省,缺省参数用 `.env` 默认值;`negative_prompt` 支持多行;
- `[SCENE:cover]` 可选,`[SCENE:1..N]` 数量不限;场景顺序固定 cover → 1 → 2 → …;
- speech / prompt / negative_prompt **原样传递**,系统不做任何改写;多音字同音字辅助只应写在 speech 中;
- scene key 重复、缺 prompt、缺 speech、参数非法都会报错并指明位置;编号断裂给出警告提示。

## 11. 常见故障

| 现象 | 排查 |
|---|---|
| 系统状态显示 ComfyUI HTTP 异常 | 检查 ComfyUI 是否启动、`.env` 的 `COMFYUI_BASE_URL` 是否可达(容器内注意 `host.docker.internal`) |
| Workflow Template 失效 | `workflows/minimax_h3_poem_v1.json` 缺失,或映射节点 ID / input 与模板不符,按提示字段校准 |
| 提交任务失败「上传首帧失败」 | ComfyUI `/upload/image` 被拒,检查磁盘与 ComfyUI 版本 |
| history 显示完成但找不到 MP4 | Save 节点输出类型不是 output 或未生成视频,检查 Workflow 的 SaveVideo 节点 |
| 页面刷新后状态丢失 | 正常情况下由 prompt_id + history 对账恢复;若 ComfyUI 也重启丢失 history,任务会标记「待恢复确认」,可单独重试 |
| 下载 404 | 输出文件不在数据库登记路径,先在系统状态页确认 Data Directory 可写 |

## 12. V1.0 验收方式

以《宿建德江》(1 封面 + 4 句)为例:

1. `GET /api/system/health` 全绿(ComfyUI 相关项需要真实环境);
2. 上传 5 张图 → 粘贴批量文本 → 解析得到 5 场景 → 全部绑定 → 创建批次(数据库 1 Batch + 5 VideoTask);
3. 点击「全部加入生成队列」→ ComfyUI Queue 出现 5 个任务 → 页面看到 queued → running → completed;
4. 每段视频可预览、可下载,文件名形如 `宿建德江_01_移舟泊烟渚.mp4`;
5. 制造一段失败(如临时停掉 ComfyUI)后单独重试成功;
6. 重启 API 容器,任务状态可恢复,已下载输出不丢失。

自动化验证:`pnpm run e2e` 覆盖第 2 步全流程(不含真实 ComfyUI 部分);真实 ComfyUI 端到端需在部署服务器执行第 3~6 步。

## 13. V1.1 服务器控制中心(任务04/05)

Web API 不直接执行宿主机命令,一律经宿主机 `poem-video-agent`(白名单,无任意 Shell):

- **GPU**:状态/进程查看、单卡与全部 Power Limit 设置(驱动 min/max 区间校验)、默认功耗与开机自动应用(systemd oneshot);
- **模型服务**:已登记服务(`services.yaml` 注册表)的启动/停止/重启/日志,process 与 health 两层状态,停止保护(生成任务运行中或队列非空时需二次确认);
- **冲突服务自动检测**:Agent 按 GPU 真实占用(nvidia-smi 进程 → cgroup 归属 docker/systemd/进程)自动给出待停止清单,不再依赖固定配置,新增服务同样能被检测;停止容器仅对「当前占用 GPU」者放行(动态白名单);
- **一键准备**:「服务器 → 总览」提供「视频环境准备 · 手动逐项」卡片,按 `server/profiles.yaml` 分项展示(设置功耗 → 停止冲突服务 → 启动 H3 → 启动 ComfyUI),由用户手动逐项确认执行,每项操作有确认框并落审计(后端仍保留自动 prepare API,页面不提供入口);
- **操作审计**:全部修改动作落 `ServerOperation`(动作/参数/结果/来源 IP/时间)。

部署与回滚:`agent/README.md`;H3/ComfyUI systemd 服务化迁移:`docs/2026-09-22_服务器控制中心_H3与ComfyUI服务化迁移手册.md`(真实服务器执行)。

前端新增菜单:服务器(总览 / GPU / 模型服务 / 操作日志);批量页面顶部显示视频环境状态条(只读,不自动改变服务器状态)。

## MiniMax H3 首尾帧测试（独立功能）

开发分支新增 /keyframes 页面，支持上传首帧＋尾帧、文字提示词、5 秒竖屏，以及原版 50 步 / FL2VA Turbo 8-step 生成。通过 Studio FastAPI 直接请求 H3 的 /v1/videos/sync，不修改已有 ComfyUI 模板和批量队列。

生产部署请在 .env 配置 H3_API_BASE_URL=http://host.docker.internal:8000（Studio API 容器访问宿主 H3），并保证 API_PORT 不与 H3 的宿主 8000 端口冲突。Turbo 模式要求 H3 服务已预加载相应 FL2VA LoRA。首次先用原版模式测试接口兼容性。

后端离线测试：进入 backend 执行 python -m pytest tests/test_h3_keyframes.py -q。前端类型检查：进入 frontend 执行 pnpm run typecheck。

注意：当前页面用于单次真实兼容性试验，尚未接入整首诗批量任务的新增首尾帧字段。详见 docs/2026-10-12_首尾帧生成接入与试运行.md。
