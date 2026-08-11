import { expect, test } from '@playwright/test'

test('智能出入库：扫码识别商品 → 确认入库 → 库存增加', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('邮箱').fill('admin@inventoryos.dev')
  await page.getByLabel('密码').fill('Demo@12345')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByText('经营驾驶舱')).toBeVisible()

  await page.getByRole('link', { name: '仓库中心' }).click()
  const productRow = page.locator('tr', { hasText: 'A004 · 伺服电机 750W' })
  await expect(productRow.getByRole('cell').nth(2)).toHaveText('800')

  // 打开入库窗口，使用扫码识别而非下拉选择。
  await page.getByRole('button', { name: '入库' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByPlaceholder('扫描或输入条码').fill('6901000000004')
  await dialog.getByRole('button', { name: '识别' }).click()
  const candidate = dialog.locator('button', { hasText: 'A004' })
  await expect(candidate.first()).toBeVisible()
  await candidate.first().click()

  await dialog.locator('select').nth(1).selectOption({ label: 'WH01 · 华东一号仓' })
  await dialog.getByPlaceholder('数量 *').fill('10')
  await dialog.getByRole('button', { name: '提交' }).click()
  await expect(dialog).not.toBeVisible()

  await expect(productRow.getByRole('cell').nth(2)).toHaveText('810')
})
