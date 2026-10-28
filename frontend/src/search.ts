import { campusDate, campusTime, toInstant, validDate } from './time.ts'

export interface SearchInput {
  mode: 'now' | 'custom'
  date: string
  time: string
  offset: string
  duration: number
  building: string
}

export function readLocation(query: string, now = new Date()) {
  const params = new URLSearchParams(query)
  const rawDuration = params.get('duration') ?? '60'
  const duration = Number(rawDuration)
  const search: SearchInput = {
    mode: params.get('mode') === 'custom' ? 'custom' : 'now',
    date: params.get('date') ?? campusDate(now),
    time: params.get('time') ?? campusTime(now),
    offset: params.get('offset') ?? '',
    duration: Number.isInteger(duration) && duration >= 5 && duration <= 240 ? duration : 60,
    building: params.get('building') ?? '',
  }
  const room = params.get('room')
  const roomId =
    room && /^\d+$/.test(room) && Number.isSafeInteger(Number(room)) && Number(room) > 0
      ? Number(room)
      : undefined
  const scheduleDate = params.get('schedule_date') ?? search.date
  let error: string | undefined
  if (params.has('mode') && !['now', 'custom'].includes(params.get('mode')!))
    error = 'Saved search mode is invalid. Choose a new search.'
  else if (!/^\d+$/.test(rawDuration) || duration !== search.duration)
    error = 'Choose a duration between 5 and 240 minutes.'
  else if (room !== null && roomId === undefined)
    error = 'This room link is invalid. Return to the room search.'
  else if (!validDate(scheduleDate)) error = 'Choose a valid schedule date.'
  else if (search.mode === 'custom') {
    if (!params.has('date') || !params.has('time'))
      error = 'The saved search needs a date and time.'
    else
      try {
        toInstant(search.date, search.time, search.offset)
      } catch (cause) {
        error = (cause as Error).message
      }
  }
  return { search, roomId, scheduleDate, error }
}

export function searchParams(search: SearchInput): URLSearchParams {
  const params = new URLSearchParams({ mode: search.mode, duration: String(search.duration) })
  if (search.mode === 'custom') {
    params.set('date', search.date)
    params.set('time', search.time)
    if (search.offset) params.set('offset', search.offset)
  }
  if (search.building) params.set('building', search.building)
  return params
}

export function requestParams(search: SearchInput, now = new Date()) {
  if (!Number.isInteger(search.duration) || search.duration < 5 || search.duration > 240) {
    throw new Error('Choose a duration between 5 and 240 minutes.')
  }
  return {
    start:
      search.mode === 'now'
        ? now.toISOString()
        : toInstant(search.date, search.time, search.offset),
    duration_minutes: search.duration,
    building: search.building || undefined,
  }
}
