import { expect, test } from '@playwright/test'

test('核心经营链路：登录→商品→订单→确认→交付→风险', async ({ page }) => {
  // 1. 登录
  await page.goto('/login')
  await page.getByLabel('邮箱').fill('admin@inventoryos.dev')
  await page.getByLabel('密码').fill('Demo@12345')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByText('经营驾驶舱')).toBeVisible()

  // 2. 打开商品 A
  await page.getByRole('link', { name: '商品中心' }).click()
  await page.getByRole('link', { name: 'A001' }).first().click()
  await expect(page.getByText('精密铝合金板材 6061')).toBeVisible()
  await expect(page.getByText('On Hand')).toBeVisible()

  // 3. 创建订单
  await page.getByRole('link', { name: '订单中心' }).click()
  await page.getByRole('button', { name: '新建订单' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.locator('select').nth(0).selectOption({ label: 'C001 · 华东电子科技有限公司' })
  await dialog.locator('select').nth(1).selectOption({ label: 'A001 · 精密铝合金板材 6061' })
  await dialog.getByPlaceholder('数量 *').fill('200')
  await dialog.getByPlaceholder('成交价').fill('116')
  await page.getByRole('button', { name: '创建草稿' }).click()
  await expect(page.getByText('DRAFT').first()).toBeVisible()

  // 4. 确认订单：Reserved/Available 变化
  const newOrderRow = page.locator('tr', { hasText: 'DRAFT' }).last()
  const orderNo = (await newOrderRow.locator('a').first().textContent()) ?? ''
  await newOrderRow.getByRole('button', { name: '确认' }).click()
  const confirmedRow = page.locator('tr', { hasText: orderNo })
  await expect(confirmedRow.getByText('CONFIRMED')).toBeVisible()

  await page.getByRole('link', { name: '仓库中心' }).click()
  const productRow = page.locator('tr', { hasText: 'A001 · 精密铝合金板材 6061' }).first()
  await expect(productRow.getByRole('cell').nth(4)).toHaveText(/240/)

  // 5. 部分交付 → PARTIAL
  await page.getByRole('link', { name: '订单中心' }).click()
  await page.locator('tr', { hasText: orderNo }).getByRole('link').first().click()
  await page.getByRole('button', { name: '交付' }).first().click()
  await page.locator('input').first().fill('100')
  await page.getByRole('button', { name: '确认交付' }).click()
  await expect(page.getByText('PARTIAL')).toBeVisible()

  // 6. 商品时间线含出库事件
  await page.getByRole('link', { name: '商品中心' }).click()
  await page.getByRole('link', { name: 'A001' }).first().click()
  await expect(page.getByText('inventory.shipped').first()).toBeVisible()

  // 7. 库存风险（A003 临期批次 → EXPIRY_RISK；已预留订单不再误报缺货）
  await page.getByRole('link', { name: '风险中心' }).click()
  await expect(page.getByText('EXPIRY_RISK').first()).toBeVisible()

  // 8. 采购页“全部到货”必须带 lines body，而不是 422。
  await page.getByRole('link', { name: '采购中心' }).click()
  const poRow = page.locator('tr', { hasText: 'PO-' }).first()
  await poRow.getByRole('button', { name: '全部到货' }).click()
  await expect(poRow.getByText('RECEIVED')).toBeVisible()
})
