# poem-video-agent

PoemVideo Studio V1.1 服务器控制中心的宿主机 Agent。运行在 Ubuntu GPU 服务器上,只提供**白名单** GPU 与已登记模型服务操作,不提供任意 Shell。

> 设计依据:`docs/2026-09-22_服务器控制中心设计方案_V1.1.md`;任务书:任务04/任务05。

## 1. 架构与边界

```
PoemVideo Studio API(Docker) → http://host.docker.internal:8300(本 Agent)→ nvidia-smi / systemctl / journalctl
```

- 只监听 `127.0.0.1`(Docker 侧经 `host.docker.internal` → host-gateway 访问)。
- Agent 永不接收 shell/command 字符串;所有命令在代码内固定构造,参数只接受已校验的数字/注册表名称。
- 高权限动作经 `sudo -n` 执行,sudoers 最小权限(见 `sudoers/poem-video-agent`)。

## 2. 安装(真实服务器)

```bash
# 1) 部署代码与虚拟环境
sudo mkdir -p /opt/poem-video-agent && sudo chown $USER /opt/poem-video-agent
# 把仓库 agent/ 目录内容复制到 /opt/poem-video-agent
cd /opt/poem-video-agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2) 运行用户与配置目录
sudo useradd -r -m poemagent || true   # 已存在则跳过
sudo mkdir -p /etc/poem-video-agent
sudo cp config/services.yaml.example /etc/poem-video-agent/services.yaml
sudo cp config/gpu-power.json.example /etc/poem-video-agent/gpu-power.json
# 按服务器实际情况修改以上两个文件(H3 端口、unit 名等)
sudo chown -R poemagent:poemagent /etc/poem-video-agent

# 3) sudoers(按需修改用户名/新增 unit)
sudo cp sudoers/poem-video-agent /etc/sudoers.d/poem-video-agent
sudo chmod 440 /etc/sudoers.d/poem-video-agent
sudo visudo -c   # 校验语法

# 4) systemd 服务
sudo cp systemd/poem-video-agent.service systemd/poem-video-gpu-power.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now poem-video-agent
curl http://127.0.0.1:8300/v1/health   # 应返回 {"status":"ok",...}

# 5) 开机自动应用功耗(可选,默认启用)
sudo systemctl enable poem-video-gpu-power.service
```

## 3. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /v1/health | Agent 存活 + 配置自检(非法配置报 degraded,不崩溃) |
| GET | /v1/gpus | 全部 GPU 状态 + 每卡进程(驱动不支持的字段为 null) |
| PUT | /v1/gpus/{index}/power-limit | `{watts}`;实查 min/max 校验后执行 `nvidia-smi -i N -pl W`,返回 before/requested/after |
| GET/PUT | /v1/gpu-power/config | `/etc/poem-video-agent/gpu-power.json` 读写(原子替换) |
| GET | /v1/services | 已登记服务状态(process_state + health_state 两层) |
| GET | /v1/services/{name} | 单服务状态 |
| POST | /v1/services/{name}/start\|stop\|restart | 固定动词;name 必须来自 services.yaml |
| GET | /v1/services/{name}/logs?lines=N | journalctl 最近日志,默认 100,上限 1000,参数固定 |
| GET | /v1/gpu-workloads | 自动检测占用 GPU 显存的服务清单(docker 容器/systemd unit/裸进程,cgroup 归属 + docker ps 映射) |
| POST | /v1/gpu-workloads/{container}/stop | 停止一个**当前占用 GPU** 的容器(动态白名单,任意容器名拒绝);systemd/裸进程负载只读展示 |

不存在 `/shell`、`/exec`、`/command` 端点。

## 4. 配置

| 文件 | 作用 |
|---|---|
| `/etc/poem-video-agent/gpu-power.json` | 开机自动应用:`{"enabled":true,"default_power_limit":280,"per_gpu":{}}` |
| `/etc/poem-video-agent/services.yaml` | 服务注册表(唯一允许控制的 systemd unit 清单) |
| 环境变量 `AGENT_TOKEN` | 可选 Bearer Token,设置后所有 /v1/* (除 health) 需携带 |

## 5. Docker API 如何访问 Agent

docker-compose 已为 poem-video-api 配置 `extra_hosts: host.docker.internal:host-gateway`,在 `.env` 中:

```
AGENT_BASE_URL=http://host.docker.internal:8300
```

## 6. 故障排查

| 现象 | 排查 |
|---|---|
| 页面显示 Agent 离线 | `systemctl status poem-video-agent`;`curl 127.0.0.1:8300/v1/health` |
| 功耗设置失败 502 | `sudo -u poemagent sudo -n nvidia-smi -i 0 -pl 280` 手工验证 sudoers |
| 服务操作失败 | `journalctl -u poem-video-agent -n 100`;确认 unit 在 services.yaml 且 sudoers 已放行 |
| 健康接口 degraded | 检查 /etc/poem-video-agent/ 下 JSON/YAML 语法 |
| 开机功耗未应用 | `journalctl -u poem-video-gpu-power.service`,确认 enabled 与 gpu-power.json enabled=true |

## 7. 回滚

```bash
sudo systemctl disable --now poem-video-agent poem-video-gpu-power.service
sudo rm /etc/systemd/system/poem-video-agent.service /etc/systemd/system/poem-video-gpu-power.service
sudo rm /etc/sudoers.d/poem-video-agent && sudo systemctl daemon-reload
# H3/ComfyUI 恢复手工启动:systemctl disable --now minimax-h3 comfyui 后按原 tmux 命令启动
```

Web/API 容器不依赖 Agent 存活:Agent 离线时仅服务器控制中心页面显示离线,批量生成等功能不受影响。
