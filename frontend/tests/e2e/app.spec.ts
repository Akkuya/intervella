import { visit } from './control-helpers.ts'
import { choose } from './control-helpers.ts'
import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockAPI } from './fixtures.ts'

test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})

test('search, room schedule, URL navigation and accessible responsive layout', async ({
  page,
}, testInfo) => {
  await visit(page, '/')
  await expect(page.getByRole('heading', { name: 'Find a room between classes.' })).toBeVisible()
  await expect(page.getByText('Unverified / demo data', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
  await expect(page.getByText('3 rooms excluded', { exact: false })).toBeVisible()
  await choose(page, 'Building', 'SYN-A')
  await expect(page.getByRole('heading', { name: 'Schedule available', exact: true })).toBeVisible()
  await expect(page).toHaveURL(/building=SYN-A/)
  await page.getByRole('link', { name: 'View SYN-A-101' }).click()
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /Cancelled event/ })).toBeVisible()
  await expect(page).toHaveURL(/room=1/)
  await page.goBack()
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeFocused()
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  )
  expect(overflow).toBe(false)
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('search.png'), fullPage: true })
})
