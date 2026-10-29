import { useEffect, useRef, useState } from 'react'
import type { CalendarRoom, Meeting, TimeWindow } from './api.ts'
import { roomLabel } from './rooms.ts'
import { navigate, routeClick } from './navigation.ts'
import { campusDate, campusTimeLabel, dateLabel, nextBookingLabel, validDate } from './time.ts'
import { eventLabel, layoutEvents, positionRange, shiftDay } from './calendar-layout.ts'
import { Badge, Button } from './ui.tsx'
import './calendar.css'

export function CalendarDate({
  date,
  query,
  onRefresh,
}: {
  date: string
  query: string
  onRefresh: () => void
}) {
  const [error, setError] = useState('')
  const apply = (day: string) => {
    if (!validDate(day)) {
      setError('Choose a valid calendar date.')
      return
    }
    const params = new URLSearchParams(query)
    params.set('schedule_date', day)
    if (!navigate(params)) onRefresh()
  }
  return (
    <div className="date-navigation">
      <Button
        variant="secondary"
        aria-label="Previous day"
        onClick={() => {
          try {
            apply(shiftDay(date, -1))
          } catch {
            setError('No previous supported date.')
          }
        }}
      >
        ←
      </Button>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          apply(String(new FormData(event.currentTarget).get('schedule_date') ?? ''))
        }}
      >
        <label>
          Schedule date
          <input
            type="date"
            name="schedule_date"
            key={date}
            required
            defaultValue={date}
            onChange={() => {
              setError('')
            }}
          />
        </label>
        <Button variant="secondary" type="submit">
          Show schedule
        </Button>
      </form>
      <Button
        variant="secondary"
        aria-label="Next day"
        onClick={() => {
          try {
            apply(shiftDay(date, 1))
          } catch {
            setError('No next supported date.')
          }
        }}
      >
        →
      </Button>
      {error && <p role="alert">{error}</p>}
    </div>
  )
}

export function MeetingList({ meetings, reference }: { meetings: Meeting[]; reference: string }) {
  return meetings.length ? (
    <ol className="meeting-list" aria-label="Scheduled meetings">
      {meetings.map((meeting) => (
        <li key={meeting.id}>
          <div>
            <strong>{eventLabel(meeting)}</strong>
            <br />
            <time dateTime={meeting.starts_at}>
              {nextBookingLabel(meeting.starts_at, reference)}
            </time>{' '}
            –{' '}
            <time dateTime={meeting.ends_at}>
              {nextBookingLabel(meeting.ends_at, meeting.starts_at)}
            </time>
          </div>
          <Badge tone={meeting.status === 'cancelled' ? 'neutral' : ''}>
            {meeting.status === 'cancelled' ? 'Cancelled' : 'Scheduled'}
          </Badge>
        </li>
      ))}
    </ol>
  ) : (
    <p className="small">No meetings listed. Missing coverage never establishes availability.</p>
  )
}

type Selection = { title: string; room: string; start: string; end: string; detail: string }
function IntervalDialog({ selection, onClose }: { selection: Selection; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    ref.current?.showModal()
  }, [])
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby="interval-title"
      className="interval-dialog"
    >
      <h2 id="interval-title">{selection.title}</h2>
      <p>{selection.room}</p>
      <p>
        {dateLabel(selection.start, true)} · {campusTimeLabel(selection.start)} to{' '}
        {nextBookingLabel(selection.end, selection.start)} Toronto time
      </p>
      <p>{selection.detail}</p>
      <Button variant="secondary" onClick={() => ref.current?.close()}>
        Close interval details
      </Button>
    </dialog>
  )
}

