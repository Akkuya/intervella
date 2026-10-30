import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { available, mockAPI, NOW } from './fixtures.ts'

const PASSCODE = 'synthetic-test-only-beta-passcode'
const CSRF = 'b'.repeat(64)
async function authMock(
  page: import('@playwright/test').Page,
  mode: 'beta' | 'university' = 'beta',
) {
  await mockAPI(page)
  const state = {
    signed: false,
    attempts: 0,
    logout: 0,
    renew: 0,
    expires: Date.parse(NOW) + 3600000,
    failRenew: false,
    mode,
  }
  await page.route('**/auth/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const now = await page.evaluate(() => Date.now())
    const body = () => route.request().postDataJSON()
    if (path === '/auth/beta') {
      state.attempts++
      if (body().passcode !== PASSCODE)
        return route.fulfill({
          status: 401,
          json: { error: { code: 'invalid_signin', message: 'private server detail' } },
        })
      state.signed = true
    } else if (path === '/auth/university/code') {
      expect(body().email).toBe('friend@university.test')
    } else if (path === '/auth/university/verify') {
      expect(body().code).toBe('123456')
      state.signed = true
    } else if (path === '/auth/logout') {
      expect(route.request().headers()['x-csrf-token']).toBe(CSRF)
      state.logout++
      state.signed = false
    } else if (path === '/auth/renew') {
      expect(route.request().headers()['x-csrf-token']).toBe(CSRF)
      state.renew++
      if (state.failRenew) {
        state.signed = false
        return route.fulfill({ status: 401, json: { error: { code: 'invalid_signin' } } })
      }
      state.expires = now + 3600000
    }
    return route.fulfill({
      json:
        path === '/auth/session' || path === '/auth/renew'
          ? {
              mode: state.mode,
              authenticated: state.signed && state.expires > now,
              csrf: CSRF,
              expires_at: new Date(state.expires).toISOString(),
              needs_renewal:
                state.mode === 'university' && state.signed && state.expires < now + 60000,
            }
          : { ok: true },
    })
  })
  return state
}
async function betaLogin(page: import('@playwright/test').Page) {
  await page.getByLabel('Beta passcode', { exact: true }).fill(PASSCODE)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
}

test('beta preserves intended navigation, refresh and local favourites; logout clears protected results', async ({
  page,
}) => {
  const state = await authMock(page)
  await page.addInitScript(() =>
    localStorage.setItem('utscvacant.favourites', JSON.stringify({ rooms: [1], buildings: [] })),
  )
  let requests = 0
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/')) requests++
  })
  await page.goto('/?room=1&schedule_date=2026-10-14&next=https%3A%2F%2Fevil.test')
  await expect(page.getByRole('heading', { name: 'Welcome to the private beta' })).toBeVisible()
  expect(requests).toBe(0)
  await betaLogin(page)
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeVisible()
  await expect(page).toHaveURL(/room=1/)
  await expect(page.getByRole('button', { name: 'Remove SYN-A-101', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByLabel('Beta passcode')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'SYN-A-101', exact: true })).toHaveCount(0)
  await expect.poll(() => state.logout).toBe(1)
  expect(
    await page.evaluate(() => JSON.parse(localStorage.getItem('utscvacant.favourites')!)),
  ).toEqual({ rooms: [1], buildings: [] })
  expect(page.url()).not.toContain(PASSCODE)
})

test('missing and incorrect passcodes are safe, with no timetable requests', async ({ page }) => {
  const state = await authMock(page)
  await page.goto('/')
  await expect(page.getByLabel('Beta passcode')).toBeVisible()
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  expect(state.attempts).toBe(0)
  await page.getByLabel('Beta passcode').fill('wrong')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Sign-in was not accepted')
  await expect(page.getByText('private server detail')).toHaveCount(0)
  await expect(page.getByLabel('Beta passcode')).toHaveValue('')
  await expect(page.getByRole('article')).toHaveCount(0)
})

test('API expiry clears cached availability immediately and leaves the current URL intact', async ({
  page,
}) => {
  const state = await authMock(page)
  await page.route('**/api/v1/room-search*', (route) =>
    state.signed
      ? route.fulfill({ json: available })
      : route.fulfill({ status: 401, json: { error: { code: 'authentication_required' } } }),
  )
  await page.goto('/?building=SYN-A')
  await betaLogin(page)
  await expect(page.getByRole('article')).toHaveCount(2)
  state.signed = false
  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(page.getByLabel('Beta passcode')).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(0)
  await expect(page).toHaveURL(/building=SYN-A/)
})

test('fixed session expiry hides results even without another timetable request', async ({
  page,
}) => {
  const state = await authMock(page)
  state.expires = Date.parse(NOW) + 10000
  await page.goto('/')
  await betaLogin(page)
  await expect(page.getByRole('article')).toHaveCount(2)
  await page.clock.fastForward(10001)
  await expect(page.getByLabel('Beta passcode')).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(0)
})

test('university email-code login and renewal use the shared session without beta fallback', async ({
  page,
}) => {
  const state = await authMock(page, 'university')
  state.expires = Date.parse(NOW) + 90000
  await page.goto('/')
  await page.getByLabel('University email').fill('friend@university.test')
  await page.getByRole('button', { name: 'Send email code' }).click()
  await page.getByLabel('Email code').fill('123456')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await page.clock.fastForward(61000)
  await expect.poll(() => state.renew).toBe(1)
  await expect(page.getByRole('article')).toHaveCount(2)
  state.failRenew = true
  state.expires = await page.evaluate(() => Date.now() + 1000)
  await page.clock.fastForward(30001)
  await expect(page.getByRole('heading', { name: 'University sign-in' })).toBeVisible()
  await expect(page.getByLabel('Beta passcode')).toHaveCount(0)
  await expect(page.getByRole('article')).toHaveCount(0)
})

for (const mode of ['beta', 'university'] as const)
  for (const theme of ['light', 'dark'] as const)
    for (const width of [360, 1440]) {
      test(`student login ${mode} ${theme} ${width}`, async ({ page }, info) => {
        await authMock(page, mode)
        await page.setViewportSize({ width, height: 900 })
        await page.emulateMedia({ colorScheme: theme })
        await page.goto('/')
        await expect(page.getByRole('form', { name: 'Student sign in' })).toBeVisible()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
          true,
        )
        expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([])
        await page.screenshot({
          path: info.outputPath(`login-${mode}-${theme}-${width}.png`),
          fullPage: true,
        })
      })
    }

test('malformed session metadata fails closed without exposing raw errors or fetching schedules', async ({
  page,
}) => {
  await authMock(page, 'university')
  let requests = 0
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/')) requests++
  })
  await page.route('**/auth/session', (route) =>
    route.fulfill({
      json: {
        mode: 'university',
        authenticated: true,
        needs_renewal: false,
        csrf: ['b'.repeat(64)],
        expires_at: '2099-01-01T00:00:00Z',
      },
    }),
  )
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('Invalid sign-in response')
  expect(requests).toBe(0)
  await expect(page.getByLabel('Beta passcode')).toHaveCount(0)
  await expect(page.getByRole('article')).toHaveCount(0)
})
