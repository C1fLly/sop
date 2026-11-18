import { test, expect } from '@playwright/test'
test('记一笔后合计变了，页面和基准截图一致', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('total')).toHaveText('一共 12.50 元，共 1 笔')
  await page.getByLabel('说明').fill('水')
  await page.getByLabel('金额').fill('3')
  await page.getByRole('button', { name: '记一笔' }).click()
  await expect(page.getByTestId('total')).toHaveText('一共 15.50 元，共 2 笔')
  await expect(page).toHaveScreenshot('ledger.png')
})
