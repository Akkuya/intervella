// Mirrors the public Pydantic responses in backend/app/schemas.py. No database access.
export interface Freshness {
  dataset_id: string
  source_fetched_at: string
  freshness: 'fresh' | 'stale'
  generated_at: string
  warnings: string[]
}
export interface Room {
  room_id: number
  building_code: string
  room_number: string
  capacity: number | null
  active: boolean
}
export interface Building {
  id: number
  code: string
  name: string
}
export interface TimeWindow {
  start: string
  end: string
  timezone: 'America/Toronto'
}
export interface AvailabilityResponse {
  query: TimeWindow
  data: (Omit<Room, 'active'> & { status: 'schedule_available'; next_booking: string | null })[]
  meta: Freshness & {
    coverage: 'complete' | 'partial'
    unknown_room_count: number
    has_more: boolean
  }
}
export interface Coverage {
  completeness: 'complete' | 'partial' | 'unknown'
  starts_at: string | null
  ends_at: string | null
}
export interface ScheduleResponse {
  room: Room
  date: string
  query: TimeWindow
  data: Meeting[]
  meta: Freshness & { coverage: Coverage }
  calendar?: DayCalendar | null
}
export interface Meeting {
  id: number
  starts_at: string
  ends_at: string
  status: 'scheduled' | 'cancelled'
  public_label?: { text: string; authorization: 'approved_public' } | null
}
export interface CalendarPeriod {
  starts_at: string
  ends_at: string
  state: 'available' | 'scheduled' | 'unknown'
}
export interface CoverageWindow {
  starts_at: string
  ends_at: string
  completeness: Coverage['completeness']
}
export interface DayCalendar {
  window: TimeWindow
  coverage: CoverageWindow[]
  periods: CalendarPeriod[]
}
export interface CalendarRoom {
  room: Room
  meetings: Meeting[]
  calendar: DayCalendar
}
export interface BuildingScheduleResponse {
  building: Building
  date: string
  query: TimeWindow
  display_window: TimeWindow
  data: CalendarRoom[]
  meta: Freshness & { unknown_room_count: number }
}
export interface StatusResponse extends Freshness {
  age_seconds: number
  period: { start: string; end: string } | null
  timezone: 'America/Toronto'
  degraded: boolean
  usable: boolean
  unknown_room_count: number
}

const messages: Record<string, string> = {
  unsupported_window: 'Choose a start time between five minutes ago and 30 days ahead.',
  outside_dataset_coverage:
    'That time is outside the published schedule. Check the source period or choose another date.',
  coverage_unavailable:
    'Coverage is incomplete or unknown for this search. No room availability can be confirmed.',
  dataset_unavailable:
    'No published schedule is available yet. Try again after a schedule is published.',
  database_unavailable: 'The schedule service is unavailable. Try again later.',
  invalid_building: 'Choose a recognized building, or search all buildings.',
  invalid_request: 'Check your search date, time, duration, and building.',
  room_not_found: 'This room could not be found. Return to the room search.',
  request_timeout: 'The schedule request timed out. Try again.',
  connection_error: 'Could not reach the schedule service. Check your connection and try again.',
  invalid_response: 'The schedule service returned an unexpected response. Try again later.',
  building_not_found: 'This building could not be found. Choose an active building.',
  schedule_too_large:
    'This calendar exceeds the safe display limit. Choose a smaller building or another date.',
}

export class ApiError extends Error {
  code: string
  requestId?: string
  constructor(code: string, requestId?: string) {
    super(
      Object.hasOwn(messages, code)
        ? messages[code]
        : 'The schedule request failed. Try again later.',
    )
    this.name = 'ApiError'
    this.code = code
    this.requestId = requestId
  }
}

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null
const text = (value: unknown) => typeof value === 'string'
const integer = (value: unknown) =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
const instant = (value: unknown) =>
  text(value) &&
  /(?:Z|[+-]\d{2}:\d{2})$/i.test(value as string) &&
  Number.isFinite(Date.parse(value as string))
