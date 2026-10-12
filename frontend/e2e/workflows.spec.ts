import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'

const SHOT_DIR = path.resolve(import.meta.dirname, '../../Walkthroughes/screenshots/20260928_模板管理与默认模板')
mkdirSync(SHOT_DIR, { recursive: true })

test('模板管理闭环:导入 ComfyUI 工作流→保存→设默认→删除', async ({ page }) => {
  // 前置:确保 mock ComfyUI 在运行(object_info 可用)
  await page.request.post('/api/server/services/comfyui/start').catch(() => {})

  await page.goto('/workflows')
  await expect(page.getByText('从 ComfyUI 导入工作流')).toBeVisible()
  await expect(page.getByText('Workflow 模板')).toBeVisible()
  await expect(page.getByTestId('template-empty')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '01_模板管理_空状态.png'), fullPage: true })

  // 1. 来源列表与转换预览
  await page.getByTestId('refresh-sources-btn').click()
  await page.getByTestId('source-select').click()
  await page.getByRole('option', { name: 'ui_workflow_h3.json' }).click()
  await page.getByTestId('convert-btn').click()
  await expect(page.getByTestId('convert-preview')).toBeVisible()
  await expect(page.getByTestId('template-name-input')).toHaveValue('ui_workflow_h3')
  const mapText = await page.getByTestId('map-yaml-input').inputValue()
  expect(mapText).toContain('image:')
  expect(mapText).toContain('prompt:')
  await page.screenshot({ path: path.join(SHOT_DIR, '02_模板管理_转换预览与映射草稿.png'), fullPage: true })

  // 2. 保存模板
  await page.getByTestId('save-template-btn').click()
  await expect(page.getByTestId('template-table')).toBeVisible()
  await expect(page.getByTestId('template-table')).toContainText('ui_workflow_h3')
  await expect(page.getByTestId('template-table')).toContainText('可用')

  // 3. 设为默认
  await page.getByTestId('set-default-btn').first().click()
  await expect(page.getByTestId('template-table')).toContainText('默认')
  await page.screenshot({ path: path.join(SHOT_DIR, '03_模板管理_已保存并设为默认.png'), fullPage: true })

  // 4. 删除模板(默认模板删除后默认被清空)
  await page.getByTestId('delete-template-btn').first().click()
  await page.getByRole('button', { name: '确定' }).click()
  await expect(page.getByTestId('template-empty')).toBeVisible()
  await page.screenshot({ path: path.join(SHOT_DIR, '04_模板管理_删除后恢复空状态.png'), fullPage: true })
})
