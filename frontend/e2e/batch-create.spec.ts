import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { makePng } from './helpers/png'

const SHOT_DIR = path.resolve(import.meta.dirname, '../../Walkthroughes/screenshots/20260921_任务01_工程骨架与批量输入解析')
const TEMPLATE_SHOT_DIR = path.resolve(import.meta.dirname, '../../Walkthroughes/screenshots/20260928_批量文本模板下载')
mkdirSync(TEMPLATE_SHOT_DIR, { recursive: true })

const SAMPLE_TEXT = `POEM_VIDEO_BATCH_V1

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
水墨风格封面,江面晨雾缭绕,标题文字保持清晰稳定,
整体画面安静克制,仅有轻微雾气流动。

[SCENE:1]
speech: 移舟,泊烟渚。
prompt:
一叶扁舟缓缓停靠烟雾迷蒙的小洲,水面微波荡漾,
船夫撑篙动作轻缓,远山朦胧。

[SCENE:2]
speech: 日暮,客愁新。
prompt:
黄昏落日,旅人独立船头眺望远方,衣摆随风轻摆,
天边云霞缓慢流动,水面泛起金色波光。

[SCENE:3]
speech: 野旷,天低树。
prompt:
旷野辽阔,远树低垂,天地相接,薄雾缓缓飘动,
镜头轻微推移,层次分明。

[SCENE:4]
speech: 江清,月近人。
prompt:
夜色澄澈,明月倒映江中,波光粼粼,
月光随水波轻轻晃动,静谧安详。`

test.beforeAll(() => {
  mkdirSync(SHOT_DIR, { recursive: true })
})

// 任务04/05 引入 Mock Agent 后,ComfyUI 假端点随 comfyui 服务状态启停;
// 复位保证本用例仍按「ComfyUI 不可达」路径断言
test.beforeEach(async ({ request }) => {
  await request.post('http://127.0.0.1:8310/_e2e/control', { data: { action: 'reset' } }).catch(() => {})
})

/** 通过键盘导航把某张图片绑定到指定场景。
 *  说明:Element Plus 用过的下拉 popper 会残留在 DOM 且带包围盒,
 *  CSS 定位不可靠,因此用 ArrowDown/Enter 只与当前打开的下拉交互;
 *  选项顺序 = 场景顺序,N 次 ArrowDown 高亮第 N 项(封面 cover 为第 1 项)。 */
async function rebind(page: Page, cardText: string | null, arrowDownTimes: number) {
  const card = cardText
    ? page.locator('[data-testid="image-card"]', { hasText: cardText }).first()
    : page.locator('[data-testid="image-card"]').first()
  await card.locator('[data-testid="bind-select"]').click()
  await page.waitForTimeout(400)
  for (let i = 0; i < arrowDownTimes; i++) {
    await page.keyboard.press('ArrowDown')
  }
  await page.keyboard.press('Enter')
  await page.waitForTimeout(300)
}

test('解析失败时显示错误位置且禁止创建', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('诗影工坊')).toBeVisible()
  await page.getByTestId('batch-textarea').fill('POEM_VIDEO_BATCH_V2\n\n[SCENE:1]\nspeech: 一句。\nprompt: 画面。\n')
  await page.getByTestId('parse-btn').click()
  await expect(page.getByTestId('error-list')).toContainText('POEM_VIDEO_BATCH_V1')
  // 有错误时不出现场景预览,也没有可用的创建入口
  await expect(page.getByTestId('scene-card')).toHaveCount(0)
  await page.screenshot({ path: path.join(SHOT_DIR, '04_新建批量任务_解析错误提示.png'), fullPage: true })
})

