export const CAMPUS_ZONE = 'America/Toronto'
const partsFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: CAMPUS_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

function parts(value: string | Date) {
  const fields = Object.fromEntries(
    partsFormatter
      .formatToParts(new Date(value))
      .filter((part) => part.type !== 'literal')
      .map((part) => [part.type, part.value]),
  )
  return {
    date: `${fields.year}-${fields.month}-${fields.day}`,
    time: `${fields.hour}:${fields.minute}`,
  }
}

export const campusDate = (value: string | Date) => parts(value).date
export const campusTime = (value: string | Date) => parts(value).time
export const dateLabel = (value: string | Date) =>
  new Intl.DateTimeFormat('en-CA', {
    timeZone: CAMPUS_ZONE,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(value))

export function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(`${value}T12:00:00Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}

export interface LocalCandidate {
  instant: string
  offset: string
}

export function localCandidates(date: string, time: string): LocalCandidate[] {
  if (!validDate(date) || !/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) {
    throw new Error('Enter a valid date and time in Toronto time.')
  }
  const wall = Date.parse(`${date}T${time}:00Z`)
  const offsets = new Set<number>()
  for (const hours of [-24, 0, 24]) {
    const probe = new Date(wall + hours * 3_600_000)
    const local = parts(probe)
    offsets.add(Date.parse(`${local.date}T${local.time}:00Z`) - probe.getTime())
  }
  return [...offsets]
    .map((offset) => ({ instant: new Date(wall - offset).toISOString(), offset }))
    .filter(
      (candidate) =>
        campusDate(candidate.instant) === date && campusTime(candidate.instant) === time,
    )
    .sort((a, b) => a.instant.localeCompare(b.instant))
    .map(({ instant, offset }) => {
      const minutes = Math.abs(offset / 60_000)
      return {
        instant,
        offset: `${offset < 0 ? '-' : '+'}${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`,
      }
    })
}

export function toInstant(date: string, time: string, offset = ''): string {
  const candidates = localCandidates(date, time)
  if (!candidates.length)
    throw new Error(
      'This time does not exist in Toronto because the clocks move forward. Choose another time.',
    )
  if (candidates.length > 1 && !offset)
    throw new Error('This time occurs twice. Choose the first or second occurrence.')
  const selected = offset
    ? candidates.find((candidate) => candidate.offset === offset)
    : candidates[0]
  if (!selected)
    throw new Error('The saved offset does not match Toronto time. Choose the time again.')
  return selected.instant
}

export function nextBookingLabel(value: string, searchStart: string) {
  return `${campusDate(value) !== campusDate(searchStart) ? `${dateLabel(value)} · ` : ''}${campusTime(value)}`
}
