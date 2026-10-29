import type { Meeting, TimeWindow } from './api.ts'
import { validDate } from './time.ts'

export function positionRange(start: string, end: string, window: TimeWindow) {
  const left = Math.max(Date.parse(start), Date.parse(window.start))
  const right = Math.min(Date.parse(end), Date.parse(window.end))
  const length = Date.parse(window.end) - Date.parse(window.start)
  if (!Number.isFinite(left + right + length) || left >= right || length <= 0) return null
  return {
    left: ((left - Date.parse(window.start)) / length) * 100,
    width: ((right - left) / length) * 100,
  }
}

// Lanes only position already-authoritative event intervals; they do not infer free time.
export function layoutEvents(meetings: Meeting[], window: TimeWindow) {
  const lanes: number[] = []
  return [...meetings]
    .sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at) || a.id - b.id)
    .flatMap((meeting) => {
      const position = positionRange(meeting.starts_at, meeting.ends_at, window)
      if (!position) return []
      let lane = lanes.findIndex((end) => end <= Date.parse(meeting.starts_at))
      if (lane < 0) lane = lanes.length
      lanes[lane] = Date.parse(meeting.ends_at)
      return [{ meeting, position, lane }]
    })
}

export function shiftDay(day: string, amount: number) {
  const date = new Date(`${day}T12:00:00Z`)
  date.setUTCDate(date.getUTCDate() + amount)
  const next = Number.isFinite(date.getTime()) ? date.toISOString().slice(0, 10) : ''
  if (!validDate(next)) throw new Error('No adjacent supported date.')
  return next
}

export const eventLabel = (meeting: Meeting) =>
  meeting.public_label?.authorization === 'approved_public'
    ? meeting.public_label.text
    : meeting.status === 'cancelled'
      ? 'Cancelled event'
      : 'Scheduled event'
