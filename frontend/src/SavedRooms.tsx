import { useQuery } from '@tanstack/react-query'
import { api } from './api.ts'
import type { Building, StatusResponse } from './api.ts'
import { useFavourites } from './favourites.ts'
import { FavouriteButton } from './FavouriteButton.tsx'
import { requestParams } from './search.ts'
import { routeClick, useSearchLocation } from './navigation.ts'
import { ErrorPanel, OfflinePanel, SessionNotice } from './components.tsx'
import { EmptyState } from './ui.tsx'
import { Results } from './Results.tsx'

export function SavedRooms({
  query,
  online,
  status,
  statusPending,
  buildings,
}: {
  query: string
  online: boolean
  status?: StatusResponse
  statusPending: boolean
  buildings: Building[]
}) {
  const { value } = useFavourites()
  const location = useSearchLocation(query)
  const result = useQuery({
    queryKey: ['saved', value.rooms, query, status?.dataset_id],
    queryFn: ({ signal }) => {
      const search = requestParams(location.search)
      return api.roomSearch(
        {
          ...search,
          building: undefined,
          room_name: undefined,
          include_next: true,
          room_ids: value.rooms,
        },
        signal,
      )
    },
    enabled:
      online && !location.error && !location.session && !statusPending && value.rooms.length > 0,
    staleTime: location.search.mode === 'now' ? 0 : Infinity,
    refetchInterval: location.search.mode === 'now' && !location.session ? 60_000 : false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: location.search.mode === 'now',
    refetchOnReconnect: location.search.mode === 'now',
  })
  const find = new URLSearchParams(query)
  find.delete('view')
  return (
    <section className="saved-page building-page" aria-labelledby="page-title">
      <p className="eyebrow">Your browser · no account needed</p>
      <h1 id="page-title" tabIndex={-1}>
        Saved rooms
      </h1>
      <p>
        Uses your search time and duration, without inventory filters.{' '}
        <a href={`?${find}`} onClick={(event) => routeClick(event, find)}>
          Change search time
        </a>
        .
      </p>
      <p className="small">
        Saved on this browser only (up to 100 rooms and 50 buildings). If storage is blocked,
        favourites last for this session. Schedule availability is always checked with the service.
      </p>
      <h2>Saved buildings</h2>
      {value.buildings.length ? (
        <ul className="saved-buildings">
          {value.buildings.map((code) => {
            const params = new URLSearchParams(query)
            params.set('view', 'buildings')
            params.set('building', code)
            return (
              <li key={code}>
                <a href={`?${params}`} onClick={(event) => routeClick(event, params)}>
                  {code} ·{' '}
                  {buildings.find((item) => item.code === code)?.name ?? 'Building listing'}
                </a>
                <FavouriteButton kind="buildings" id={code} label={code} />
              </li>
            )
          })}
        </ul>
      ) : (
        <p>No buildings saved yet. Save one from Building schedules.</p>
      )}
      <h2>Room status</h2>
      {!value.rooms.length ? (
        <EmptyState title="No saved rooms yet">
          <p>Save a room from search results or room details.</p>
        </EmptyState>
      ) : location.error ? (
        <p role="alert">{location.error}</p>
      ) : location.session ? (
        <SessionNotice session={location.session} />
      ) : !online ? (
        <OfflinePanel />
      ) : result.isError ? (
        <ErrorPanel
          error={result.error}
          onRetry={() => {
            void result.refetch()
          }}
        />
      ) : result.isPending ? (
        <p role="status">Checking saved rooms…</p>
      ) : (
        <>
          <button
            className="text-button"
            disabled={result.isFetching}
            onClick={() => {
              void result.refetch()
            }}
          >
            Refresh saved rooms
          </button>
          {result.isFetching && (
            <p role="status">Updating results. The times below show the previous check.</p>
          )}
          <Results result={result.data} status={status} params={new URLSearchParams(query)} />
          {result.data.meta.missing_room_ids.map((id) => (
            <div className="notice warning" key={id}>
              Saved room {id} is no longer found.{' '}
              <FavouriteButton kind="rooms" id={id} label={`room ${id}`} />
            </div>
          ))}
        </>
      )}
    </section>
  )
}
