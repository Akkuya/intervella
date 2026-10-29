import { Select, DatePicker, TimePicker } from './Controls.tsx'
import { endSuggestions } from './picker-time.ts'
import { useState } from 'react'
import type { FormEvent } from 'react'
import type { Building, Freshness, StatusResponse } from './api.ts'
import { ApiError } from './api.ts'
import type { SearchInput } from './search.ts'
import { requestParams } from './search.ts'
import type { SearchSessionEnded } from './search.ts'
import {
  campusDate,
  campusTime,
  campusTimeLabel,
  dateLabel,
  localCandidates,
  zoneLabel,
  toInstant,
} from './time.ts'
import { Button, Badge } from './ui.tsx'

export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="state-panel error-panel" role="alert">
      <h3>We couldn’t check the schedule</h3>
      <p>{error instanceof ApiError ? error.message : 'Check your search and try again.'}</p>
      {error instanceof ApiError && error.requestId && (
        <p className="small">
          Request reference: <code>{error.requestId}</code>
        </p>
      )}
      <Button variant="secondary" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}

export function OfflinePanel() {
  return (
    <div className="state-panel" role="status">
      <h3>You’re offline</h3>
      <p>
        Connect to the internet to check the schedule. Previous results are not a current
        availability confirmation.
      </p>
    </div>
  )
}

export function SessionNotice({ session }: { session: SearchSessionEnded }) {
  return (
    <div className="state-panel notice warning" role="status">
      <h3>{session.state === 'expired' ? 'Session expired' : 'Session ending'}</h3>
      <p>
        {session.state === 'expired'
          ? 'Your selected end time has passed.'
          : 'Fewer than five minutes remain before your selected end time.'}{' '}
        End: {dateLabel(session.end)} at {campusTimeLabel(session.end)} Toronto time.
      </p>
      <p>
        Live results are paused. Earlier room checks no longer confirm availability for this
        session. Choose a later end time or switch to Duration to start a new search.
      </p>
    </div>
  )
}

export function FreshnessNote({ meta, status }: { meta: Freshness; status?: StatusResponse }) {
  const current =
    status?.dataset_id === meta.dataset_id &&
    Date.parse(status.generated_at) > Date.parse(meta.generated_at)
      ? status
      : meta
  return (
    <div className="source-receipt">
      {current.freshness === 'stale' && (
        <div className="notice warning" role="status">
          <strong>Older schedule</strong>
          <p>The source is stale. Covered results are still shown, but may miss recent changes.</p>
        </div>
      )}
      <p className="freshness-line">
        <Badge tone={current.freshness === 'stale' ? 'amber' : ''}>
          {current.freshness === 'stale' ? 'Stale source' : 'Fresh source'}
        </Badge>
        <span>
          Updated {dateLabel(meta.source_fetched_at)} at {campusTimeLabel(meta.source_fetched_at)} ·
          Toronto time
        </span>
      </p>
      <details className="source-details">
        <summary>Source details</summary>
        <p>
          Fetched {dateLabel(meta.source_fetched_at, true)} at{' '}
          {campusTimeLabel(meta.source_fetched_at)} Toronto time.
        </p>
        <p>
          Last checked {dateLabel(meta.generated_at, true)} at {campusTimeLabel(meta.generated_at)}{' '}
          Toronto time. Source freshness does not guarantee physical vacancy.
        </p>
      </details>
    </div>
  )
}

