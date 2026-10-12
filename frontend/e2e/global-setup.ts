import { rmSync } from 'node:fs'
import path from 'node:path'

/** 在 webServer 启动前尽力清理 E2E 隔离数据目录;若被瞬态文件锁挡住则跳过,
 *  测试断言不依赖绝对数据量。 */
export default function globalSetup() {
  const e2eData = path.resolve(import.meta.dirname, '../../backend/.e2e-data')
  try {
    rmSync(e2eData, { recursive: true, force: true })
  } catch {
    // Windows 下 SQLite 句柄释放有延迟,忽略;用例按“最新批次”断言
  }
}
