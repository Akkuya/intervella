import type { Page } from '@playwright/test'
import type { RoomSearchResponse, ScheduleResponse, StatusResponse } from '../../src/api.ts'
import { toInstant } from '../../src/time.ts'
import { shiftDay } from '../../src/calendar-layout.ts'

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
export const available: RoomSearchResponse = {
  query: { start: NOW, end: '2026-10-14T13:00:00Z', timezone: 'America/Toronto' },
  data: [
    {
      room_id: 1,
      building_code: 'SYN-A',
      room_number: '101',
      capacity: 24,
      state: 'available',
      active: true,
      available_until: '2026-10-14T13:00:00Z',
      next_available_start: NOW,
      next_booking: '2026-10-14T13:00:00Z',
    },
    {
      room_id: 2,
      building_code: 'SYN-B',
      room_number: '205',
      capacity: null,
      state: 'available',
      active: true,
      available_until: '2026-10-15T02:00:00Z',
      next_available_start: NOW,
      next_booking: null,
    },
  ],
  meta: {
    ...meta,
    coverage: 'partial',
    unknown_room_count: 3,
    has_more: false,
    missing_room_ids: [],
    lookahead_end: '2026-10-15T12:00:00Z',
  },
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
  calendar: {
    window: {
      start: '2026-10-14T12:00:00Z',
      end: '2026-10-15T02:00:00Z',
      timezone: 'America/Toronto',
    },
    coverage: [
      {
        starts_at: '2026-10-14T12:00:00Z',
        ends_at: '2026-10-15T02:00:00Z',
        completeness: 'complete',
      },
    ],
    periods: [
      { starts_at: '2026-10-14T12:00:00Z', ends_at: '2026-10-14T13:00:00Z', state: 'available' },
      { starts_at: '2026-10-14T13:00:00Z', ends_at: '2026-10-14T14:00:00Z', state: 'scheduled' },
      { starts_at: '2026-10-14T14:00:00Z', ends_at: '2026-10-15T02:00:00Z', state: 'available' },
    ],
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

function scheduleOn(date: string): ScheduleResponse {
  const at = (time: string) => toInstant(date, time)
  return {
    ...schedule,
    date,
    query: { ...schedule.query, start: at('00:00'), end: toInstant(shiftDay(date, 1), '00:00') },
    data: [
      { ...schedule.data[0], starts_at: at('09:00'), ends_at: at('10:00') },
      { ...schedule.data[1], starts_at: at('11:00'), ends_at: at('12:00') },
    ],
    calendar: {
      window: { ...schedule.query, start: at('08:00'), end: at('22:00') },
      coverage: [{ starts_at: at('08:00'), ends_at: at('22:00'), completeness: 'complete' }],
      periods: [
        { starts_at: at('08:00'), ends_at: at('09:00'), state: 'available' },
        { starts_at: at('09:00'), ends_at: at('10:00'), state: 'scheduled' },
        { starts_at: at('10:00'), ends_at: at('22:00'), state: 'available' },
      ],
    },
  }
}

export async function mockAPI(page: Page) {
  await page.clock.install({ time: new Date(NOW) })
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const daySchedule = scheduleOn(
      new URL(route.request().url()).searchParams.get('date') ?? '2026-10-14',
    )
    const code = decodeURIComponent(path.split('/')[4] ?? '')
    const buildingRoom = {
      ...room,
      building_code: code,
      room_id: code === 'SYN-A' ? 1 : 2,
      room_number: code === 'SYN-A' ? '101' : '205',
    }
    const body = path.endsWith('/buildings')
      ? buildings
      : path.endsWith('/status')
        ? status
        : path.endsWith('/room-search')
          ? {
              ...available,
              data: available.data.filter((item) => {
                const params = new URL(route.request().url()).searchParams
                const ids = params.getAll('room_ids')
                const name = (params.get('room_name') ?? '')
                  .replace(/[^a-z0-9]/gi, '')
                  .toUpperCase()
                return (
                  (!ids.length || ids.includes(String(item.room_id))) &&
                  (!params.get('building') || params.get('building') === item.building_code) &&
                  `${item.building_code}${item.room_number}`
                    .replace(/[^a-z0-9]/gi, '')
                    .toUpperCase()
                    .includes(name)
                )
              }),
            }
          : path.startsWith('/api/v1/buildings/')
            ? {
                building:
                  buildings.data.find(
                    (building) => building.code === decodeURIComponent(path.split('/')[4]),
                  ) ?? buildings.data[0],
                date: new URL(route.request().url()).searchParams.get('date'),
                query: daySchedule.query,
                display_window: daySchedule.calendar!.window,
                data: [
                  {
                    room: buildingRoom,
                    meetings: daySchedule.data,
                    calendar: daySchedule.calendar,
                  },
                  {
                    room: {
                      ...buildingRoom,
                      room_id: code === 'SYN-A' ? 3 : 4,
                      room_number: code === 'SYN-A' ? '102' : '206',
                      capacity: null,
                    },
                    meetings: [],
                    calendar: {
                      window: daySchedule.calendar!.window,
                      coverage: [],
                      periods: [
                        {
                          starts_at: daySchedule.calendar!.window.start,
                          ends_at: daySchedule.calendar!.window.end,
                          state: 'unknown',
                        },
                      ],
                    },
                  },
                ],
                meta: { ...meta, unknown_room_count: 1 },
              }
            : path.endsWith('/schedule')
              ? daySchedule
              : { data: room }
    await route.fulfill({ json: body })
  })
}