test('任务01验收闭环:上传→解析→绑定→创建批次(自动入队)→刷新持久', async ({ page }) => {
  // 前置:启动 mock ComfyUI 并设置默认模板,创建批次后才能自动入队
  await page.request.post('/api/server/services/comfyui/start').catch(() => {})
  const inlineTemplate = {
    '28': { class_type: 'LoadImage', inputs: { image: 'x.png' } },
    '16': { class_type: 'VLLMOmniGenerateVideo', inputs: { prompt: '', url: 'http://mock/v1' } },
    '13': { class_type: 'SaveVideo', inputs: { filename_prefix: 'x' } },
  }
  const inlineMap = [
    'name: e2e内联模板',
    'nodes:',
    '  image:',
    '    id: "28"',
    '    input: image',
    '  prompt:',
    '    id: "16"',
    '    input: prompt',
    '  save:',
    '    id: "13"',
    '    input: filename_prefix',
  ].join('\n')
  const saveResp = await page.request.post('/api/workflows', {
    data: { name: 'e2e内联模板', workflow_api: inlineTemplate, map_yaml: inlineMap },
  })
  expect(saveResp.ok()).toBeTruthy()
  await page.request.put('/api/workflows/default', { data: { name: 'e2e内联模板' } })

  await page.goto('/')
  await expect(page.getByText('批量任务文本')).toBeVisible()

  // 标题旁的模板下载链接:可见、指向后端端点、端点内容以版本头开始
  const templateLink = page.getByTestId('template-link')
  await expect(templateLink).toBeVisible()
  await expect(templateLink).toHaveText('下载文本模板')
  await expect(templateLink).toHaveAttribute('href', '/api/batches/text-template')
  const tmplResp = await page.request.get('/api/batches/text-template')
  expect(tmplResp.ok()).toBeTruthy()
  expect((await tmplResp.text()).startsWith('POEM_VIDEO_BATCH_V1')).toBeTruthy()
  await page.screenshot({ path: path.join(TEMPLATE_SHOT_DIR, '01_新建批量任务_标题旁下载模板链接.png'), fullPage: true })

  await page.screenshot({ path: path.join(SHOT_DIR, '01_新建批量任务_页面初始状态.png'), fullPage: true })

  // 1. 一次上传 5 张图(封面 + 4 句场景图)
  const images = [
    { name: 'cover.png', mimeType: 'image/png', buffer: makePng(320, 240, [46, 74, 68]) },
    { name: '01.png', mimeType: 'image/png', buffer: makePng(320, 240, [58, 92, 130]) },
    { name: '02.png', mimeType: 'image/png', buffer: makePng(320, 240, [186, 128, 66]) },
    { name: '03.png', mimeType: 'image/png', buffer: makePng(320, 240, [118, 88, 142]) },
    { name: '04.png', mimeType: 'image/png', buffer: makePng(320, 240, [92, 100, 110]) },
  ]
  await page.setInputFiles('input[type=file]', images)
  await expect(page.getByTestId('image-card')).toHaveCount(5)
  await expect(page.getByText('识别:cover')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '02_新建批量任务_图片上传后.png'), fullPage: true })

  // 2. 一次粘贴整首诗批量文本并解析
  await page.getByTestId('batch-textarea').fill(SAMPLE_TEXT)
  await page.getByTestId('parse-btn').click()
  await expect(page.getByTestId('scene-card')).toHaveCount(5)
  await expect(page.getByTestId('stats-text')).toContainText('共 5 个场景')
  await expect(page.getByTestId('stats-text')).toContainText('已绑定 5 张图片')
  await expect(page.getByText('可以创建批次')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '03_新建批量任务_解析结果场景预览.png'), fullPage: true })

  // 3. 手工重绑定验证:cover.png 改绑场景 2(交换绑定),cover 场景变为未绑定
  await rebind(page, null, 3) // cover.png → 场景 2
  await expect(page.getByTestId('scene-card').filter({ hasText: '封面' })).toContainText('未绑定图片')
  await expect(page.getByTestId('stats-text')).toContainText('已绑定 4 张图片')
  // 再次点击「解析任务」重跑自动绑定:未绑定的 cover 场景由空闲的 02.png 补齐
  await page.getByTestId('parse-btn').click()
  await expect(page.getByTestId('stats-text')).toContainText('已绑定 5 张图片')
  await expect(page.getByText('可以创建批次')).toBeVisible()

  // 4. 创建批次(应自动进入生成队列)
  await page.getByTestId('create-btn').click()
  await expect(page).toHaveURL(/\/batches\/[0-9a-f]+/)
  await expect(page.getByTestId('default-template-tag')).toContainText('生成模板:e2e内联模板')
  const batchId = page.url().split('/').pop() as string
  await expect(page.getByTestId('task-table').locator('tbody tr')).toHaveCount(5)
  await expect(page.getByText('总进度:0 / 5 已完成')).toBeVisible()
  // 全部任务自动入队(排队中)
  await expect(page.getByTestId('task-table')).toContainText('排队中')
  await expect(page.getByTestId('task-table').getByText('排队中')).toHaveCount(5)
  await page.screenshot({ path: path.join(SHOT_DIR, '05_批次详情_创建成功自动入队.png'), fullPage: true })

  // 5. 数据库落库校验:5 个 VideoTask 全部 queued
  const tasksResp = await page.request.get(`/api/batches/${batchId}/tasks`)
  expect(tasksResp.ok()).toBeTruthy()
  const tasks = (await tasksResp.json()) as Array<{ scene_key: string; status: string; speech: string }>
  expect(tasks.map((t) => t.scene_key)).toEqual(['cover', '1', '2', '3', '4'])
  expect(tasks.every((t) => t.status === 'queued')).toBeTruthy()
  expect(tasks[1].speech).toBe('移舟,泊烟渚。')

  // 6. 刷新后数据仍然存在
  await page.reload()
  await expect(page.getByTestId('task-table').locator('tbody tr')).toHaveCount(5)
  await expect(page.getByText('《宿建德江》')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '06_批次详情_刷新后数据持久.png'), fullPage: true })

  // 7. 批次列表:移除队列按钮(不加二次确认)→ 任务回待提交 → 按钮切换为提交队列 → 重新入队
  await page.goto('/batches')
  await expect(page.getByTestId('batch-table').locator('tbody tr').first()).toContainText('宿建德江')
  const firstRow = page.getByTestId('batch-table').locator('tbody tr').first()
  await expect(firstRow.getByTestId('cancel-queue-btn')).toBeVisible()
  await firstRow.getByTestId('cancel-queue-btn').click()
  await expect(firstRow.getByTestId('submit-queue-btn')).toBeVisible()
  await expect(firstRow).toContainText('已解析')
  await page.screenshot({ path: path.join(SHOT_DIR, '07_批次列表_移除队列后.png'), fullPage: true })
  await firstRow.getByTestId('submit-queue-btn').click()
  await expect(firstRow.getByTestId('cancel-queue-btn')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '08_批次列表_重新提交队列.png'), fullPage: true })

  // 8. 批次详情:重试按钮无二次确认弹窗,点击直接生成新任务
  await page.goto(`/batches/${batchId}`)
  await expect(page.getByText('《宿建德江》')).toBeVisible()
  // 排队中任务先移除队列,得到可重试的待提交任务
  await page.request.post(`/api/batches/${batchId}/cancel-queued`)
  await page.reload()
  await expect(page.getByText('总进度:0 / 5 已完成')).toBeVisible()
  await expect(page.getByText('确认重试该场景')).toHaveCount(0) // 无二次确认弹窗文案
  await page.getByTestId('retry-btn').first().click()
  await expect(page.getByTestId('task-table').getByText('排队中')).toHaveCount(1)
  await page.screenshot({ path: path.join(SHOT_DIR, '09_批次详情_重试直接执行无确认框.png'), fullPage: true })

  // 9. 系统状态卡片 + 清理本用例模板(恢复 workflows 用例的空态前提)
  await page.goto('/batches')
  await expect(page.getByTestId('system-status')).toContainText('ComfyUI HTTP')
  await page.screenshot({ path: path.join(SHOT_DIR, '07_批次列表_系统运行状态.png'), fullPage: true })
  await page.request.post(`/api/batches/${batchId}/cancel-queued`)
  await page.request.delete('/api/workflows/e2e内联模板')
})

