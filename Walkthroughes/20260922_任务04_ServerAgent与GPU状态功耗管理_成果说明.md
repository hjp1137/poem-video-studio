# 任务04成果说明:Server Agent、GPU 状态与功耗管理(代码完成,真实服务器验收未执行)

> 任务书:`tasks/2026-09-22_任务04_ServerAgent与GPU状态功耗管理.md`
> 日期:2026-09-22
> 结论:**代码已实现并通过单元测试(Mock nvidia-smi/systemctl)与 Mock Agent E2E;本机无 4×4090 服务器,任务书 §16 真实服务器验收未执行,按 §18 完成定义,本任务不得标记完成。**

## 一、实现内容

### 1. poem-video-agent(`agent/`,宿主机 FastAPI,默认 127.0.0.1:8300)

- **白名单命令执行器**(`services/runner.py`):参数数组 + shell=False + timeout + stderr 捕获 + 退出码校验;变更类动作经 `sudo -n`(可配);无 /shell、/exec、/command 端点。
- **GPU 采集**(`services/nvidia.py`):`--query-gpu`(CSV 机器解析,skipinitialspace 处理带引号字段)读取温度/利用率/显存/功耗/区间/P-State/风扇;`--query-compute-apps` 读进程;驱动不支持的区间字段自动降级为 null 不失败。
- **Power Limit**(`services/power.py`):每次实查该卡 min/max 区间后校验 → `nvidia-smi -i N -pl W` → 回读 → 返回 before/requested/after;禁止信任前端提交的区间;驱动未上报区间时拒绝盲设。
- **gpu-power.json**:全局默认 + 预留 per_gpu;临时文件 + os.replace 原子写入;非法 JSON 抛配置错误、不影响 Agent 存活(健康接口报 degraded)。
- **开机自动应用**:`poem-video-gpu-power.service`(Type=oneshot,After=nvidia-persistenced)执行 `python -m app.apply_power`,单卡失败记录 index 并非 0 退出,不阻断系统启动。
- **可选 Token**:AGENT_TOKEN 设置后所有 /v1/*(除 health)需 Bearer 校验。

### 2. PoemVideo Studio API(`backend/app/api/server.py` 等)

- `GET /api/server/gpus`、`PUT /api/server/gpus/{index}/power-limit`、`PUT /api/server/gpus/power-limit`(逐卡调用、逐卡结果、单卡失败不伪装成功)、`GET/PUT /api/server/settings/gpu-power`(本地 ServerSetting + 同步 Agent 侧开机配置 + 可选立即应用);Web 不直接执行 nvidia-smi。
- **审计**:全部修改动作落 `ServerOperation`(action/参数 before/after/result/error/request_id/source_ip/created_at)。

### 3. 前端 GPU 页(`/server/gpu`)

- 摘要(数量/总显存/已用/最高温度/总功耗)+ 一卡一卡片(含进程列表,标注「非受管进程 · 只读」,无 kill 按钮);
- 单卡/全部功耗设置:确认框 → 完成后显示实测 after 值;默认功耗保存 + 开机自动应用开关;
- 刷新:可见 4s / 隐藏降频,编辑中的卡片暂停覆盖;Agent 离线显示红色横幅而非 0 张卡;
- 操作日志页(`/server/operations`)展示审计表。

### 4. 部署配套

`agent/README.md`(安装/systemd/sudoers/Docker 访问/排查/回滚)、`agent/systemd/`(agent + gpu-power oneshot)、`agent/sudoers/`(最小权限:仅 nvidia-smi 与逐个枚举的 unit 固定动词,无 NOPASSWD: ALL)、`agent/config/` 示例;docker-compose 挂载 `./server`、.env.example 增 AGENT_* 项。

## 二、修改文件

- 新增:`agent/**`(app/api、app/services、app/core、app/apply_power.py、tests 4 个文件、systemd 4 个、sudoers、config 2 个、requirements.txt、README.md);
- 新增:`backend/app/models/server.py`、`schemas/server.py`、`services/agent_client.py`、`services/server_service.py`、`api/server.py`、`tests/test_server_api.py`、`tests/mock_agent_app.py`;
- 修改:`backend/app/core/config.py`(agent_* 配置)、`app/models/__init__.py`、`app/main.py`(挂载路由);
- 前端:`types/index.ts`、`api/index.ts`(含 ApiError 暴露 409)、`App.vue` 菜单、`main.ts` 路由、`views/ServerGpuView.vue`、`views/ServerOperationsView.vue`、`playwright.config.ts`(E2E 走 8200 端口 + Mock Agent);
- 配置:`docker-compose.yml`、`.env.example`、`README.md`。

## 三、自验证结果(Mock,非真实 GPU)

| 命令 | 结果 |
|---|---|
| `backend/.venv/Scripts/python.exe -m pytest agent/tests -q`(agent 目录) | 42 passed:CSV 解析/降级/[N/A]/进程引号字段/无进程、区间校验(低/高/非法 index/无区间盲设拒绝)/成功回读、配置原子写/损坏/非法 schema/开机应用(已正确 already、单卡失败记录)、systemctl 状态映射×7/固定 argv/非法动词/日志行数收敛、API 层 404/400/502/422/Token 401 |
| `pytest tests/ -q`(backend) | 43 passed(含新增 9 用例:GPU 代理+审计、非法值、单卡失败不伪装、设置同步+立即应用、未登记服务 404、停止保护、Prepare 全流程/超时/并发守卫) |
| `pnpm run typecheck` / `pnpm run build` | 通过 / ✓ built |

## 四、E2E 验证结果

`pnpm run e2e` 6 passed,其中任务04 用例 1 个(`server-gpu.spec.ts`):4×4090 卡片与摘要 → 全部设 280W 确认框 → 成功后卡片实测 280W → 单卡 320W → 50W 超区间失败提示 → 默认功耗+开机自动应用 → Agent 离线横幅 → 操作日志审计(含失败项与来源 IP)。Mock Agent 为 `backend/tests/mock_agent_app.py`(内存态假 Agent + /_e2e/control 状态切换),非真实宿主机。

## 五、自动截图清单

`Walkthroughes/screenshots/20260922_任务04_ServerAgent与GPU状态功耗管理/`:

| 截图 | 验证点 |
|---|---|
| 01_GPU页_四卡状态与摘要.png | 4 卡片、总显存 96GB、功耗上限 300W、进程只读标注、无 kill 按钮 |
| 02_GPU页_全部设置功耗确认框.png | 批量功耗二次确认与影响范围(GPU0-3)提示 |
| 03_GPU页_设置成功后实测280W.png | 设置后卡片显示实测 280W(after 值) |
| 04_GPU页_超出区间失败提示.png | 低于驱动 min 的值被拒绝,失败原因可见 |
| 05_GPU页_默认功耗与开机自动应用.png | 默认功耗保存、开机自动应用开关开启 |
| 06_GPU页_Agent离线提示.png | Agent 离线横幅,不显示 0 张卡 |
| 07_操作日志_功耗修改审计.png | gpu.power_limit / bulk 审计、success/failed、来源 IP |

## 六、未验证项(重要)

按任务书 §16,以下必须在真实 4×4090 服务器执行,本机无法完成:

1. 页面显示与 `nvidia-smi` 实测一致性(§16.1~2);
2. 真实设置 280W 并回读确认(§16.4~5);
3. 重启 Agent 后配置可读取(§16.6);
4. 开机自动应用 + 服务器重启验证(§16.7~8);
5. 真实 GPU 进程展示与只读(§16.9~10);
6. sudoers 在真实用户/路径下生效(`agent/README.md` §6 排查命令);
7. nvidia-smi 旧驱动对 `power.min_limit/max_limit` 的降级路径仅在 Mock 验证。

需用户提供:4×4090 Ubuntu 服务器 SSH 访问与部署权限,按 `agent/README.md` 安装后执行 §16 十项验收。

## 七、结论

代码已修改,单测与 Mock E2E 全部通过,但真实服务器验收未执行,不能确认完全完成。
