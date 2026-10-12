import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'

const SHOT_DIR = path.resolve(import.meta.dirname, '../../Walkthroughes/screenshots/20260922_任务05_模型服务管理与H3环境一键准备')

const MOCK_AGENT = 'http://127.0.0.1:8310'

test.beforeAll(() => {
  mkdirSync(SHOT_DIR, { recursive: true })
})

test.beforeEach(async ({ request }) => {
  await request.post(`${MOCK_AGENT}/_e2e/control`, { data: { action: 'reset' } })
})

test('任务05验收:服务状态、启动停止、日志与停止保护', async ({ page, request }) => {
  await page.goto('/server/services')
  await expect(page.getByTestId('service-card-minimax_h3')).toBeVisible()

  // 1. 初始状态:H3 停止、Ollama 运行健康、ComfyUI 停止
  await expect(page.getByTestId('service-card-ollama')).toContainText('Running')
  await expect(page.getByTestId('service-card-minimax_h3')).toContainText('Stopped')
  await page.screenshot({ path: path.join(SHOT_DIR, '01_模型服务页_初始状态.png'), fullPage: true })

  // 2. 启动 MiniMax H3:状态变 Running,健康由 Unhealthy 转 Healthy(systemd active ≠ Ready)
  await page.getByTestId('service-card-minimax_h3').getByTestId('svc-start').click()
  await expect(page.getByTestId('service-card-minimax_h3')).toContainText('Running', { timeout: 10000 })
  await expect(page.getByTestId('service-card-minimax_h3')).toContainText('Unhealthy')
  await expect(page.getByTestId('service-card-minimax_h3')).toContainText('Healthy', { timeout: 20000 })
  await page.screenshot({ path: path.join(SHOT_DIR, '02_模型服务页_H3启动后Healthy.png'), fullPage: true })

  // 3. 服务日志抽屉:默认 100 行,行数可切换
  await page.getByTestId('service-card-minimax_h3').getByTestId('svc-logs').click()
  await expect(page.getByTestId('logs-drawer')).toBeVisible()
  await expect(page.getByTestId('logs-content')).toContainText('模拟日志第 99 行')
  await page.screenshot({ path: path.join(SHOT_DIR, '03_模型服务页_服务日志抽屉.png') })
  await page.keyboard.press('Escape')

  // 4. 停止保护:ComfyUI 运行且队列繁忙时,停止默认被阻断并要求二次确认
  await request.post(`${MOCK_AGENT}/_e2e/control`, { data: { action: 'set_service', name: 'comfyui', process_state: 'running', health_state: 'healthy' } })
  await page.reload()
  await expect(page.getByTestId('service-card-comfyui')).toContainText('Healthy', { timeout: 10000 })
  await request.post(`${MOCK_AGENT}/_e2e/control`, { data: { action: 'queue_busy', value: true } })

  await page.getByTestId('service-card-comfyui').getByTestId('svc-stop').click()
  await page.getByRole('button', { name: '确认' }).click() // 第一次确认
  await expect(page.getByText('ComfyUI 队列非空')).toBeVisible({ timeout: 10000 }) // 409 阻断原因
  await page.screenshot({ path: path.join(SHOT_DIR, '04_模型服务页_停止保护阻断提示.png') })
  await page.getByRole('button', { name: /仍然停止/ }).click() // 高风险二次确认
  await expect(page.getByTestId('service-card-comfyui')).toContainText('Stopped', { timeout: 10000 })
  await page.screenshot({ path: path.join(SHOT_DIR, '05_模型服务页_强制停止后.png'), fullPage: true })

  // 5. 操作日志:blocked 与 success 均落审计
  await page.goto('/server/operations')
  await expect(page.getByTestId('ops-table')).toContainText('service.stop')
  await expect(page.getByTestId('ops-table')).toContainText('blocked')
  await page.screenshot({ path: path.join(SHOT_DIR, '06_操作日志_服务动作审计.png'), fullPage: true })
})
