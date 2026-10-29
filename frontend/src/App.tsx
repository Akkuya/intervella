import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api.ts'
import type { AvailabilityResponse, StatusResponse } from './api.ts'
import { ErrorPanel, FreshnessNote, OfflinePanel, SearchForm } from './components.tsx'
import { navigate, routeClick, useLocationSearch, useOnline } from './navigation.ts'
import { readLocation, requestParams, searchParams } from './search.ts'
import type { SearchInput } from './search.ts'
import { campusTimeLabel, dateLabel, validDate, nextBookingLabel } from './time.ts'
import { ThemeControl } from './theme.tsx'
import { roomLabel } from './rooms.ts'
import { Badge, EmptyState, RoomCard } from './ui.tsx'
import './App.css'

function Results({
  result,
  status,
  params,
}: {
  result: AvailabilityResponse
  status?: StatusResponse
  params: URLSearchParams
}) {
  return (
    <>
      <div className="time-strip">
        <span className="eyebrow">Search window · Toronto</span>
        <strong className="tabular-nums">
          {campusTimeLabel(result.query.start)} <span aria-hidden="true">—</span>
          <span className="sr-only"> to </span>{' '}
          {nextBookingLabel(result.query.end, result.query.start)}
        </strong>
        <span>{dateLabel(result.query.start)}</span>
      </div>
      <FreshnessNote meta={result.meta} status={status} />
      {result.meta.unknown_room_count > 0 && (
        <p className="coverage-note" role="status">
          <strong>{result.meta.unknown_room_count} rooms excluded</strong> because coverage is
          incomplete, unknown, or too short for this search.
        </p>
      )}
      <p className="result-count" role="status">
        {result.data.length} {result.data.length === 1 ? 'room matches' : 'rooms match'} this search
      </p>
      {result.data.length === 0 ? (
        <EmptyState title="No matching rooms for this time">
          <p>
            No fully covered rooms match this search. Try another duration or building. This is not
            a statement about every room on campus.
          </p>
        </EmptyState>
      ) : (
        <div className="room-grid">
          {result.data.map((room) => (
            <RoomCard
              room={room}
              params={params}
              key={room.room_id}
              status={<Badge tone="green">Schedule available</Badge>}
            >
              <div className="booking">
                <span>Next scheduled booking</span>
                <strong>
                  {room.next_booking
                    ? nextBookingLabel(room.next_booking, result.query.start)
                    : 'No later booking known'}
                </strong>
              </div>
            </RoomCard>
          ))}
        </div>
      )}
      {result.meta.has_more && (
        <p className="coverage-note">
          More rooms match. Narrow the building filter to see a smaller set; results are capped by
          the service.
        </p>
      )}
    </>
  )
}