const nullableInstant = (value: unknown) => value === null || instant(value)
const windowShape = (value: unknown) =>
  record(value) &&
  instant(value.start) &&
  instant(value.end) &&
  value.timezone === 'America/Toronto'
const roomShape = (value: unknown) =>
  record(value) &&
  integer(value.room_id) &&
  value.room_id !== 0 &&
  text(value.building_code) &&
  text(value.room_number) &&
  (value.capacity === null || (integer(value.capacity) && value.capacity !== 0))
const freshnessShape = (value: unknown) =>
  record(value) &&
  text(value.dataset_id) &&
  instant(value.source_fetched_at) &&
  instant(value.generated_at) &&
  ['fresh', 'stale'].includes(value.freshness as string) &&
  Array.isArray(value.warnings) &&
  value.warnings.every(text)
const buildingsShape = (value: unknown) =>
  record(value) &&
  Array.isArray(value.data) &&
  value.data.every(
    (item: unknown) => record(item) && integer(item.id) && text(item.code) && text(item.name),
  )
const roomResponseShape = (value: unknown) =>
  record(value) &&
  roomShape(value.data) &&
  record(value.data) &&
  typeof value.data.active === 'boolean'
const meetingShape = (item: unknown) =>
  record(item) &&
  integer(item.id) &&
  instant(item.starts_at) &&
  instant(item.ends_at) &&
  Date.parse(item.ends_at as string) > Date.parse(item.starts_at as string) &&
  ['scheduled', 'cancelled'].includes(item.status as string) &&
  (item.public_label === undefined ||
    item.public_label === null ||
    (record(item.public_label) &&
      item.public_label.authorization === 'approved_public' &&
      text(item.public_label.text) &&
      (item.public_label.text as string).trim().length > 0 &&
      (item.public_label.text as string).length <= 120))
const calendarShape = (value: unknown) =>
  record(value) &&
  windowShape(value.window) &&
  Array.isArray(value.coverage) &&
  value.coverage.every(
    (item: unknown) =>
      record(item) &&
      instant(item.starts_at) &&
      instant(item.ends_at) &&
      ['complete', 'partial', 'unknown'].includes(item.completeness as string),
  ) &&
  Array.isArray(value.periods) &&
  value.periods.length > 0 &&
  value.periods.every(
    (item: unknown) =>
      record(item) &&
      instant(item.starts_at) &&
      instant(item.ends_at) &&
      ['available', 'scheduled', 'unknown'].includes(item.state as string),
  )
const buildingScheduleShape = (value: unknown) =>
  record(value) &&
  record(value.building) &&
  integer(value.building.id) &&
  text(value.building.code) &&
  text(value.building.name) &&
  text(value.date) &&
  windowShape(value.query) &&
  windowShape(value.display_window) &&
  freshnessShape(value.meta) &&
  record(value.meta) &&
  integer(value.meta.unknown_room_count) &&
  Array.isArray(value.data) &&
  value.data.length <= 100 &&
  value.data.every(
    (item: unknown) =>
      record(item) &&
      roomResponseShape({ data: item.room }) &&
      Array.isArray(item.meetings) &&
      item.meetings.every(meetingShape) &&
      calendarShape(item.calendar),
  )
const availabilityShape = (value: unknown) =>
  record(value) &&
  windowShape(value.query) &&
  record(value.meta) &&
  freshnessShape(value.meta) &&
  integer(value.meta.unknown_room_count) &&
  ['complete', 'partial'].includes(value.meta.coverage as string) &&
  typeof value.meta.has_more === 'boolean' &&
  Array.isArray(value.data) &&
  value.data.every(
    (item: unknown) =>
      roomShape(item) &&
      record(item) &&
      item.status === 'schedule_available' &&
      nullableInstant(item.next_booking),
  )
