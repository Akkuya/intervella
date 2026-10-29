import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mockAPI } from './fixtures.ts'

test('themed selectors and scrollbars retain keyboard and high-contrast behavior', async ({
  page,
}, testInfo) => {
  await mockAPI(page)
  await page.goto('/')
  for (const theme of ['light', 'dark']) {
    await page.getByLabel('Appearance').selectOption(theme)
    const controls = await page.locator('select').evaluateAll((elements) =>
      elements.map((element) => ({
        appearance: getComputedStyle(element).appearance,
        arrow: getComputedStyle(element).backgroundImage,
        padding: parseFloat(getComputedStyle(element).paddingRight),
      })),
    )
    expect(controls.length).toBeGreaterThan(3)
    expect(
      controls.every(
        (control) =>
          control.appearance === 'none' && control.arrow.includes('svg') && control.padding >= 32,
      ),
    ).toBe(true)
    await page.screenshot({ path: testInfo.outputPath(`selectors-${theme}.png`), fullPage: true })
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
  }
  const duration = page.getByRole('combobox', { name: 'Duration', exact: true })
  await duration.focus()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(duration).toHaveValue('90')
  await page.getByRole('link', { name: 'Building schedules', exact: true }).click()
  const scroll = page.locator('.calendar-scroll')
  await expect(scroll).toBeVisible()
  const dark = await scroll.evaluate((element) => getComputedStyle(element).scrollbarColor)
  await page.getByLabel('Appearance').selectOption('light')
  const light = await scroll.evaluate((element) => getComputedStyle(element).scrollbarColor)
  expect(light).not.toBe('auto')
  expect(light).not.toBe(dark)
  await page.emulateMedia({ forcedColors: 'active' })
  await expect(page.getByLabel('Appearance')).toHaveCSS('appearance', 'auto')
  await expect(page.getByLabel('Appearance')).toHaveCSS('background-image', 'none')
})
