import { expect, test } from '@playwright/test'

test('login and evidence workspace are usable', async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  await page.goto('./login')
  await expect(page.getByRole('heading', { name: /每个结论/ })).toBeVisible()
  await expect(page.getByText('证据跳转', { exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('login.png'), fullPage: true })
  await page.getByRole('button', { name: /进入工作区/ }).click()
  await expect(page).toHaveURL(/minutestrace\/$/)
  await expect(page.getByRole('heading', { name: /会议数据总览/ })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('dashboard.png'), fullPage: true })
  if (testInfo.project.name.includes('mobile')) await page.getByRole('button', { name: '打开菜单' }).click()
  await page.getByRole('link', { name: '会议管理' }).click()
  await expect(page.getByRole('heading', { name: /会议不是文件夹/ })).toBeVisible()
  await page.getByText('证据化纪要发布评审', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '证据化纪要发布评审' })).toBeVisible()
  await page.getByRole('button', { name: /打开纪要/ }).click()
  await expect(page.getByRole('heading', { name: /结论旁边/ })).toBeVisible()
  expect(errors).toEqual([])
})
