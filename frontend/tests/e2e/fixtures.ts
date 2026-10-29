import type { Page } from '@playwright/test'
import type { AvailabilityResponse, ScheduleResponse, StatusResponse } from '../../src/api.ts'

export const NOW = '2026-10-14T12:00:00Z'
export const meta = {
  dataset_id: '00000000-0000-0000-0000-000000000202',
  source_fetched_at: '2026-10-14T09:00:00Z',
  freshness: 'fresh' as const,
  generated_at: NOW,
  warnings: [],
}
export const buildings = {
  data: [
    { id: 1, code: 'SYN-A', name: 'Synthetic Building A' },
    { id: 2, code: 'SYN-B', name: 'Synthetic Building B' },
  ],
}
export const available: AvailabilityResponse = {
  query: { start: NOW, end: '2026-10-14T13:00:00Z', timezone: 'America/Toronto' },
  data: [
    {
      room_id: 1,
      building_code: 'SYN-A',
      room_number: '101',
      capacity: 24,
      status: 'schedule_available',
      next_booking: '2026-10-14T13:00:00Z',
    },
    {
      room_id: 2,
      building_code: 'SYN-B',
      room_number: '205',
      capacity: null,
      status: 'schedule_available',
      next_booking: null,
    },
  ],
  meta: { ...meta, coverage: 'partial', unknown_room_count: 3, has_more: false },
}
export const room = {
  room_id: 1,
  building_code: 'SYN-A',
  room_number: '101',
  capacity: 24,
  active: true,
}
export const schedule: ScheduleResponse = {
  room,
  date: '2026-10-14',
  query: {
    start: '2026-10-14T04:00:00Z',
    end: '2026-10-15T04:00:00Z',
    timezone: 'America/Toronto',
  },
  data: [
    {
      id: 1,
      starts_at: '2026-10-14T13:00:00Z',
      ends_at: '2026-10-14T14:00:00Z',
      status: 'scheduled',
    },
    {
      id: 2,
      starts_at: '2026-10-14T15:00:00Z',
      ends_at: '2026-10-14T16:00:00Z',
      status: 'cancelled',
    },
  ],
  meta: {
    ...meta,
    coverage: {
      completeness: 'complete',
      starts_at: '2026-10-14T04:00:00Z',
      ends_at: '2026-10-15T04:00:00Z',
    },
  },
}
export const status: StatusResponse = {
  ...meta,
  age_seconds: 10800,
  period: { start: '2026-10-14T04:00:00Z', end: '2026-10-15T04:00:00Z' },
  timezone: 'America/Toronto',
  degraded: true,
  usable: true,
  unknown_room_count: 3,
}

export async function mockAPI(page: Page) {
  await page.clock.install({ time: new Date(NOW) })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path.endsWith('/buildings')
      ? buildings
      : path.endsWith('/status')
        ? status
        : path.endsWith('/availability')
          ? available
          : path.endsWith('/schedule')
            ? schedule
            : { data: room }
    await route.fulfill({ json: body })
  })
}
