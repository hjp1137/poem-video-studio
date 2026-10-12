import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import { makePng } from './helpers/png'

const SHOT_DIR = path.resolve(import.meta.dirname, '../../Walkthroughes/screenshots/20260928_批量下载多版本与参数管理')
mkdirSync(SHOT_DIR, { recursive: true })
const MOCK = 'http://127.0.0.1:8310'

const TEMPLATE = {
  '28': { class_type: 'LoadImage', inputs: { image: 'x.png' } },
  '16': { class_type: 'VLLMOmniGenerateVideo', inputs: { prompt: '', url: 'http://mock/v1' } },
  '13': { class_type: 'SaveVideo', inputs: { filename_prefix: 'x' } },
}
const MAP = [
  'name: e2e输出模板', 'nodes:', '  image:', '    id: "28"', '    input: image',
  '  prompt:', '    id: "16"', '    input: prompt', '  save:', '    id: "13"', '    input: filename_prefix',
].join('\n')

async function waitTaskStatus(page: import('@playwright/test').Page, batchId: string, scene: string, status: string) {
  for (let i = 0; i < 30; i++) {
    const resp = await page.request.get(`/api/batches/${batchId}/tasks`)
    const tasks = (await resp.json()) as Array<{ scene_key: string; status: string; comfy_prompt_id?: string }>
    if (tasks.find((t) => t.scene_key === scene)?.status === status) return tasks
    await page.waitForTimeout(1000)
  }
  throw new Error(`等待任务 ${scene} 变 ${status} 超时`)
}

test('多版本输出、批量下载与参数管理闭环', async ({ page }) => {
  test.setTimeout(240_000)
  await page.request.post(`${MOCK}/_e2e/control`, { data: { action: 'reset' } })
  await page.request.post('/api/server/services/comfyui/start').catch(() => {})
  await (await page.request.post('/api/workflows', { data: { name: 'e2e输出模板', workflow_api: TEMPLATE, map_yaml: MAP } })).json()
  await page.request.put('/api/workflows/default', { data: { name: 'e2e输出模板' } })

  // 1. 上传一张图 + 建批次(单场景,自动入队)
  const up = await page.request.post('/api/uploads', {
    multipart: { files: { name: 'cover.png', mimeType: 'image/png', buffer: makePng(60, 40, [9, 9, 9]) } },
  })
  const upload = (await up.json()) as { files: Array<{ upload_id: string }> }
  const created = await page.request.post('/api/batches', {
    data: {
      title: '多版本演示', dynasty: '唐', author: '测试',
      raw_batch_text: 'POEM_VIDEO_BATCH_V1\n\n[SCENE:cover]\nspeech: 一句。\nprompt: 画面。\n',
      image_bindings: { cover: upload.files[0].upload_id },
    },
  })
  expect(created.ok()).toBeTruthy(), await created.text()
  expect(created.ok()).toBeTruthy(), await created.text()
  const batch = (await created.json()) as { id: string }
  // API 建批次不经过前端,显式提交入队(页面路径的自动入队由 batch-create 用例覆盖)
  await page.request.post(`/api/batches/${batch.id}/submit`)
  const queued = await waitTaskStatus(page, batch.id, 'cover', 'queued')
  const promptId1 = queued.find((t) => t.scene_key === 'cover')!.comfy_prompt_id!

  // 2. mock 标记完成 → 等对账 → v1
  await page.request.post(`${MOCK}/_e2e/control`, { data: { action: 'set_history', prompt_id: promptId1 } })
  await waitTaskStatus(page, batch.id, 'cover', 'completed')
  await page.goto(`/batches/${batch.id}`)
  await expect(page.getByTestId('task-table')).toContainText('完成')
  await page.screenshot({ path: path.join(SHOT_DIR, '01_第一版生成完成.png'), fullPage: true })

  // 3. 重试 → 新 prompt 完成 → v2,操作列出现 v1/v2 链接
  await page.getByTestId('retry-btn').first().click()
  const queued2 = await waitTaskStatus(page, batch.id, 'cover', 'queued')
  const promptId2 = queued2.find((t) => t.scene_key === 'cover')!.comfy_prompt_id!
  expect(promptId2).not.toBe(promptId1)
  await page.request.post(`${MOCK}/_e2e/control`, { data: { action: 'set_history', prompt_id: promptId2 } })
  await waitTaskStatus(page, batch.id, 'cover', 'completed')
  await page.reload()
  await expect(page.getByTestId('version-links')).toBeVisible()
  await expect(page.getByTestId('version-links').locator('a')).toHaveCount(2)
  await page.screenshot({ path: path.join(SHOT_DIR, '02_重试后两个版本.png'), fullPage: true })

  // 4. 勾选复选框批量下载(zip)
  await page.getByRole('row', { name: '封面' }).locator('.el-checkbox').first().click()
  await expect(page.getByTestId('download-selected-btn')).toContainText('1')
  const tasksNow = (await (await page.request.get(`/api/batches/${batch.id}/tasks`)).json()) as Array<{ id: string }>
  const zipResp = await page.request.get(`/api/batches/${batch.id}/download?task_ids=${tasksNow[0].id}`)
  expect(zipResp.ok()).toBeTruthy()
  expect(zipResp.headers()['content-type']).toContain('application/zip')
  const head = (await zipResp.body()).subarray(0, 2)
  expect(Buffer.from(head).toString()).toBe('PK')
  await page.screenshot({ path: path.join(SHOT_DIR, '03_勾选批量下载.png'), fullPage: true })

  // 5. 展开参数管理:改 width 与 prompt 保存并断言生效
  await page.locator('.el-table__expand-icon').first().click()
  await expect(page.getByTestId('params-panel-cover')).toBeVisible()
  await page.getByTestId('param-prompt').fill('改后的画面提示词')
  await page.getByTestId('param-width').locator('input').fill('1024')
  await page.getByTestId('param-width').locator('input').press('Enter')
  await page.getByTestId('save-params-btn').click()
  await expect(page.getByText('参数已保存')).toBeVisible()
  const after = (await (await page.request.get(`/api/batches/${batch.id}/tasks`)).json()) as Array<{
    scene_key: string
    width: number
    prompt: string
  }>
  expect(after[0].width).toBe(1024)
  expect(after[0].prompt).toBe('改后的画面提示词')
  await page.screenshot({ path: path.join(SHOT_DIR, '04_参数管理修改保存.png'), fullPage: true })

  // 清理
  await page.request.post(`/api/batches/${batch.id}/cancel-queued`)
  await page.request.delete('/api/workflows/e2e输出模板')
})
