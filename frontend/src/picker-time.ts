import { campusDate, campusTime, localCandidates } from './time.ts'

export function endSuggestions(start?: string) {
  if (!start) return []
  return [30, 60, 120].map((minutes) => {
    const target = Date.parse(start) + minutes * 60_000
    const instant = new Date(Math.ceil(target / 300_000) * 300_000).toISOString()
    const date = campusDate(instant),
      time = campusTime(instant)
    const offset = localCandidates(date, time).find(
      (item) => Date.parse(item.instant) === Date.parse(instant),
    )!.offset
    return {
      label: `${Date.parse(instant) === target ? '+' : '~'}${minutes === 30 ? '30 min' : minutes === 60 ? '1 hr' : '2 hr'}`,
      date,
      time,
      offset,
    }
  })
}

export function parseTimeText(text: string): string {
  const match = text.trim().match(/^(\d{1,2})(?::?(\d{2}))?\s*(am|pm)?$/i)
  if (!match) throw new Error('Enter a time such as 2:30 PM, 14:30 or 1430.')
  let hour = Number(match[1])
  const minute = Number(match[2] ?? 0)
  if (match[3]) {
    if (hour < 1 || hour > 12) throw new Error('Use hours 1–12 with AM/PM.')
    hour = (hour % 12) + (match[3].toLowerCase() === 'pm' ? 12 : 0)
  }
  if (hour > 23 || minute > 59 || minute % 5)
    throw new Error(
      'Choose a five-minute increment (00, 05, …, 55). Times are never silently rounded.',
    )
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}
export function nearestFive(time?: string) {
  if (time === undefined) return campusTime(new Date(Math.round(Date.now() / 300_000) * 300_000))
  const [h, m] = time.split(':').map(Number)
  const minutes = (Math.round((h * 60 + m) / 5) * 5) % 1440
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}
export function timeText(time: string) {
  if (!/^\d{2}:\d{2}$/.test(time)) return time || 'Choose a time'
  const [h, m] = time.split(':').map(Number)
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h >= 12 ? 'PM' : 'AM'}`
}
export function allowedTime(date: string, time: string, start?: string) {
  try {
    return localCandidates(date, time).some(
      (candidate) =>
        !start ||
        (Date.parse(candidate.instant) - Date.parse(start) >= 300_000 &&
          Date.parse(candidate.instant) - Date.parse(start) <= 14_400_000),
    )
  } catch {
    return false
  }
}
