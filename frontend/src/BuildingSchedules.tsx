import { Select } from './Controls.tsx'
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api.ts'
import type { Building, StatusResponse } from './api.ts'
import { Calendar, CalendarDate, MeetingList } from './Calendar.tsx'
import { ErrorPanel, FreshnessNote, OfflinePanel } from './components.tsx'
import { EmptyState } from './ui.tsx'
import { navigate } from './navigation.ts'
import { readLocation } from './search.ts'
import { roomLabel } from './rooms.ts'
import { useFavourites } from './favourites.ts'
import { FavouriteButton } from './FavouriteButton.tsx'

export function BuildingSchedules({
  query,
  buildings,
  status,
  online,
  loading,
  error,
  reloadBuildings,
  statusPending,
}: {
  query: string
  buildings: Building[]
  status?: StatusResponse
  online: boolean
  loading: boolean
  error: unknown
  reloadBuildings: () => void
  statusPending: boolean
}) {
  const { value: favourites } = useFavourites()
  const location = readLocation(query)
  const params = new URLSearchParams(query)
  const code = params.get('building') || buildings[0]?.code || ''
  const date = location.scheduleDate
  useEffect(() => {
    if (!new URLSearchParams(query).get('building') && buildings[0]) {
      const next = new URLSearchParams(query)
      next.set('building', buildings[0].code)
      navigate(next, true)
    }
  }, [query, buildings])
  const result = useQuery({
    queryKey: ['building-day', code, date, (status?.publication_id ?? status?.dataset_id)],
    queryFn: ({ signal }) => api.buildingSchedule(code, date, signal),
    enabled: online && !!code && !location.error && !statusPending,
    staleTime: Infinity,
  })
  return (
    <section className="building-page" aria-labelledby="page-title">
      <p className="eyebrow">One building · one published snapshot</p>
      <h1 id="page-title" tabIndex={-1}>
        Building schedules
      </h1>
      <div className="selected-building">
        <span className="building-code">{code}</span>
        <h2>
          {buildings.find((building) => building.code === code)?.name ?? 'Building inventory'}
        </h2>
      </div>
      <nav className="saved-building-shortcuts" aria-label="Saved buildings">
        {buildings
          .filter((building) => favourites.buildings.includes(building.code))
          .map((building) => (
            <button
              key={building.code}
              className="text-button"
              aria-pressed={building.code === code}
              onClick={() => {
                const next = new URLSearchParams(query)
                next.set('building', building.code)
                navigate(next)
              }}
            >
              {building.code}
            </button>
          ))}
      </nav>
      <p className="small">
        Compare rooms on the same Toronto timeline. Scroll sideways for the full day.
      </p>
      <div className="building-controls">
        <label>
          Building
          <Select
            label="Building"
            value={code}
            onChange={(selection) => {
              const next = new URLSearchParams(query)
              next.set('building', selection)
              navigate(next)
            }}
          >
            {!code && <option value="">Choose a building</option>}
            {code && !buildings.some((building) => building.code === code) && (
              <option value={code}>{code} (check building code)</option>
            )}
            {buildings.map((building) => (
              <option key={building.id} value={building.code}>
                {building.code} · {building.name}
              </option>
            ))}
          </Select>
        </label>
        <CalendarDate
          date={date}
          query={query}
          onRefresh={() => {
            void result.refetch()
          }}
        />
      </div>
      {!online ? (
        <OfflinePanel />
      ) : location.error ? (
        <p role="alert">{location.error}</p>
      ) : !code ? (
        loading ? (
          <p role="status">Loading buildings…</p>
        ) : error ? (
          <ErrorPanel error={error} onRetry={reloadBuildings} />
        ) : (
          <EmptyState title="No active buildings">
            <p>No active building inventory is published.</p>
          </EmptyState>
        )
      ) : result.isError ? (
        <ErrorPanel
          error={result.error}
          onRetry={() => {
            void result.refetch()
          }}
        />
      ) : result.isPending ? (
        <p role="status">Loading building schedule…</p>
      ) : (
        <>
          <FavouriteButton kind="buildings" id={code} label={code} />
          <FreshnessNote meta={result.data.meta} status={status} />
          {result.data.meta.unknown_room_count > 0 && (
            <p className="coverage-note" role="status">
              {result.data.meta.unknown_room_count}{' '}
              {result.data.meta.unknown_room_count === 1 ? 'room has' : 'rooms have'} incomplete or
              unknown coverage within this view.
            </p>
          )}
          {result.data.data.length ? (
            <>
              <Calendar
                entries={result.data.data}
                window={result.data.display_window}
                date={date}
                query={query}
              />
              <details className="schedule-list">
                <summary>Accessible schedule list</summary>
                {result.data.data.map((entry) => (
                  <section key={entry.room.room_id}>
                    <h2>{roomLabel(entry.room)}</h2>
                    <MeetingList meetings={entry.meetings} reference={result.data.query.start} />
                  </section>
                ))}
              </details>
            </>
          ) : (
            <EmptyState title="No active rooms in this building">
              <p>There are no active room listings in this published inventory.</p>
            </EmptyState>
          )}
        </>
      )}
    </section>
  )
}
