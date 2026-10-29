import { useState } from 'react'
import { Select, TimePicker } from './Controls.tsx'
import type { Inventory, InventoryRoom, InventoryWindow } from './operator-api.ts'

export function WindowEditor({
  label,
  value,
  date,
  onChange,
}: {
  label: string
  value: InventoryWindow
  date: string
  onChange: (value: InventoryWindow) => void
}) {
  return (
    <fieldset className="ops-window">
      <legend>{label}</legend>
      <label>
        Start (Toronto)
        <TimePicker
          label={`${label} start`}
          value={value.start}
          date={date}
          minuteStep={30}
          onChange={(start) => onChange({ ...value, start })}
        />
      </label>
      <label>
        End (Toronto)
        <TimePicker
          label={`${label} end`}
          value={value.end === '24:00' ? '00:00' : value.end}
          date={date}
          minuteStep={30}
          onChange={(end) => onChange({ ...value, end: end === '00:00' ? '24:00' : end })}
        />
      </label>
      <p className="small">
        Expected timetable coverage, not opening hours. End at or before start crosses midnight.
        Only half-hour boundaries are supported by the source grid.
      </p>
    </fieldset>
  )
}

export function InventoryEditor({
  value,
  date,
  onChange,
  disabled = false,
}: {
  value: Inventory
  date: string
  onChange: (value: Inventory) => void
  disabled?: boolean
}) {
  const [filter, setFilter] = useState('')
  const changeBuilding = (index: number, patch: Partial<Inventory['buildings'][number]>) =>
    onChange({
      ...value,
      buildings: value.buildings.map((b, i) => (i === index ? { ...b, ...patch } : b)),
    })
  const changeRoom = (building: number, index: number, patch: Partial<InventoryRoom>) =>
    changeBuilding(building, {
      rooms: value.buildings[building].rooms.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    })
  return (
    <fieldset className="ops-inventory" disabled={disabled}>
      <legend>Building and room mappings</legend>
      <p className="small">
        Canonical building codes and room numbers keep database identities stable. Source IDs are
        timetable locators, never database room IDs. Label prefixes are suggestions that require
        independent review.
      </p>
      <WindowEditor
        label="Default expected window"
        value={value.window}
        date={date}
        onChange={(window) => onChange({ ...value, window })}
      />
      <label>
        Find a room or building
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Source label, building code or room number"
        />
      </label>
      {value.buildings.map((building, bi) => {
        const visible = building.rooms
          .map((room, ri) => ({ room, ri }))
          .filter(({ room }) =>
            `${building.code} ${building.name} ${room.source_name} ${room.room_number}`
              .toLowerCase()
              .includes(filter.toLowerCase()),
          )
        if (filter && !visible.length) return null
        return (
          <details className="ops-mapping-group" key={bi} open={filter ? true : undefined}>
            <summary>
              {building.code || 'Unmapped building'} · {building.name || 'Name required'} ·{' '}
              {building.rooms.length} rooms
            </summary>
            <div className="ops-editor-fields">
              <label>
                Source building label
                <input
                  value={building.source_name}
                  maxLength={128}
                  onChange={(e) => changeBuilding(bi, { source_name: e.target.value })}
                />
              </label>
              <label>
                Canonical building code
                <input
                  value={building.code}
                  maxLength={16}
                  onChange={(e) => changeBuilding(bi, { code: e.target.value })}
                  placeholder="Confirm the canonical code"
                />
              </label>
              <label>
                Building display name
                <input
                  value={building.name}
                  maxLength={128}
                  onChange={(e) => changeBuilding(bi, { name: e.target.value })}
                />
              </label>
              <button
                type="button"
                className="text-button"
                onClick={() =>
                  onChange({ ...value, buildings: value.buildings.filter((_, i) => i !== bi) })
                }
              >
                Remove building {building.code || bi + 1} from draft
              </button>
            </div>
            {visible.map(({ room, ri }) => (
              <details className="ops-room-mapping" key={ri}>
                <summary>
                  {room.source_name} → {building.code || '?'}-{room.room_number || '?'} ·{' '}
                  {room.capacity ?? 'Unknown'} seats
                </summary>
                <div className="ops-editor-fields">
                  <label>
                    Source room label
                    <input
                      value={room.source_name}
                      maxLength={128}
                      onChange={(e) => changeRoom(bi, ri, { source_name: e.target.value })}
                    />
                  </label>
                  <label>
                    Canonical room number
                    <input
                      value={room.room_number}
                      maxLength={32}
                      onChange={(e) => changeRoom(bi, ri, { room_number: e.target.value })}
                    />
                  </label>
                  <label>
                    Source room ID (optional for weekly)
                    <input
                      type="number"
                      min={1}
                      value={room.source_id ?? ''}
                      onChange={(e) =>
                        changeRoom(bi, ri, {
                          source_id: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    />
                  </label>
                  <label>
                    Expected capacity
                    <input
                      type="number"
                      min={1}
                      value={room.capacity ?? ''}
                      onChange={(e) =>
                        changeRoom(bi, ri, {
                          capacity: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    />
                  </label>
                  <label>
                    Move room to building
                    <Select
                      label={`Building for ${room.source_name}`}
                      value={String(bi)}
                      onChange={(v) => {
                        const target = Number(v)
                        onChange({
                          ...value,
                          buildings: value.buildings.map((b, i) =>
                            i === bi
                              ? { ...b, rooms: b.rooms.filter((_, j) => j !== ri) }
                              : i === target
                                ? { ...b, rooms: [...b.rooms, room] }
                                : b,
                          ),
                        })
                      }}
                    >
                      {value.buildings.map((b, i) => (
                        <option key={i} value={String(i)}>
                          {b.code || `Unmapped building ${i + 1}`}
                        </option>
                      ))}
                    </Select>
                  </label>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() =>
                      changeBuilding(bi, { rooms: building.rooms.filter((_, i) => i !== ri) })
                    }
                  >
                    Remove {room.source_name} from draft
                  </button>
                </div>
                <WindowEditor
                  label={`Expected window for ${room.source_name}`}
                  value={room.window ?? value.window}
                  date={date}
                  onChange={(window) => changeRoom(bi, ri, { window })}
                />
              </details>
            ))}
            <button
              type="button"
              className="button secondary"
              onClick={() =>
                changeBuilding(bi, {
                  rooms: [
                    ...building.rooms,
                    {
                      source_name: '',
                      room_number: '',
                      source_id: null,
                      capacity: null,
                      window: { ...value.window },
                    },
                  ],
                })
              }
            >
              Add expected room to {building.code || 'building'}
            </button>
          </details>
        )
      })}
      {filter &&
        !value.buildings.some((b) =>
          b.rooms.some((r) =>
            `${b.code} ${b.name} ${r.source_name} ${r.room_number}`
              .toLowerCase()
              .includes(filter.toLowerCase()),
          ),
        ) && <p role="status">No mappings match. Clear the filter to review all expected rooms.</p>}
      <button
        type="button"
        className="button secondary"
        onClick={() =>
          onChange({
            ...value,
            buildings: [...value.buildings, { source_name: '', code: '', name: '', rooms: [] }],
          })
        }
      >
        Add expected building
      </button>
    </fieldset>
  )
}
