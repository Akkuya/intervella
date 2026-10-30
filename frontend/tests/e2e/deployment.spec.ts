import { readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import { mockAPI } from './fixtures.ts'

const deployment = JSON.parse(
  readFileSync(new URL('../../../vercel.json', import.meta.url), 'utf8'),
)
const policy = deployment.headers[0].headers.find(
  (h: { key: string }) => h.key === 'Content-Security-Policy',
).value

test('student app works under deployed same-origin content security policy', async ({ page }) => {
  await mockAPI(page)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.route('**/*', async (route) => {
    if (route.request().isNavigationRequest()) {
      const response = await route.fetch()
      await route.fulfill({
        response,
        headers: { ...response.headers(), 'content-security-policy': policy },
      })
    } else {
      await route.fallback()
    }
  })
  await page.goto('/')
  await expect(page.getByText('Unverified / demo data')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible()
  await expect(page.getByRole('banner')).toBeVisible()
  expect(errors).toEqual([])
})