export function Calendar({
  entries,
  window,
  date,
  query,
}: {
  entries: CalendarRoom[]
  window: TimeWindow
  date: string
  query: string
}) {
  const [show, setShow] = useState(() => {
    try {
      return localStorage.getItem('utscvacant.showEvents') !== 'false'
    } catch {
      return true
    }
  })
  const [selection, setSelection] = useState<Selection | null>(null)
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(timer)
  }, [])
  const start = Date.parse(window.start),
    end = Date.parse(window.end)
  const hours = (end - start) / 3_600_000
  const width = Math.max(720, hours * 64)
  const step = hours > 16 ? 2 : 1
  const ticks = Array.from({ length: Math.floor(hours / step) + 1 }, (_, i) =>
    new Date(start + i * step * 3_600_000).toISOString(),
  )
  const current =
    now.getTime() >= start && now.getTime() < end && campusDate(now) === date
      ? ((now.getTime() - start) / (end - start)) * 100
      : null
  return (
    <section className="day-calendar" aria-label="Day calendar">
      <div className="calendar-tools">
        <label className="toggle-control">
          <input
            type="checkbox"
            checked={show}
            onChange={(event) => {
              setShow(event.target.checked)
              try {
                localStorage.setItem('utscvacant.showEvents', String(event.target.checked))
              } catch {
                /* Session setting still works. */
              }
            }}
          />
          Show scheduled events
        </label>
        <span className="small">{dateLabel(window.start)} · Toronto time</span>
      </div>
      <ul className="calendar-legend" aria-label="Calendar legend">
        <li>✓ Available</li>
        <li>■ Scheduled</li>
        <li>▧ Unknown coverage</li>
        <li>┄ Cancelled booking</li>
      </ul>
      <div
        className="calendar-scroll"
        role="region"
        aria-label="Scrollable room timeline"
        tabIndex={0}
      >
        <div className="calendar-grid" style={{ gridTemplateColumns: `140px ${width}px` }}>
          <div className="room-axis">Room</div>
          <div className="time-axis">
            {ticks.map((tick) => (
              <span
                key={tick}
                style={{ left: `${((Date.parse(tick) - start) / (end - start)) * 100}%` }}
              >
                {campusTimeLabel(tick)}
              </span>
            ))}
          </div>
          {entries.map((entry) => {
            const name = roomLabel(entry.room),
              events = layoutEvents(entry.meetings, window)
            const height = show
              ? Math.max(100, (Math.max(0, ...events.map((event) => event.lane)) + 1) * 62 + 28)
              : 60
            const params = new URLSearchParams(query)
            params.set('room', String(entry.room.room_id))
            return (
              <div className="calendar-row" key={entry.room.room_id}>
                <div className="calendar-room">
                  <a
                    id={`room-link-${entry.room.room_id}`}
                    href={`?${params}`}
                    onClick={(event) => routeClick(event, params)}
                  >
                    {name}
                  </a>
                  <span>
                    {entry.room.capacity === null
                      ? 'Capacity unknown'
                      : `${entry.room.capacity} seats`}
                  </span>
                </div>
                <div className="calendar-track" style={{ height }}>
                  {entry.calendar.periods.map((period) => {
                    const position = positionRange(period.starts_at, period.ends_at, window)
                    if (!position) return null
                    const label =
                      period.state === 'available'
                        ? 'Available'
                        : period.state === 'scheduled'
                          ? 'Scheduled'
                          : 'Unknown'
                    return (
                      <button
                        key={`${period.starts_at}:${period.state}`}
                        className={`calendar-period ${period.state}`}
                        style={{ left: `${position.left}%`, width: `${position.width}%` }}
                        aria-label={`${name} ${label}, ${campusTimeLabel(period.starts_at)} to ${nextBookingLabel(period.ends_at, period.starts_at)}`}
                        onClick={() =>
                          setSelection({
                            title: label,
                            room: name,
                            start: period.starts_at,
                            end: period.ends_at,
                            detail:
                              period.state === 'available'
                                ? 'Complete published coverage with no scheduled conflict. This is not a guarantee of occupancy or access.'
                                : period.state === 'unknown'
                                  ? 'Schedule coverage is incomplete or missing. Do not assume availability.'
                                  : 'This interval has a scheduled booking.',
                          })
                        }
                      >
                        <span>
                          {period.state === 'available'
                            ? '✓ '
                            : period.state === 'unknown'
                              ? '▧ '
                              : '■ '}
                          {label}
                        </span>
                      </button>
                    )
                  })}
                  {show &&
                    events.map(({ meeting, position, lane }) => (
                      <button
                        key={meeting.id}
                        className={`event-block ${meeting.status}`}
                        style={{
                          left: `${position.left}%`,
                          width: `${position.width}%`,
                          top: 26 + lane * 62,
                        }}
                        onClick={() =>
                          setSelection({
                            title: eventLabel(meeting),
                            room: name,
                            start: meeting.starts_at,
                            end: meeting.ends_at,
                            detail:
                              meeting.status === 'cancelled'
                                ? 'Cancelled: this booking does not block otherwise covered time.'
                                : 'Scheduled booking. Course labels are unavailable unless explicitly approved by the source owner.',
                          })
                        }
                      >
                        <span className="event-caption">{eventLabel(meeting)}</span>{' '}
                        <span className="event-times">
                          {campusTimeLabel(meeting.starts_at)}
                          <br />– {campusTimeLabel(meeting.ends_at)}
                        </span>
                        <span className="sr-only">
                          , {name}, {dateLabel(meeting.starts_at, true)} to{' '}
                          {dateLabel(meeting.ends_at, true)} Toronto time
                        </span>
                      </button>
                    ))}
                  {current !== null && (
                    <div
                      className="now-line"
                      style={{ left: `${current}%` }}
                      aria-label={`Current Toronto time ${campusTimeLabel(now)}`}
                    >
                      <span>Now</span>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
      <p className="small calendar-caveat">
        Availability comes from the published schedule. Unknown gaps are never free; cancelled
        bookings do not block otherwise covered time. Event labels default to “Scheduled event.”
      </p>
      {selection && <IntervalDialog selection={selection} onClose={() => setSelection(null)} />}
    </section>
  )
}
