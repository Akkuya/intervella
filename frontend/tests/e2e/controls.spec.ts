import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockAPI } from './fixtures.ts'
import { choose, selectTrigger } from './control-helpers.ts'
test('custom selectors retain keyboard, themed scrolling and forced colors', async ({ page }) => {
  await mockAPI(page)
  await page.goto('/')
  const duration = selectTrigger(page, 'Duration')
  await duration.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('listbox')).toBeVisible()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(duration).toContainText('90 minutes')
  await expect(duration).toBeFocused()
  await choose(page, 'Appearance', 'dark')
  await page.getByRole('link', { name: 'Building schedules', exact: true }).click()
  const scroll = page.locator('.calendar-scroll')
  await expect(scroll).toBeVisible()
  const dark = await scroll.evaluate((el) => getComputedStyle(el).scrollbarColor)
  await choose(page, 'Appearance', 'light')
  expect(await scroll.evaluate((el) => getComputedStyle(el).scrollbarColor)).not.toBe(dark)
  await page.emulateMedia({ forcedColors: 'active', reducedMotion: 'reduce' })
  await selectTrigger(page, 'Building').click()
  await expect(page.getByRole('listbox')).toBeVisible()
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  await page.keyboard.press('Escape')
  await expect(selectTrigger(page, 'Building')).toBeFocused()
})
