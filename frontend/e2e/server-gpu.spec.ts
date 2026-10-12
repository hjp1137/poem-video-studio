import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'

const SHOT_DIR = path.resolve(import.meta.dirname, '../../Walkthroughes/screenshots/20260922_任务04_ServerAgent与GPU状态功耗管理')

const MOCK_AGENT = 'http://127.0.0.1:8310'

test.beforeAll(() => {
  mkdirSync(SHOT_DIR, { recursive: true })
})

test.beforeEach(async ({ request }) => {
  await request.post(`${MOCK_AGENT}/_e2e/control`, { data: { action: 'reset' } })
})

test('任务04验收:GPU 状态展示、功耗设置闭环与操作审计', async ({ page, request }) => {
  await page.goto('/server/gpu')
  await expect(page.getByTestId('gpu-summary')).toBeVisible()

  // 1. 4 张 4090 卡片与摘要
  for (let i = 0; i < 4; i++) {
    await expect(page.getByTestId(`gpu-card-${i}`)).toContainText('RTX 4090')
    await expect(page.getByTestId(`gpu-card-${i}`)).toContainText('300W') // 初始功耗上限
  }
  await expect(page.getByTestId('gpu-summary')).toContainText('4 张')
  await expect(page.getByTestId('gpu-summary')).toContainText('96.0 GB') // 4×24564MiB 总显存
  await expect(page.getByTestId('gpu-summary')).toContainText('最高温度')
  // GPU 进程展示且标注只读,无 kill 入口
  await expect(page.getByTestId('gpu-card-0')).toContainText('PID 12345')
  await expect(page.getByTestId('gpu-card-0')).toContainText('非受管进程 · 只读')
  await expect(page.getByRole('button', { name: 'Kill' })).toHaveCount(0)
  await page.screenshot({ path: path.join(SHOT_DIR, '01_GPU页_四卡状态与摘要.png'), fullPage: true })

  // 2. 全部设置为 280W:确认框 → 完成后卡片显示实测值
  await page.getByTestId('bulk-watts-input').locator('input').fill('280')
  await page.getByTestId('bulk-apply-btn').click()
  await expect(page.getByText('将 GPU0-3 Power Limit 设置为 280W?')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '02_GPU页_全部设置功耗确认框.png') })
  await page.getByRole('button', { name: '确认修改' }).click()
  await expect(page.getByText(/全部 4 张 GPU 已设置为 280W/)).toBeVisible()
  for (let i = 0; i < 4; i++) {
    await expect(page.getByTestId(`gpu-card-${i}`)).toContainText('280W')
  }
  await page.screenshot({ path: path.join(SHOT_DIR, '03_GPU页_设置成功后实测280W.png'), fullPage: true })

  // 3. 单卡修改:GPU2 设为 320W
  await page.getByTestId('card-watts-2').locator('input').fill('320')
  await page.getByTestId('card-apply-2').click()
  await expect(page.getByText('将 GPU2 Power Limit 设置为 320W?')).toBeVisible()
  await page.getByRole('button', { name: '确认修改' }).click()
  await expect(page.getByText(/GPU2 已设置,实测值 320W/)).toBeVisible()
  await expect(page.getByTestId('gpu-card-2')).toContainText('320W')

  // 4. 超出驱动区间的值被拒绝,失败原因可见
  await page.getByTestId('bulk-watts-input').locator('input').fill('50')
  await page.getByTestId('bulk-apply-btn').click()
  await page.getByRole('button', { name: '确认修改' }).click()
  await expect(page.getByText(/超出驱动允许区间/)).toBeVisible({ timeout: 10000 })
  await page.screenshot({ path: path.join(SHOT_DIR, '04_GPU页_超出区间失败提示.png') })

  // 5. 默认功耗 + 开机自动应用
  await page.getByTestId('default-watts-input').locator('input').fill('280')
  await page.getByTestId('default-save-btn').click()
  await page.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText(/默认功耗已保存/)).toBeVisible()
  await page.getByTestId('auto-apply-switch').click()
  await expect(page.getByText('开机自动应用已开启')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '05_GPU页_默认功耗与开机自动应用.png'), fullPage: true })

  // 6. Agent 离线:显示横幅,不显示 0 张卡
  await request.post(`${MOCK_AGENT}/_e2e/control`, { data: { action: 'offline', value: true } })
  await expect(page.getByTestId('agent-offline-banner')).toBeVisible({ timeout: 10000 })
  await expect(page.getByTestId('agent-offline-banner')).toContainText('Agent 离线')
  await page.screenshot({ path: path.join(SHOT_DIR, '06_GPU页_Agent离线提示.png'), fullPage: true })
  await request.post(`${MOCK_AGENT}/_e2e/control`, { data: { action: 'offline', value: false } })

  // 7. 操作日志:功耗修改全部落审计(含失败项与来源 IP)
  await page.goto('/server/operations')
  await expect(page.getByTestId('ops-table')).toContainText('gpu.power_limit_bulk')
  await expect(page.getByTestId('ops-table')).toContainText('gpu.power_limit')
  await expect(page.getByTestId('ops-table')).toContainText('127.0.0.1')
  await expect(page.getByTestId('ops-table')).toContainText('success')
  await expect(page.getByTestId('ops-table')).toContainText('failed')
  await page.screenshot({ path: path.join(SHOT_DIR, '07_操作日志_功耗修改审计.png'), fullPage: true })
})
