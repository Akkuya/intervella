import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api.ts'
import type { StatusResponse } from './api.ts'
import {
  ErrorPanel,
  FreshnessNote,
  OfflinePanel,
  SearchForm,
  SessionNotice,
} from './components.tsx'
import {
  navigate,
  routeClick,
  useLocationSearch,
  useOnline,
  useSearchLocation,
} from './navigation.ts'
import { requestParams, searchParams } from './search.ts'
import type { SearchInput } from './search.ts'
import { campusTimeLabel, dateLabel, nextBookingLabel } from './time.ts'
import { StudentSignOut } from './StudentAccess.tsx'
import { ThemeControl } from './theme.tsx'
import { timeText } from './picker-time.ts'
import { roomLabel } from './rooms.ts'
import { Results } from './Results.tsx'
import { SavedRooms } from './SavedRooms.tsx'
import { BuildingLink } from './ui.tsx'
import { FavouriteButton } from './FavouriteButton.tsx'
import { Calendar, CalendarDate, MeetingList } from './Calendar.tsx'
import { BuildingSchedules } from './BuildingSchedules.tsx'
import './App.css'

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
  if (back.get('view') !== 'buildings') back.delete('schedule_date')
  return (
    <section className="room-detail" aria-labelledby="room-title">
      <a className="back-link" href={`?${back}`} onClick={(event) => routeClick(event, back)}>
        ← {back.get('view') === 'buildings' ? 'Back to building schedules' : 'Back to results'}
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
        {details && (
          <div className="detail-actions">
            <FavouriteButton kind="rooms" id={details.room_id} label={roomLabel(details)} />
            <BuildingLink
              code={details.building_code}
              params={new URLSearchParams(query)}
              date={date}
            />
          </div>
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
              <CalendarDate
                date={date}
                query={query}
                onRefresh={() => {
                  void schedule.refetch()
                }}
              />
            </div>
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
                {schedule.data.calendar ? (
                  <Calendar
                    entries={[
                      {
                        room: schedule.data.room,
                        meetings: schedule.data.data,
                        calendar: schedule.data.calendar,
                      },
                    ]}
                    window={schedule.data.calendar.window}
                    date={date}
                    query={query}
                  />
                ) : (
                  <p className="notice warning">
                    Calendar details unavailable. Use the schedule list; missing coverage is never
                    free.
                  </p>
                )}
                {schedule.data.data.length ? (
                  <details className="schedule-list">
                    <summary>Accessible schedule list</summary>
                    <MeetingList
                      meetings={schedule.data.data}
                      reference={schedule.data.query.start}
                    />
                  </details>
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
  const [editingQuery, setEditingQuery] = useState<string | null>(null)
  const query = useLocationSearch()
  const editing = editingQuery === query
  useEffect(() => {
    const clearDraft = () => setEditingQuery(null)
    window.addEventListener('popstate', clearDraft)
    return () => window.removeEventListener('popstate', clearDraft)
  }, [])
  const online = useOnline()
  const location = useSearchLocation(query)
  const previous = useRef({
    room: location.roomId,
    date: location.scheduleDate,
    view: location.view,
  })
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
    queryFn: ({ signal }) => api.roomSearch(requestParams(location.search), signal),
    enabled:
      online &&
      !editing &&
      !location.error &&
      !location.session &&
      location.roomId === undefined &&
      location.view === 'find',
    staleTime: location.search.mode === 'now' ? 0 : Infinity,
    refetchInterval: location.search.mode === 'now' && !location.session ? 60_000 : false,
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
    else if (old.view !== location.view) document.getElementById('page-title')?.focus()
    previous.current = { room: location.roomId, date: location.scheduleDate, view: location.view }
  }, [location.roomId, location.scheduleDate, location.view])
  const findParams = new URLSearchParams(query)
  findParams.delete('view')
  findParams.delete('room')
  findParams.delete('schedule_date')
  const calendarParams = new URLSearchParams(findParams)
  calendarParams.set('view', 'buildings')
  calendarParams.set('schedule_date', location.scheduleDate)
  const savedParams = new URLSearchParams(findParams)
  savedParams.set('view', 'saved')
  const onSearch = (input: SearchInput) => {
    const params = searchParams(input)
    setEditingQuery(null)
    navigate(params, true)
  }
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="site-header shell">
        <a className="brand" href="?" onClick={(event) => routeClick(event, new URLSearchParams())}>
          <img className="brand-mark" src="/assets/intervella.svg" alt="" width="40" height="40" />
          <span>Intervella</span>
        </a>
        <div className="account-controls">
          <ThemeControl />
          <StudentSignOut />
        </div>
        <nav className="app-navigation" aria-label="Application">
          <a
            href={`?${findParams}`}
            onClick={(event) => routeClick(event, findParams)}
            aria-current={!location.roomId && location.view === 'find' ? 'page' : undefined}
          >
            Find a room
          </a>
          <a
            href={`?${calendarParams}`}
            onClick={(event) => routeClick(event, calendarParams)}
            aria-current={!location.roomId && location.view === 'buildings' ? 'page' : undefined}
          >
            Building schedules
          </a>
          <a
            href={`?${savedParams}`}
            onClick={(event) => routeClick(event, savedParams)}
            aria-current={!location.roomId && location.view === 'saved' ? 'page' : undefined}
          >
            Saved rooms
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
        ) : location.view === 'saved' ? (
          <SavedRooms
            query={query}
            online={online}
            status={status.data}
            statusPending={status.isPending}
            buildings={buildings.data?.data ?? []}
          />
        ) : location.view === 'buildings' ? (
          <BuildingSchedules
            query={query}
            buildings={buildings.data?.data ?? []}
            status={status.data}
            online={online}
            loading={buildings.isPending}
            error={buildings.error}
            reloadBuildings={() => {
              void buildings.refetch()
            }}
            statusPending={status.isPending}
          />
        ) : (
          <>
            <div className="intro">
              <div>
                <p className="eyebrow">Find your space between classes.</p>
                <h1 id="page-title" tabIndex={-1}>
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
                <details className="search-filters">
                  <summary>
                    Search filters{' '}
                    <span>
                      {location.search.mode === 'now'
                        ? 'Free now'
                        : `${location.search.date} at ${timeText(location.search.time)}`}{' '}
                      · {location.search.building || 'All buildings'} ·{' '}
                      {location.search.endDate !== undefined
                        ? `Until ${location.search.endTime ? timeText(location.search.endTime) : 'end time'} on ${location.search.endDate}`
                        : `${location.search.duration} min`}
                    </span>
                  </summary>
                  <SearchForm
                    initial={location.search}
                    buildings={buildings.data?.data ?? []}
                    buildingsError={buildings.isError}
                    onSearch={onSearch}
                    onEditing={(value) => setEditingQuery(value ? query : null)}
                  />
                </details>
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
                      {location.session
                        ? 'Search session'
                        : location.search.includeNext ||
                            result.data?.data.some((room) => room.state !== 'available')
                          ? 'Room status'
                          : 'Schedule available'}
                    </h2>
                  </div>
                  <button
                    type="button"
                    className="text-button"
                    disabled={
                      editing ||
                      result.isFetching ||
                      !online ||
                      !!location.error ||
                      !!location.session
                    }
                    onClick={() => {
                      void result.refetch()
                      void status.refetch()
                    }}
                  >
                    Refresh
                  </button>
                </div>
                {editing ? (
                  <div className="state-panel" role="status">
                    <h3>Updating your search</h3>
                    <p>
                      Complete valid filters to see matching rooms. Earlier results do not describe
                      these changes.
                    </p>
                  </div>
                ) : location.error ? (
                  <div className="state-panel error-panel" role="alert">
                    <h3>Check this saved search</h3>
                    <p>{location.error}</p>
                    <p>Choose your search settings again to correct the link.</p>
                  </div>
                ) : location.session ? (
                  <SessionNotice session={location.session} />
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
