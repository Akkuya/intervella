import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockAPI } from './fixtures.ts'

test.beforeEach(async ({ page }) => {
  await mockAPI(page)
})

test('system theme, stored appearance, full identifiers and friendly times', async ({
  page,
}, testInfo) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto('/')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.getByLabel('Appearance')).toHaveValue('system')
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeVisible()
  await expect(page.locator('.time-strip')).toContainText('8:00 AM')
  await expect(page.locator('.time-strip')).not.toContainText('GMT')
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('dark-search.png'), fullPage: true })
  await page.getByLabel('Appearance').selectOption('light')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await expect(page.getByLabel('Appearance')).toHaveValue('light')
  await page.getByRole('link', { name: 'View SYN-A-101' }).click()
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeVisible()
  await page.getByLabel('Appearance').selectOption('system')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.emulateMedia({ colorScheme: 'light' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
})

test('blocked browser storage does not prevent appearance changes or searches', async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', {
      get() {
        throw new Error('blocked')
      },
    })
  })
  await page.goto('/')
  await page.getByLabel('Appearance').selectOption('dark')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.getByRole('link', { name: 'View SYN-A-101' })).toBeVisible()
})