const scheduleShape = (value: unknown) =>
  record(value) &&
  roomShape(value.room) &&
  record(value.room) &&
  typeof value.room.active === 'boolean' &&
  text(value.date) &&
  windowShape(value.query) &&
  record(value.meta) &&
  freshnessShape(value.meta) &&
  record(value.meta.coverage) &&
  ['complete', 'partial', 'unknown'].includes(value.meta.coverage.completeness as string) &&
  nullableInstant(value.meta.coverage.starts_at) &&
  nullableInstant(value.meta.coverage.ends_at) &&
  Array.isArray(value.data) &&
  value.data.every(meetingShape) &&
  (value.calendar === undefined || value.calendar === null || calendarShape(value.calendar))
const statusShape = (value: unknown) =>
  record(value) &&
  freshnessShape(value) &&
  typeof value.age_seconds === 'number' &&
  Number.isFinite(value.age_seconds) &&
  value.age_seconds >= 0 &&
  value.timezone === 'America/Toronto' &&
  typeof value.usable === 'boolean' &&
  typeof value.degraded === 'boolean' &&
  integer(value.unknown_room_count) &&
  (value.period === null ||
    (record(value.period) && instant(value.period.start) && instant(value.period.end)))

async function get<T>(
  path: string,
  signal: AbortSignal | undefined,
  isValid: (value: unknown) => boolean,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/v1/${path}`, { signal, credentials: 'omit', cache: 'no-cache' })
  } catch (cause) {
    if (signal?.aborted || (cause instanceof DOMException && cause.name === 'AbortError'))
      throw cause
    throw new ApiError('connection_error')
  }
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiError('invalid_response')
  }
  if (!response.ok) {
    const error =
      typeof body === 'object' && body !== null && 'error' in body ? body.error : undefined
    const code =
      typeof error === 'object' &&
      error !== null &&
      'code' in error &&
      typeof error.code === 'string'
        ? error.code
        : 'request_failed'
    const id = response.headers.get('x-request-id')
    throw new ApiError(code, id && /^[a-zA-Z0-9-]{1,80}$/.test(id) ? id : undefined)
  }
  if (!isValid(body)) throw new ApiError('invalid_response')
  return body as T
}

export const api = {
  buildingSchedule: (code: string, date: string, signal?: AbortSignal) =>
    get<BuildingScheduleResponse>(
      `buildings/${encodeURIComponent(code)}/schedule?${new URLSearchParams({ date })}`,
      signal,
      (value) =>
        buildingScheduleShape(value) &&
        record(value) &&
        record(value.building) &&
        value.building.code === code &&
        value.date === date &&
        Array.isArray(value.data) &&
        value.data.every(
          (item: unknown) => record(item) && record(item.room) && item.room.building_code === code,
        ),
    ),
  buildings: (signal?: AbortSignal) =>
    get<{ data: Building[] }>('buildings', signal, buildingsShape),
  status: (signal?: AbortSignal) => get<StatusResponse>('status', signal, statusShape),
  room: (id: number, signal?: AbortSignal) =>
    get<{ data: Room }>(
      `rooms/${id}`,
      signal,
      (value) =>
        roomResponseShape(value) &&
        record(value) &&
        record(value.data) &&
        value.data.room_id === id,
    ),
  schedule: (id: number, date: string, signal?: AbortSignal) =>
    get<ScheduleResponse>(
      `rooms/${id}/schedule?${new URLSearchParams({ date })}`,
      signal,
      (value) =>
        scheduleShape(value) &&
        record(value) &&
        record(value.room) &&
        value.room.room_id === id &&
        value.date === date,
    ),
  availability: (
    query: { start: string; duration_minutes: number; building?: string },
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams({
      start: query.start,
      duration_minutes: String(query.duration_minutes),
    })
    if (query.building) params.set('building', query.building)
    return get<AvailabilityResponse>(`availability?${params}`, signal, availabilityShape)
  },
}
