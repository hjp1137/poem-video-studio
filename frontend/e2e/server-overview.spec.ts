import { mkdirSync, readdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'

const SHOT_DIR = path.resolve(import.meta.dirname, '../../Walkthroughes/screenshots/20260922_任务05_模型服务管理与H3环境一键准备')

const MOCK_AGENT = 'http://127.0.0.1:8310'

test.beforeAll(() => {
  mkdirSync(SHOT_DIR, { recursive: true })
})

test.beforeEach(async ({ request }) => {
  await request.post(`${MOCK_AGENT}/_e2e/control`, { data: { action: 'reset' } })
  // 清掉旧编号截图(手动分项改造后重新归档)
  for (const f of readdirSync(SHOT_DIR)) {
    if (/^(0[7-9]|1[0-9])_/.test(f)) rmSync(path.join(SHOT_DIR, f))
  }
})

test('任务05验收:手动分项准备视频环境与批量页联动', async ({ page }) => {
  await page.goto('/server')
  await expect(page.getByTestId('env-card')).toBeVisible()

  // 1. 初始 NOT READY,手动逐项卡片展示;冲突服务为自动检测清单(非 Profile 写死)
  await expect(page.getByTestId('env-ready-tag')).toHaveText('NOT READY')
  await expect(page.getByTestId('manual-prep-card')).toBeVisible()
  await expect(page.getByTestId('prep-item-power')).toContainText('设置 GPU 功耗')
  await expect(page.getByTestId('prep-stop-head')).toContainText('停止冲突服务')
  await expect(page.getByTestId('prep-stop-head')).toContainText('自动检测')
  await expect(page.getByTestId('prep-item-conflict-wl-magic-pdf-server')).toContainText('容器:magic-pdf-server')
  await expect(page.getByTestId('prep-item-conflict-wl-magic-pdf-server')).toContainText('11190')
  await expect(page.getByTestId('prep-item-conflict-wl-bge-m3-server')).toContainText('容器:bge-m3-server')
  // Profile 登记且仍在运行的 ollama(未占 GPU)也列出
  await expect(page.getByTestId('prep-item-conflict-svc-ollama')).toContainText('Profile 登记')
  await expect(page.getByTestId('prep-item-start-minimax_h3')).toContainText('MiniMax H3')
  await expect(page.getByTestId('prep-item-start-comfyui')).toContainText('ComfyUI')
  await expect(page.getByTestId('prepare-btn')).toHaveCount(0)
  await page.screenshot({ path: path.join(SHOT_DIR, '07_服务器总览_手动分项与自动检测冲突服务.png'), fullPage: true })

  // 2. ① 设置 GPU 功耗:当前 300W → 目标 280W,确认框后生效
  await expect(page.getByTestId('prep-power-state')).toContainText('当前 300W / 目标 280W')
  await page.getByTestId('prep-power-btn').click()
  await expect(page.getByText('将 GPU0-3 Power Limit 设置为 280W?')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '08_手动准备_功耗设置确认框.png') })
  await page.getByRole('button', { name: '确认修改' }).click()
  await expect(page.getByText(/全部 4 张 GPU 已设置为 280W/)).toBeVisible()
  await expect(page.getByTestId('prep-power-done')).toContainText('已是目标值 280W')
  await page.screenshot({ path: path.join(SHOT_DIR, '09_手动准备_功耗设置完成.png'), fullPage: true })

  // 3. ② 停止冲突服务:逐个停止自动检测出的容器 + Profile 登记的 ollama
  await page.getByTestId('prep-conflict-stop-wl-magic-pdf-server').click()
  await expect(page.getByText('确认停止容器 magic-pdf-server?')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '10_手动准备_停止冲突容器确认框.png') })
  await page.getByRole('button', { name: '确认停止' }).click()
  await expect(page.getByText(/magic-pdf-server 已停止,释放约 11190 MiB 显存/)).toBeVisible()

  await page.getByTestId('prep-conflict-stop-wl-bge-m3-server').click()
  await page.getByRole('button', { name: '确认停止' }).click()
  await expect(page.getByTestId('prep-item-conflict-wl-bge-m3-server')).toHaveCount(0, { timeout: 10000 })

  await page.getByTestId('prep-conflict-stop-svc-ollama').click()
  await page.getByRole('button', { name: '确认停止' }).click()
  await expect(page.getByTestId('prep-conflict-none')).toContainText('无占用 GPU 的冲突服务', { timeout: 10000 })
  await page.screenshot({ path: path.join(SHOT_DIR, '11_手动准备_冲突服务全部停止.png'), fullPage: true })

  // 4. ③ 启动 MiniMax H3(等待健康转为 Healthy)
  await page.getByTestId('prep-start-btn-minimax_h3').click()
  await expect(page.getByText(/MiniMax H3 已启动/)).toBeVisible()
  await expect(page.getByTestId('prep-start-done-minimax_h3')).toBeVisible({ timeout: 30000 })
  await page.screenshot({ path: path.join(SHOT_DIR, '12_手动准备_H3启动就绪.png'), fullPage: true })

  // 5. ④ 启动 ComfyUI → 全部就绪 READY
  await page.getByTestId('prep-start-btn-comfyui').click()
  await expect(page.getByTestId('prep-start-done-comfyui')).toBeVisible({ timeout: 30000 })
  await expect(page.getByTestId('env-ready-tag')).toHaveText('READY', { timeout: 15000 })
  await page.screenshot({ path: path.join(SHOT_DIR, '13_手动准备_全部就绪READY.png'), fullPage: true })

  // 6. 幂等视觉:READY 后各操作项均为 ✓,无重复操作入口
  await expect(page.getByTestId('prep-power-done')).toBeVisible()
  await expect(page.getByTestId('prep-conflict-none')).toBeVisible()
  await expect(page.getByTestId('prep-start-btn-comfyui')).toHaveCount(0)
  await page.screenshot({ path: path.join(SHOT_DIR, '14_手动准备_READY后各项就绪无重复入口.png'), fullPage: true })

  // 7. 批量页面环境条联动:READY 状态可见(不自动改变服务器状态)
  await page.goto('/batches')
  await expect(page.getByTestId('env-banner-ready')).toContainText('视频环境:READY')
  await page.screenshot({ path: path.join(SHOT_DIR, '15_批次列表_环境条READY.png'), fullPage: true })

  // 8. 新建批量任务页同样显示环境条
  await page.goto('/')
  await expect(page.getByTestId('env-banner-ready')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '16_新建批量任务_环境条READY.png'), fullPage: true })

  // 9. 操作日志记录手动分项动作(功耗 + 容器停止 + 服务启停)
  await page.goto('/server/operations')
  await expect(page.getByTestId('ops-table')).toContainText('gpu.power_limit_bulk')
  await expect(page.getByTestId('ops-table')).toContainText('workload.docker_stop')
  await expect(page.getByTestId('ops-table')).toContainText('service.stop')
  await expect(page.getByTestId('ops-table')).toContainText('service.start')
  await page.screenshot({ path: path.join(SHOT_DIR, '17_操作日志_手动分项操作审计.png'), fullPage: true })
})
