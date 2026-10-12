import path from 'node:path'
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      // E2E 专用 Mock Agent:模拟 4×4090 + 服务状态机 + ComfyUI 队列
      command: `"${path.resolve(import.meta.dirname, '../backend/.venv/Scripts/python.exe')}" tests/mock_agent_app.py 8310`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8310/v1/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: `"${path.resolve(import.meta.dirname, '../backend/.venv/Scripts/python.exe')}" -m uvicorn app.main:app --host 127.0.0.1 --port 8200`,
      cwd: '../backend',
      url: 'http://127.0.0.1:8200/',
      reuseExistingServer: true,
      timeout: 120_000,
      env: {
        DATA_ROOT: path.resolve(import.meta.dirname, '../backend/.e2e-data'),
        AGENT_BASE_URL: 'http://127.0.0.1:8310',
        // ComfyUI 指到 Mock Agent 的假端点,prepare STEP10 队列检查可闭环
        COMFYUI_BASE_URL: 'http://127.0.0.1:8310',
        COMFYUI_WS_URL: 'ws://127.0.0.1:8310/ws',
        SERVER_PROFILES_FILE: path.resolve(import.meta.dirname, '../server/profiles.yaml'),
        // 模板管理:ComfyUI 用户工作流来源指向测试 fixture(199 真实工作流)
        COMFYUI_USER_WORKFLOWS_DIR: path.resolve(import.meta.dirname, '../backend/tests/fixtures'),
        // 缩短 HTTP 对账周期,加速「生成完成→对账」类用例
        RECONCILE_INTERVAL_SECONDS: '2',
      },
    },
    {
      command: 'pnpm preview --port 4173 --strictPort',
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: true,
      timeout: 60_000,
      // 本机 8000 常被其他服务占用,E2E 固定走 8200
      env: { API_PROXY_TARGET: 'http://127.0.0.1:8200' },
    },
  ],
})
