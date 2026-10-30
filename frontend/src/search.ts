import { campusDate, campusTime, toInstant, validDate } from './time.ts'

export interface SearchInput {
  mode: 'now' | 'custom'
  date: string
  time: string
  offset: string
  duration: number
  building: string
  endDate?: string
  endTime?: string
  endOffset?: string
  roomName?: string
  sort?: 'building' | 'room' | 'duration'
  includeNext?: boolean
}

export class SearchSessionEnded extends Error {
  readonly end: string
  readonly state: 'ending' | 'expired'

  constructor(end: string, remaining: number) {
    super(
      remaining <= 0
        ? 'This session has expired. Choose a new end time or duration.'
        : 'Fewer than five minutes remain. Choose a later end time or a duration.',
    )
    this.name = 'SearchSessionEnded'
    this.end = end
    this.state = remaining <= 0 ? 'expired' : 'ending'
  }
}

export function readLocation(query: string, now = new Date()) {
  const params = new URLSearchParams(query)
  const view = params.get('view') ?? 'find'
  const rawDuration = params.get('duration') ?? '60'
  const duration = Number(rawDuration)
  const mode = params.get('mode') === 'custom' ? 'custom' : 'now'
  const search: SearchInput = {
    mode,
    date: mode === 'custom' ? (params.get('date') ?? campusDate(now)) : campusDate(now),
    time: mode === 'custom' ? (params.get('time') ?? campusTime(now)) : campusTime(now),
    offset: mode === 'custom' ? (params.get('offset') ?? '') : '',
    duration: Number.isInteger(duration) && duration >= 5 && duration <= 240 ? duration : 60,
    building: params.get('building') ?? '',
    endDate: params.get('end_date') ?? undefined,
    endTime: params.get('end_time') ?? undefined,
    endOffset: params.get('end_offset') ?? undefined,
    roomName: params.get('room_name') ?? undefined,
    sort: (params.get('sort') ?? 'building') as SearchInput['sort'],
    includeNext: params.get('include_next') === '1',
  }
  const room = params.get('room')
  const roomId =
    room && /^\d+$/.test(room) && Number.isSafeInteger(Number(room)) && Number(room) > 0
      ? Number(room)
      : undefined
  const scheduleDate = params.get('schedule_date') ?? search.date
  let error: string | undefined
  let session: SearchSessionEnded | undefined
  let sessionEnd: string | undefined
  if (!['find', 'buildings', 'saved'].includes(view))
    error = 'This page link is invalid. Return to the room search.'
  else if (room !== null && roomId === undefined)
    error = 'This room link is invalid. Return to the room search.'
  else if (!validDate(scheduleDate)) error = 'Choose a valid schedule date.'
  if (!error && roomId === undefined && view !== 'buildings') {
    if (params.has('mode') && !['now', 'custom'].includes(params.get('mode')!))
      error = 'Saved search mode is invalid. Choose a new search.'
    else if (!/^\d+$/.test(rawDuration) || duration !== search.duration)
      error = 'Choose a duration between 5 and 240 minutes.'
    else if (!['building', 'room', 'duration'].includes(search.sort!))
      error = 'Choose a valid sort order.'
    else if (params.has('include_next') && !['0', '1'].includes(params.get('include_next')!))
      error = 'Choose a valid next-opening option.'
    else if (search.mode === 'custom' && (!params.has('date') || !params.has('time')))
      error = 'The saved search needs a date and time.'
    if (!error) {
      try {
        const request = requestParams(search, now)
        if (search.mode === 'now') sessionEnd = request.end
      } catch (cause) {
        if (cause instanceof SearchSessionEnded) {
          session = cause
          sessionEnd = cause.end
        } else error = (cause as Error).message
      }
    }
  }
  return { search, roomId, scheduleDate, error, view, session, sessionEnd }
}

export function searchParams(search: SearchInput): URLSearchParams {
  const params = new URLSearchParams({ mode: search.mode, duration: String(search.duration) })
  if (search.mode === 'custom') {
    params.set('date', search.date)
    params.set('time', search.time)
    if (search.offset) params.set('offset', search.offset)
  }
  if (search.building) params.set('building', search.building)
  if (search.endDate !== undefined || search.endTime !== undefined) {
    params.set('end_date', search.endDate ?? '')
    params.set('end_time', search.endTime ?? '')
    if (search.endOffset) params.set('end_offset', search.endOffset)
  }
  if (search.roomName) params.set('room_name', search.roomName.trim())
  if (search.sort && search.sort !== 'building') params.set('sort', search.sort)
  if (search.includeNext) params.set('include_next', '1')
  return params
}

export function requestParams(search: SearchInput, now = new Date()) {
  if (!Number.isInteger(search.duration) || search.duration < 5 || search.duration > 240) {
    throw new Error('Choose a duration between 5 and 240 minutes.')
  }
  const start =
    search.mode === 'now' ? now.toISOString() : toInstant(search.date, search.time, search.offset)
  const until = search.endDate !== undefined || search.endTime !== undefined
  const end = until
    ? toInstant(search.endDate ?? '', search.endTime ?? '', search.endOffset)
    : undefined
  if (end && search.mode === 'now' && Date.parse(end) - Date.parse(start) < 5 * 60_000)
    throw new SearchSessionEnded(end, Date.parse(end) - Date.parse(start))
  if (
    end &&
    (Date.parse(end) - Date.parse(start) < 5 * 60_000 ||
      Date.parse(end) - Date.parse(start) > 240 * 60_000)
  )
    throw new Error('Choose an end time 5 to 240 minutes after the start.')
  if (!['building', 'room', 'duration'].includes(search.sort ?? 'building'))
    throw new Error('Choose a valid sort order.')
  if (search.roomName && (search.roomName.length > 64 || !/[a-z0-9]/i.test(search.roomName)))
    throw new Error('Enter a room identifier, such as AA-112.')
  return {
    start,
    end,
    duration_minutes: until ? undefined : search.duration,
    building: search.building || undefined,
    room_name: search.roomName?.trim() || undefined,
    sort: search.sort ?? 'building',
    include_next: search.includeNext ?? false,
  }
}