function RoomDetails({
  id,
  date,
  status,
  online,
  query,
}: {
  id: number
  date: string
  status?: StatusResponse
  online: boolean
  query: string
}) {
  const [day, setDay] = useState(date)
  const [dateError, setDateError] = useState('')
  const room = useQuery({
    queryKey: ['room', id, status?.dataset_id],
    queryFn: ({ signal }) => api.room(id, signal),
    enabled: online,
    staleTime: Infinity,
  })
  const schedule = useQuery({
    queryKey: ['room-schedule', id, date, status?.dataset_id],
    queryFn: ({ signal }) => api.schedule(id, date, signal),
    enabled: online,
    staleTime: Infinity,
  })
  const details = schedule.data?.room ?? room.data?.data
  const back = new URLSearchParams(query)
  back.delete('room')
  back.delete('schedule_date')
  return (
    <section className="room-detail" aria-labelledby="room-title">
      <a className="back-link" href={`?${back}`} onClick={(event) => routeClick(event, back)}>
        ← Back to results
      </a>
      <div className="detail-heading">
        <span className="eyebrow">Room details</span>
        <h1 id="room-title" tabIndex={-1}>
          {details ? roomLabel(details) : 'Room details'}
        </h1>
        {details && (
          <p>
            {details.capacity === null ? 'Capacity not published' : `${details.capacity} seats`}
            {!details.active && ' · Inactive listing'}
          </p>
        )}
      </div>
      {!online ? (
        <OfflinePanel />
      ) : room.isError ? (
        <ErrorPanel
          error={room.error}
          onRetry={() => {
            void room.refetch()
            void schedule.refetch()
          }}
        />
      ) : (
        <>
          <div className="schedule-panel">
            <div className="schedule-heading">
              <div>
                <span className="eyebrow">Toronto calendar day</span>
                <h2 id="schedule-title" tabIndex={-1}>
                  Room schedule
                </h2>
              </div>
              <form
                className="schedule-form"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (!validDate(day)) {
                    setDateError('Choose a valid date.')
                    return
                  }
                  const params = new URLSearchParams(query)
                  params.set('schedule_date', day)
                  if (!navigate(params)) void schedule.refetch()
                }}
              >
                <label>
                  Schedule date
                  <input
                    type="date"
                    value={day}
                    required
                    onChange={(event) => {
                      setDay(event.target.value)
                      setDateError('')
                    }}
                  />
                </label>
                <button className="button secondary" type="submit">
                  Show schedule
                </button>
              </form>
            </div>
            {dateError && <p role="alert">{dateError}</p>}
            {schedule.isError ? (
              <ErrorPanel
                error={schedule.error}
                onRetry={() => {
                  void schedule.refetch()
                }}
              />
            ) : schedule.isPending ? (
              <p role="status">Loading room schedule…</p>
            ) : (
              <>
                <p className="schedule-date" role="status">
                  {dateLabel(schedule.data.query.start)} ·{' '}
                  {campusTimeLabel(schedule.data.query.start)} to{' '}
                  {nextBookingLabel(schedule.data.query.end, schedule.data.query.start)}
                </p>
                <FreshnessNote meta={schedule.data.meta} status={status} />
                {schedule.data.meta.coverage.completeness !== 'complete' && (
                  <p className="notice warning" role="status">
                    <strong>Coverage is {schedule.data.meta.coverage.completeness}.</strong> An
                    empty schedule does not establish availability.
                  </p>
                )}
                {schedule.data.data.length ? (
                  <ol className="meeting-list" aria-label="Scheduled meetings">
                    {schedule.data.data.map((meeting) => (
                      <li key={meeting.id}>
                        <div>
                          <time dateTime={meeting.starts_at}>
                            {nextBookingLabel(meeting.starts_at, schedule.data.query.start)}
                          </time>
                          <span> – </span>
                          <time dateTime={meeting.ends_at}>
                            {nextBookingLabel(meeting.ends_at, meeting.starts_at)}
                          </time>
                        </div>
                        <span
                          className={`badge ${meeting.status === 'cancelled' ? 'neutral' : ''}`}
                        >
                          {meeting.status === 'cancelled' ? 'Cancelled' : 'Scheduled'}
                        </span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div className="state-panel">
                    <h3>No meetings listed</h3>
                    <p>
                      {schedule.data.meta.coverage.completeness === 'complete'
                        ? 'No scheduled meetings are listed for this covered day. This is not live occupancy information.'
                        : 'Coverage is incomplete or unknown. Do not assume this room is available.'}
                    </p>
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}
    </section>
  )
}

export default function App() {
  const query = useLocationSearch()
  const online = useOnline()
  const location = readLocation(query)
  const previous = useRef({ room: location.roomId, date: location.scheduleDate })
  const status = useQuery({
    queryKey: ['status'],
    queryFn: ({ signal }) => api.status(signal),
    enabled: online,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  })
  const buildings = useQuery({
    queryKey: ['buildings', status.data?.dataset_id],
    queryFn: ({ signal }) => api.buildings(signal),
    enabled: online,
    staleTime: Infinity,
  })
  const result = useQuery({
    queryKey: ['availability', searchParams(location.search).toString(), status.data?.dataset_id],
    queryFn: ({ signal }) => api.availability(requestParams(location.search), signal),
    enabled: online && !location.error && location.roomId === undefined,
    staleTime: location.search.mode === 'now' ? 0 : Infinity,
    refetchInterval: location.search.mode === 'now' ? 60_000 : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: location.search.mode === 'now',
    refetchOnReconnect: location.search.mode === 'now',
  })
  useEffect(() => {
    const old = previous.current
    if (old.room !== location.roomId) {
      const target = location.roomId ? 'room-title' : `room-link-${old.room}`
      ;(document.getElementById(target) ?? document.getElementById('results-title'))?.focus()
    } else if (location.roomId && old.date !== location.scheduleDate)
      document.getElementById('schedule-title')?.focus()
    previous.current = { room: location.roomId, date: location.scheduleDate }
  }, [location.roomId, location.scheduleDate])
  const onSearch = (input: SearchInput) => {
    const params = searchParams(input)
    const unchanged = params.toString() === searchParams(location.search).toString()
    navigate(params)
    if (unchanged) void result.refetch()
    document.getElementById('results-title')?.focus()
  }
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="site-header shell">
        <a className="brand" href="?" onClick={(event) => routeClick(event, new URLSearchParams())}>
          <span className="brand-mark" aria-hidden="true">
            u.
          </span>
          <span>
            UTSC<span className="brand-accent">Vacant</span>
          </span>
        </a>
        <ThemeControl />
        <nav className="app-navigation" aria-label="Application">
          <a
            href="?"
            onClick={(event) => routeClick(event, new URLSearchParams())}
            aria-current={!location.roomId ? 'page' : undefined}
          >
            Find a room
          </a>
        </nav>
      </header>
      <aside className="provenance shell" id="data-note" aria-label="Data provenance">
        <span className="provenance-symbol" aria-hidden="true">
          !
        </span>
        <div>
          <strong>Unverified / demo data</strong>
          <p>
            This development app may show synthetic schedules. Results are not verified current
            campus availability.
          </p>
        </div>
      </aside>
      <main id="main" className="shell" tabIndex={-1}>
        {location.roomId && !location.error ? (
          <RoomDetails
            key={`${location.roomId}:${location.scheduleDate}`}
            id={location.roomId}
            date={location.scheduleDate}
            status={status.data}
            online={online}
            query={query}
          />
        ) : (
          <>
            <div className="intro">
              <div>
                <p className="eyebrow">Find your next study spot</p>
                <h1>
                  Find a room
                  <br className="desktop-break" /> between classes.
                </h1>
                <p>
                  Check scheduled classroom availability.
                  <br />
                  Choose a time. Make space for your next session.
                </p>
              </div>
              <aside className="source-summary" aria-label="Schedule source status">
                <span className="eyebrow">Schedule source</span>
                <strong>
                  {!online
                    ? 'Offline'
                    : status.isError
                      ? 'Status unavailable'
                      : status.isPending
                        ? 'Checking source…'
                        : status.data.usable
                          ? 'Published schedule'
                          : 'Coverage unavailable now'}
                </strong>
                <span>
                  {status.data?.period
                    ? `Source window: ${dateLabel(status.data.period.start)} at ${campusTimeLabel(status.data.period.start)} until ${dateLabel(status.data.period.end)} at ${campusTimeLabel(status.data.period.end)}`
                    : 'A published schedule is needed to confirm coverage.'}
                </span>
                <a href="#data-note">Read the data notice ↑</a>
              </aside>
            </div>
            <div className="workspace">
              <aside className="search-column">
                <SearchForm
                  key={searchParams(location.search).toString()}
                  initial={location.search}
                  buildings={buildings.data?.data ?? []}
                  buildingsError={buildings.isError}
                  onSearch={onSearch}
                />
              </aside>
              <section
                className="results"
                aria-labelledby="results-title"
                aria-busy={result.isFetching}
              >
                <div className="results-heading">
                  <div>
                    <span className="eyebrow">Based on the published timetable</span>
                    <h2 id="results-title" tabIndex={-1}>
                      Schedule available
                    </h2>
                  </div>
                  <button
                    type="button"
                    className="text-button"
                    disabled={result.isFetching || !online || !!location.error}
                    onClick={() => {
                      void result.refetch()
                      void status.refetch()
                    }}
                  >
                    Refresh
                  </button>
                </div>
                {location.error ? (
                  <div className="state-panel error-panel" role="alert">
                    <h3>Check this saved search</h3>
                    <p>{location.error}</p>
                    <p>Choose your search settings again to correct the link.</p>
                  </div>
                ) : !online ? (
                  <OfflinePanel />
                ) : result.isError ? (
                  <ErrorPanel
                    error={result.error}
                    onRetry={() => {
                      void result.refetch()
                      void status.refetch()
                    }}
                  />
                ) : result.isPending ? (
                  <div className="state-panel loading" role="status">
                    <span className="loading-mark" aria-hidden="true" />
                    <h3>Checking the schedule…</h3>
                    <p>Looking for complete coverage of your requested time.</p>
                  </div>
                ) : (
                  <>
                    {result.isFetching && (
                      <p role="status" className="small">
                        Updating results. The times below show the previous check.
                      </p>
                    )}
                    <Results
                      result={result.data}
                      status={status.data}
                      params={new URLSearchParams(query)}
                    />
                  </>
                )}
              </section>
            </div>
          </>
        )}
      </main>
      <footer className="site-footer shell">
        <span>Made for the space between classes.</span>
        <p>
          Independent project. Not affiliated with the University of Toronto. Scheduled availability
          does not guarantee access or vacancy.
        </p>
        <a href="#data-note">Data notice</a>
      </footer>
    </>
  )
}
