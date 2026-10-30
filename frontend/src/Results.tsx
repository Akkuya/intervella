import type { RoomSearchResponse, StatusResponse } from './api.ts'
import { FreshnessNote } from './components.tsx'
import { campusTimeLabel, dateLabel, nextBookingLabel } from './time.ts'
import { Badge, EmptyState, RoomCard } from './ui.tsx'
import { FavouriteButton } from './FavouriteButton.tsx'
import { roomLabel } from './rooms.ts'

export function Results({
  result,
  status,
  params,
}: {
  result: RoomSearchResponse
  status?: StatusResponse
  params: URLSearchParams
}) {
  const overview =
    params.get('include_next') === '1' ||
    params.get('view') === 'saved' ||
    result.data.some((room) => room.state !== 'available')
  const counts = [
    ['available', 'available for the requested time'],
    ['scheduled', 'with scheduled conflicts'],
    ['unknown', 'with unknown coverage'],
    ['inactive', 'inactive'],
  ]
    .map(([state, label]) => ({
      count: result.data.filter((room) => room.state === state).length,
      label,
    }))
    .filter(({ count }) => count > 0)
    .map(({ count, label }) => `${count} ${label}`)
    .join(' · ')
  return (
    <>
      <div className="time-strip">
        <span className="eyebrow">Search window · Toronto</span>
        <strong>
          {campusTimeLabel(result.query.start)} <span aria-hidden="true">—</span>
          <span className="sr-only"> to </span>{' '}
          {nextBookingLabel(result.query.end, result.query.start)}
        </strong>
        <span>{dateLabel(result.query.start)}</span>
      </div>
      <FreshnessNote meta={result.meta} status={status} />
      {result.meta.unknown_room_count > 0 && (
        <p className="coverage-note" role="status">
          <strong>
            {result.meta.unknown_room_count}{' '}
            {result.meta.unknown_room_count === 1 ? 'room' : 'rooms'}{' '}
            {params.get('include_next') === '1' || params.get('view') === 'saved'
              ? result.meta.unknown_room_count === 1
                ? 'has unknown coverage'
                : 'have unknown coverage'
              : 'excluded'}
          </strong>{' '}
          because coverage is incomplete, unknown, or too short for this search.
        </p>
      )}
      <p className="result-count" role="status">
        {result.data.length} {result.data.length === 1 ? 'room shown' : 'rooms shown'}
        {result.data.length > 0 && `: ${counts}`}
      </p>
      {result.data.length === 0 ? (
        <EmptyState
          title={overview ? 'No room listings to show' : 'No matching rooms for this time'}
        >
          <p>
            {overview
              ? 'No room listings were returned for these filters. Check saved listings or try another room name or building.'
              : 'No fully covered rooms match this search. Try another duration or building. This is not a statement about every room on campus.'}
          </p>
        </EmptyState>
      ) : (
        <div className="room-grid">
          {result.data.map((room) => (
            <RoomCard
              key={room.room_id}
              room={room}
              params={params}
              status={
                <Badge
                  tone={
                    room.state === 'available'
                      ? 'green'
                      : room.state === 'unknown'
                        ? 'amber'
                        : 'neutral'
                  }
                >
                  {room.state === 'available'
                    ? 'Schedule available'
                    : room.state === 'scheduled'
                      ? 'Scheduled conflict'
                      : room.state === 'inactive'
                        ? 'Inactive listing'
                        : 'Unknown coverage'}
                </Badge>
              }
            >
              <div className="booking">
                {room.state === 'available' && room.available_until ? (
                  <>
                    <span>Available until</span>
                    <strong>{nextBookingLabel(room.available_until, result.query.start)}</strong>
                  </>
                ) : room.state !== 'inactive' ? (
                  <>
                    <span>Next known opening</span>
                    <strong>
                      {room.next_available_start
                        ? nextBookingLabel(room.next_available_start, result.query.start)
                        : 'No suitable time confirmed'}
                    </strong>
                  </>
                ) : (
                  <p>
                    This room has left the active inventory. Historical details remain available.
                  </p>
                )}
                <span>Next scheduled booking</span>
                <strong>
                  {room.next_booking
                    ? nextBookingLabel(room.next_booking, result.query.start)
                    : 'No later booking known'}
                </strong>
              </div>
              <FavouriteButton kind="rooms" id={room.room_id} label={roomLabel(room)} />
            </RoomCard>
          ))}
        </div>
      )}
      <p className="small">
        Known times are bounded by published coverage and a 24-hour horizon. Next known openings may
        follow gaps with unknown coverage; they are not a claim about the earliest possible
        availability. No later booking known never means unlimited availability.
      </p>
      {result.meta.has_more && (
        <p className="coverage-note">
          More rooms were found. Narrow the building or room filter; results are capped by the
          service.
        </p>
      )}
    </>
  )
}
