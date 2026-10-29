import assert from 'node:assert/strict'
import test from 'node:test'
import { api, ApiError } from '../../src/api.ts'
import { room, schedule, available } from '../e2e/fixtures.ts'

test('client uses same-origin API, encoded parameters, cancellation and no credentials', async (t) => {
  const signal = new AbortController().signal
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(new URL(url, 'https://example.test').pathname, '/api/v1/availability')
    assert.equal(new URL(url, 'https://example.test').searchParams.get('building'), 'A&other=value')
    assert.equal(options.signal, signal)
    assert.equal(options.credentials, 'omit')
    assert.equal(options.cache, 'no-cache')
    return new Response(JSON.stringify({ error: { code: 'invalid_building' } }), { status: 422 })
  })
  await assert.rejects(
    api.availability(
      { start: '2026-10-14T12:00:00Z', duration_minutes: 60, building: 'A&other=value' },
      signal,
    ),
    { code: 'invalid_building' },
  )
})

test('API errors never display raw backend message or unsafe request ID', async (t) => {
  t.mock.method(
    globalThis,
    'fetch',
    async () =>
      new Response(
        JSON.stringify({ error: { code: 'database_unavailable', message: 'password=secret' } }),
        { status: 503, headers: { 'x-request-id': '<unsafe>' } },
      ),
  )
  await assert.rejects(
    api.status(),
    (error: unknown) =>
      error instanceof ApiError &&
      !error.message.includes('secret') &&
      error.requestId === undefined,
  )
})

test('malformed success payloads produce controlled errors instead of broken UI', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('{}'))
  for (const call of [
    () => api.buildings(),
    () => api.roomSearch({ start: '2026-10-14T12:00:00Z' }),
    () => api.buildingSchedule('SYN-A', '2026-10-14'),
    () => api.status(),
    () => api.room(1),
    () => api.schedule(1, '2026-10-14'),
    () => api.availability({ start: '2026-10-14T12:00:00Z', duration_minutes: 60 }),
  ]) {
    await assert.rejects(call(), { code: 'invalid_response' })
  }
})

test('aborted requests remain cancelled rather than becoming connection failures', async (t) => {
  const controller = new AbortController()
  controller.abort()
  t.mock.method(globalThis, 'fetch', async () => {
    throw new DOMException('Aborted', 'AbortError')
  })
  await assert.rejects(api.status(controller.signal), { name: 'AbortError' })
})

test('unreachable service has controlled connection error', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => {
    throw new TypeError('private network details')
  })
  await assert.rejects(
    api.status(),
    (error: unknown) =>
      error instanceof ApiError &&
      error.code === 'connection_error' &&
      !error.message.includes('private'),
  )
})

test('room endpoints reject payloads for a different room or date', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ data: room })))
  await assert.rejects(api.room(999), { code: 'invalid_response' })
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify(schedule)))
  await assert.rejects(api.schedule(999, '2026-10-14'), { code: 'invalid_response' })
  await assert.rejects(api.schedule(1, '2026-10-15'), { code: 'invalid_response' })
})

test('room search encodes batches and rejects mismatched identities or unproven free bounds', async (t) => {
  let response = available
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.deepEqual(new URL(url, 'https://example.test').searchParams.getAll('room_ids'), [
      '1',
      '2',
    ])
    assert.equal(options.credentials, 'omit')
    return new Response(JSON.stringify(response))
  })
  await api.roomSearch({ start: available.query.start, room_ids: [1, 2] })
  response = { ...available, data: [{ ...available.data[0], room_id: 999 }] }
  await assert.rejects(api.roomSearch({ start: available.query.start, room_ids: [1, 2] }), {
    code: 'invalid_response',
  })
  response = { ...available, data: [{ ...available.data[0], available_until: null }] }
  await assert.rejects(api.roomSearch({ start: available.query.start, room_ids: [1, 2] }), {
    code: 'invalid_response',
  })
})
