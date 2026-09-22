# 2026-09-22 任务04：Server Agent、GPU 状态与功耗管理

## 1. 任务目标

为 PoemVideo Studio V1.1 增加受控的宿主机 Server Agent，实现：

- 查看 NVIDIA GPU 状态。
- 查看 GPU 进程。
- 修改单卡 / 全部 GPU Power Limit。
- 保存默认 Power Limit。
- 可选服务器启动后自动应用。
- PoemVideo Studio 前端提供 GPU 管理页面。

本任务不实现 MiniMax H3 / ComfyUI 的启动停止，服务控制属于任务05。

## 2. 核心安全要求

禁止实现：

```text
POST /shell
POST /exec
POST /command
```

禁止从 API 接收并执行任意字符串命令。

所有动作必须使用代码内部固定逻辑 + 参数校验。

Agent 不得拥有：

```text
NOPASSWD: ALL
```

## 3. Agent 工程

建议新增：

```text
agent/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── health.py
│   │   └── gpu.py
│   ├── services/
│   │   ├── nvidia.py
│   │   └── power.py
│   └── core/
│       ├── config.py
│       └── security.py
├── requirements.txt
└── systemd/
    ├── poem-video-agent.service
    └── poem-video-gpu-power.service
```

推荐 Agent 使用 Python + FastAPI 或 Starlette。

默认绑定：

```text
127.0.0.1
```

如 Docker API 必须访问，按部署环境增加 host-gateway / Unix Socket / 受限内部接口方案。

## 4. GPU 状态

实现 Agent API：

```text
GET /v1/gpus
```

返回每卡至少：

- index
- uuid
- name
- temperature_c
- utilization_gpu_percent
- memory_used_mib
- memory_total_mib
- power_draw_w
- power_limit_w
- min_power_limit_w
- max_power_limit_w
- pstate
- processes[]

进程字段至少：

- pid
- process_name
- used_gpu_memory_mib

如驱动无法提供某字段，返回 null，不得让整个接口失败。

## 5. NVIDIA 数据读取

优先使用明确的 query 参数获取机器可解析数据。

不得通过 shell=True。

Python 使用 subprocess 时必须：

- 参数数组传递。
- shell=False。
- 设置 timeout。
- 校验 exit code。
- 捕获 stderr。
- 对异常返回明确错误。

## 6. Power Limit

实现：

```text
PUT /v1/gpus/{index}/power-limit
```

请求：

```json
{
  "watts": 280
}
```

Agent 必须：

1. 确认 index 存在。
2. 读取该 GPU 支持的最小/最大 Power Limit。
3. 校验 watts。
4. 执行受控 `nvidia-smi -i INDEX -pl WATTS`。
5. 再次查询实际值。
6. 返回 before / requested / after。

禁止信任前端提交的 min/max。

## 7. 全卡设置

PoemVideo Studio API 层实现：

```text
PUT /api/server/gpus/power-limit
```

输入：

```json
{
  "watts": 280,
  "gpu_indices": [0,1,2,3]
}
```

依次调用 Agent。

必须返回逐卡结果。

如果其中一张失败，不得伪装“全部成功”。

## 8. 默认 Power Limit

新增配置：

```text
/etc/poem-video-agent/gpu-power.json
```

示例：

```json
{
  "enabled": true,
  "default_power_limit": 280,
  "per_gpu": {}
}
```

要求：

- 支持全局默认。
- 预留 per_gpu。
- 配置写入采用原子替换。
- 非法 JSON 不得导致 Agent 启动崩溃，必须报配置错误。

## 9. 开机自动应用

建立：

```text
poem-video-gpu-power.service
```

类型：

```text
Type=oneshot
```

要求：

- 在 NVIDIA 驱动可用之后执行。
- 根据配置应用 Power Limit。
- 输出日志到 journald。
- 某张 GPU 失败时明确记录 GPU index。
- 不阻断整个系统启动。

## 10. sudoers

建立最小权限 sudoers 配置。

允许 Agent 用户执行需要的 NVIDIA Power Limit 操作。

不得授予：

```text
ALL=(ALL) NOPASSWD: ALL
```

任务实现时在 docs 中记录最终 sudoers 内容和原因。

## 11. PoemVideo Studio API 接入

新增：

```text
GET /api/server/gpus
PUT /api/server/gpus/{index}/power-limit
PUT /api/server/gpus/power-limit
GET /api/server/settings/gpu-power
PUT /api/server/settings/gpu-power
```

Web API 不直接调用 nvidia-smi。

所有宿主机动作通过 Agent。

## 12. 前端 GPU 页面

新增一级菜单：

```text
服务器
└── GPU
```

页面：

### GPU 摘要

- GPU 数量
- 总显存
- 已用显存
- 最高温度
- 当前总功耗

### 每卡卡片

显示：

- 名称
- 温度
- 利用率
- 显存
- 当前功耗
- Power Limit
- P-State
- 进程

### Power Limit 控制

- 单卡修改
- 全部设置
- 默认值
- 开机自动应用开关

修改 Power Limit 前弹确认框：

```text
将 GPU0-3 Power Limit 设置为 280W？
```

完成后显示实际读取值。

## 13. 刷新

- 页面打开时 3～5 秒刷新。
- 页面隐藏时降低频率。
- 修改过程中暂停对应卡片自动更新，防止 UI 抢状态。
- Agent 不可达时显示“Agent 离线”，不能显示 GPU=0。

## 14. 操作日志

PoemVideo Studio 落库：

- action
- gpu indices
- requested watts
- before
- after
- result
- error
- request_id
- source_ip
- created_at

Agent 也记录主机执行日志。

## 15. 测试

必须至少覆盖：

- 读取 4 张 GPU。
- min/max Power Limit。
- 正常设置 280W。
- 设置低于 min。
- 设置高于 max。
- 非法 GPU index。
- nvidia-smi 超时。
- nvidia-smi 返回非 0。
- 某一张卡设置失败。
- Agent 不可达。
- 配置文件损坏。
- 开机自动应用逻辑。

单元测试允许 mock nvidia-smi，但最终必须真实服务器验收。

## 16. 真实服务器验收

在当前 4×RTX 4090 服务器执行：

1. 页面正确显示 4 张卡。
2. 温度、显存、利用率与直接执行 nvidia-smi 基本一致。
3. 显示当前 Power Limit。
4. 页面设置全部 GPU 为 280W。
5. 再次读取确认 4 张卡均为 280W。
6. 重启 Agent，设置仍然可读取。
7. 启用开机自动应用后，完成一次服务器重启验证。
8. 重启后无需 SSH 手工设置，Power Limit 自动恢复到配置值。
9. 页面展示 GPU 进程。
10. 未登记进程只读，不提供 kill。

## 17. 文档

新增/更新文档说明：

- Agent 安装
- systemd
- sudoers
- Power Limit 配置
- Docker API 如何访问 Agent
- 故障排查
- 如何回滚

## 18. 完成定义

任务04只有在真实服务器上实现“查看 GPU + Web 设置 Power Limit + 开机自动应用”完整闭环后才能标记完成。

仅完成前端 Mock 页面或 nvidia-smi 脚本不算完成。