export function SearchForm({
  initial,
  buildings,
  buildingsError,
  onSearch,
}: {
  initial: SearchInput
  buildings: Building[]
  buildingsError: boolean
  onSearch: (input: SearchInput) => void
}) {
  const [value, setValue] = useState(initial)
  const [error, setError] = useState('')
  let startInstant: string | undefined
  try {
    startInstant =
      value.mode === 'now'
        ? new Date().toISOString()
        : toInstant(value.date, value.time, value.offset)
  } catch {
    /* Require a valid start/occurrence before suggesting an end. */
  }
  const suggestions = endSuggestions(startInstant)
  let candidates: ReturnType<typeof localCandidates> = []
  let endCandidates: ReturnType<typeof localCandidates> = []
  if (value.endDate && value.endTime) {
    try {
      endCandidates = localCandidates(value.endDate, value.endTime)
    } catch {
      /* Validate on submit. */
    }
  }
  if (value.mode === 'custom') {
    try {
      candidates = localCandidates(value.date, value.time)
    } catch {
      /* Validate on submit. */
    }
  }
  const update = (patch: Partial<SearchInput>) => {
    setValue({ ...value, ...patch })
    setError('')
  }
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    try {
      requestParams(value)
      setError('')
      onSearch(value)
    } catch (cause) {
      setError((cause as Error).message)
      const target = event.currentTarget.elements.namedItem(
        candidates.length > 1 ? 'offset' : 'date',
      )
      if (target instanceof HTMLElement) target.focus()
    }
  }
  const durations = [...new Set([5, 15, 30, 45, 60, 90, 120, 180, 240, value.duration])].sort(
    (a, b) => a - b,
  )
  const unknownBuilding =
    value.building && !buildings.some((building) => building.code === value.building)
  return (
    <form className="search-card" onSubmit={submit} aria-label="Availability search">
      <div className="card-heading">
        <span className="eyebrow">Your next study session</span>
        <h2>Find a room</h2>
      </div>
      <fieldset className="when-control">
        <legend>When do you need a room?</legend>
        <label className={value.mode === 'now' ? 'selected' : ''}>
          <input
            type="radio"
            name="mode"
            value="now"
            checked={value.mode === 'now'}
            onChange={() => update({ mode: 'now' })}
          />
          Free now
        </label>
        <label className={value.mode === 'custom' ? 'selected' : ''}>
          <input
            type="radio"
            name="mode"
            value="custom"
            checked={value.mode === 'custom'}
            onChange={() => {
              const now = new Date(Math.round(Date.now() / 300_000) * 300_000)
              update({ mode: 'custom', date: campusDate(now), time: campusTime(now), offset: '' })
            }}
          />
          Choose a time
        </label>
      </fieldset>
      {value.mode === 'custom' ? (
        <>
          <div className="field-row">
            <label>
              Date
              <DatePicker
                label="Date"
                value={value.date}
                onChange={(selection) => update({ date: selection, offset: '' })}
              />
            </label>
            <label>
              Start time
              <TimePicker
                label="Start time"
                value={value.time}
                date={value.date}
                onChange={(selection) => update({ time: selection, offset: '' })}
              />
            </label>
          </div>
          {candidates.length > 1 && (
            <label>
              Time occurrence
              <Select
                label="Time occurrence"
                name="offset"
                value={value.offset}
                aria-describedby="search-error"
                onChange={(selection) => update({ offset: selection })}
              >
                <option value="">Choose an occurrence</option>
                {candidates.map((candidate, i) => (
                  <option key={candidate.offset} value={candidate.offset}>
                    {i === 0 ? 'First' : 'Second'} occurrence ({zoneLabel(candidate.instant)})
                  </option>
                ))}
              </Select>
            </label>
          )}
        </>
      ) : (
        <p className="field-hint">
          Starts at the current time. Refreshes every minute while this tab is visible.
        </p>
      )}
      <p id="timezone-help" className="small">
        All dates and times use Toronto time (ET).
      </p>
      <label>
        Search length
        <Select
          label="Search length"
          value={value.endDate !== undefined ? 'until' : 'duration'}
          onChange={(selection) =>
            update(
              selection === 'until'
                ? { endDate: value.date, endTime: '', endOffset: '' }
                : { endDate: undefined, endTime: undefined, endOffset: undefined },
            )
          }
        >
          <option value="duration">Duration</option>
          <option value="until">Available until</option>
        </Select>
      </label>
      {value.endDate !== undefined ? (
        <>
          <div className="field-row">
            <label>
              End date
              <DatePicker
                label="End date"
                value={value.endDate}
                onChange={(selection) => update({ endDate: selection, endOffset: '' })}
              />
            </label>
            <label>
              Available until
              <TimePicker
                label="Available until"
                value={value.endTime ?? ''}
                date={value.endDate ?? ''}
                start={startInstant}
                suggestions={suggestions}
                onSuggestion={(suggestion) =>
                  update({
                    endDate: suggestion.date,
                    endTime: suggestion.time,
                    endOffset: suggestion.offset,
                  })
                }
                onChange={(selection) => update({ endTime: selection, endOffset: '' })}
              />
            </label>
          </div>
          {endCandidates.length > 1 && (
            <label>
              End time occurrence
              <Select
                label="End time occurrence"
                value={value.endOffset ?? ''}
                onChange={(selection) => update({ endOffset: selection })}
              >
                <option value="">Choose an occurrence</option>
                {endCandidates.map((candidate, index) => (
                  <option key={candidate.offset} value={candidate.offset}>
                    {index === 0 ? 'First' : 'Second'} occurrence ({zoneLabel(candidate.instant)})
                  </option>
                ))}
              </Select>
            </label>
          )}
          <p className="small">
            Choose an end 5–240 minutes after the start, in Toronto time. Midnight may use the next
            date.
          </p>
        </>
      ) : (
        <label>
          Duration
          <Select
            label="Duration"
            value={value.duration}
            onChange={(selection) => update({ duration: Number(selection) })}
          >
            {durations.map((minutes) => (
              <option key={minutes} value={minutes}>
                {minutes} minutes
              </option>
            ))}
          </Select>
        </label>
      )}
      <label>
        Building
        <Select
          label="Building"
          value={value.building}
          onChange={(selection) => update({ building: selection })}
        >
          <option value="">All buildings</option>
          {unknownBuilding && (
            <option value={value.building}>{value.building} (check building code)</option>
          )}
          {buildings.map((building) => (
            <option key={building.id} value={building.code}>
              {building.code} · {building.name}
            </option>
          ))}
        </Select>
      </label>
      {buildingsError && (
        <p className="small">Building list unavailable. You can still search all buildings.</p>
      )}
      <label>
        Room name
        <input
          type="search"
          maxLength={64}
          placeholder="e.g. AA112 or AA-112"
          value={value.roomName ?? ''}
          onChange={(event) => update({ roomName: event.target.value })}
        />
      </label>
      <label>
        Sort rooms
        <Select
          label="Sort rooms"
          value={value.sort ?? 'building'}
          onChange={(selection) => update({ sort: selection as SearchInput['sort'] })}
        >
          <option value="building">Building, then room</option>
          <option value="room">Room number</option>
          <option value="duration">Longest known availability</option>
        </Select>
      </label>
      <label className="toggle-control">
        <input
          type="checkbox"
          checked={value.includeNext ?? false}
          onChange={(event) => update({ includeNext: event.target.checked })}
        />
        Include other rooms and next known openings
      </label>
      <p id="search-error" className="form-error" role={error ? 'alert' : undefined}>
        {error}
      </p>
      <Button type="submit">
        Find rooms <span aria-hidden="true">↗</span>
      </Button>
      <p className="small">
        A schedule can show a gap. It can’t tell you whether a door is open or a room is occupied.
      </p>
    </form>
  )
}