test('任务02界面:批量提交确认、失败原因落库展示与重试入口', async ({ page }) => {
  // 通过 API 快速造一个批次(页面流程已由上一用例覆盖)
  const uploadResp = await page.request.post('/api/uploads', {
    multipart: {
      files: {
        name: 'cover.png',
        mimeType: 'image/png',
        buffer: makePng(60, 40, [10, 20, 30]),
      },
    },
  })
  expect(uploadResp.ok()).toBeTruthy()
  const upload = (await uploadResp.json()) as { files: Array<{ upload_id: string }> }
  const createResp = await page.request.post('/api/batches', {
    data: {
      title: '提交失败演示',
      dynasty: '唐',
      author: '测试',
      raw_batch_text: 'POEM_VIDEO_BATCH_V1\n\n[SCENE:cover]\nspeech: 演示。\nprompt: 演示画面。\n',
      image_bindings: { cover: upload.files[0].upload_id },
    },
  })
  expect(createResp.ok()).toBeTruthy()
  const batch = (await createResp.json()) as { id: string }

  await page.goto(`/batches/${batch.id}`)
  await expect(page.getByText('ComfyUI 不可达')).toBeVisible()
  await expect(page.getByTestId('submit-all-btn')).toBeVisible()

  // 批量操作二次确认框
  await page.getByTestId('submit-all-btn').click()
  await expect(page.getByText('是否继续?')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '08_批次详情_全部加入生成队列确认框.png') })
  await page.getByRole('button', { name: '提交' }).click()

  // 本机无真实 ComfyUI/模板:任务失败,错误原因必须可见且可诊断,重试按钮可用
  await expect(page.getByTestId('task-table').locator('tbody tr').first()).toContainText('失败', { timeout: 30000 })
  await expect(page.getByText('未设置默认 Workflow 模板').first()).toBeVisible()
  await page.screenshot({
    path: path.join(SHOT_DIR, '09_批次详情_提交失败与错误原因.png'),
    fullPage: true,
  })
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
})
