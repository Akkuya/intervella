import { Children, isValidElement, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Button,
  Select as AriaSelect,
  SelectValue,
  ListBox,
  ListBoxItem,
  Popover,
} from 'react-aria-components/Select'
import { DialogTrigger, Dialog, Heading } from 'react-aria-components/Dialog'
import { Calendar, CalendarGrid, CalendarCell } from 'react-aria-components/Calendar'
import { RadioGroup, Radio } from 'react-aria-components/RadioGroup'
import { parseDate, parseZonedDateTime } from '@internationalized/date'
import {
  campusDate,
  campusTime,
  dateLabel,
  validDate,
  nextBookingLabel,
  toInstant,
} from './time.ts'
import { allowedTime, nearestFive, parseTimeText, timeText } from './picker-time.ts'
import './controls.css'

export function Select({
  label,
  value,
  onChange,
  children,
  name,
  disabled = false,
  'aria-describedby': describedBy,
}: {
  label: string
  value: string | number
  onChange: (value: string) => void
  children: ReactNode
  name?: string
  disabled?: boolean
  'aria-describedby'?: string
}) {
  const items = Children.toArray(children)
    .filter(isValidElement<{ value: string | number; children: ReactNode; disabled?: boolean }>)
    .map((child) => ({
      id: `option:${child.props.value}`,
      text: child.props.children,
      disabled: child.props.disabled,
    }))
  return (
    <AriaSelect
      className="ui-select"
      aria-label={label}
      selectedKey={`option:${value}`}
      onSelectionChange={(key) => onChange(String(key).slice(7))}
      isDisabled={disabled}
      disabledKeys={items.filter((item) => item.disabled).map((item) => item.id)}
    >
      <Button className="control-trigger" name={name} aria-describedby={describedBy}>
        <SelectValue />
        <span className="control-chevron" aria-hidden="true">
          ⌄
        </span>
      </Button>
      <Popover
        style={{ zIndex: 30 }}
        className="control-popover select-popover"
        offset={6}
        placement="bottom start"
      >
        <ListBox className="control-options" items={items}>
          {(item) => (
            <ListBoxItem
              className="control-option"
              id={item.id}
              textValue={Children.toArray(item.text).join('')}
            >
              {({ isSelected }) => (
                <>
                  <span>{item.text}</span>
                  <span aria-hidden="true">{isSelected ? '✓' : ''}</span>
                </>
              )}
            </ListBoxItem>
          )}
        </ListBox>
      </Popover>
    </AriaSelect>
  )
}

export function DatePicker({
  label,
  value,
  onChange,
  name,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  name?: string
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(value)
  const [error, setError] = useState('')
  const selected =
    validDate(value) && value >= '1900-01-01' && value <= '2099-12-31'
      ? parseZonedDateTime(`${value}T12:00[America/Toronto]`)
      : null
  const choose = (date: string) => {
    if (!validDate(date) || date < '1900-01-01' || date > '2099-12-31') {
      setError('Choose a valid date.')
      return
    }
    onChange(date)
    setOpen(false)
  }
  return (
    <DialogTrigger
      isOpen={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) {
          setDraft(value)
          setError('')
        }
      }}
    >
      {name && <input type="hidden" name={name} value={value} />}
      <Button
        className="control-trigger"
        name={label === 'Date' ? 'date' : undefined}
        aria-label={`${label}: ${selected ? dateLabel(`${value}T16:00:00Z`, true) : 'Choose a date'}`}
      >
        {selected ? (
          <time dateTime={value}>{dateLabel(`${value}T16:00:00Z`, true)}</time>
        ) : (
          'Choose a date'
        )}
        <span aria-hidden="true">▦</span>
      </Button>
      <Popover
        style={{ zIndex: 30 }}
        // The inner dialog owns its name; avoid naming the nonsemantic portal wrapper.
        aria-labelledby=""
        className="control-popover picker-popover"
        offset={6}
        placement="bottom start"
      >
        <Dialog aria-label={`${label} calendar`} className="picker-dialog">
          <Calendar
            aria-label={label}
            value={selected}
            onChange={(day) => choose(day.toString().slice(0, 10))}
            defaultFocusedValue={
              selected ?? parseZonedDateTime(`${campusDate(new Date())}T12:00[America/Toronto]`)
            }
            minValue={parseDate('1900-01-01')}
            maxValue={parseDate('2099-12-31')}
          >
            <header className="picker-header">
              <Button slot="previous" aria-label="Previous month">
                ←
              </Button>
              <Heading />
              <Button slot="next" aria-label="Next month">
                →
              </Button>
            </header>
            <CalendarGrid>
              {(date) => <CalendarCell date={date} className="calendar-day" />}
            </CalendarGrid>
          </Calendar>
          <label>
            Calendar date (YYYY-MM-DD)
            <input
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value)
                setError('')
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  choose(draft)
                }
              }}
            />
          </label>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="picker-footer">
            <Button onPress={() => choose(campusDate(new Date()))}>Today</Button>
            <Button onPress={() => choose(draft)}>Use date</Button>
            <Button onPress={() => setOpen(false)}>Close</Button>
          </div>
        </Dialog>
      </Popover>
    </DialogTrigger>
  )
}

export interface TimeSuggestion {
  label: string
  date: string
  time: string
  offset: string
}
export function TimePicker({
  label,
  value,
  date,
  onChange,
  start,
  suggestions = [],
  onSuggestion,
}: {
  label: string
  value: string
  date: string
  onChange: (value: string) => void
  start?: string
  suggestions?: TimeSuggestion[]
  onSuggestion?: (suggestion: TimeSuggestion) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(value)
  const [text, setText] = useState(timeText(value))
  const [error, setError] = useState('')
  const [hour, minute] = (/^\d{2}:\d{2}$/.test(draft) ? draft : '00:00').split(':').map(Number)
  const update = (h: number, m: number) => {
    const next = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
    setDraft(next)
    setText(timeText(next))
    setError('')
  }
  const validate = () => {
    try {
      const next = parseTimeText(text)
      if (!allowedTime(date, next, start))
        throw new Error(
          'This time does not exist in Toronto, or is outside the allowed 5–240 minute window.',
        )
      onChange(next)
      setOpen(false)
    } catch (cause) {
      setError((cause as Error).message)
    }
  }
  return (
    <DialogTrigger
      isOpen={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) {
          let initial = value || nearestFive()
          if (!value && start && !allowedTime(date, initial, start)) {
            const first = new Date(Math.ceil((Date.parse(start) + 300_000) / 300_000) * 300_000)
            if (campusDate(first) === date) initial = campusTime(first)
          }
          setDraft(initial)
          setText(timeText(initial))
          setError('')
        }
      }}
    >
      <Button aria-label={`${label}: ${timeText(value)}`} className="control-trigger">
        {value ? <time dateTime={value}>{timeText(value)}</time> : 'Choose a time'}
        <span aria-hidden="true">◷</span>
      </Button>
      <Popover
        style={{ zIndex: 30 }}
        // The inner dialog owns its name; avoid naming the nonsemantic portal wrapper.
        aria-labelledby=""
        className="control-popover picker-popover time-popover"
        offset={6}
        placement="bottom start"
      >
        <Dialog aria-label={`${label} picker`} className="picker-dialog">
          <Heading slot="title">{label}</Heading>
          <p className="time-preview" aria-live="polite">
            {timeText(draft)}
          </p>
          <p className="small">Toronto time · five-minute selections</p>
          <label>
            Hour
            <Select
              label="Hour"
              value={hour % 12 || 12}
              onChange={(value) => update((Number(value) % 12) + (hour >= 12 ? 12 : 0), minute)}
            >
              {Array.from({ length: 12 }, (_, index) => (
                <option
                  key={index + 1}
                  value={index + 1}
                  disabled={
                    !Array.from({ length: 12 }, (_, m) => m * 5).some((m) =>
                      allowedTime(
                        date,
                        `${String(((index + 1) % 12) + (hour >= 12 ? 12 : 0)).padStart(2, '0')}:${String(m).padStart(2, '0')}`,
                        start,
                      ),
                    )
                  }
                >
                  {index + 1}
                </option>
              ))}
            </Select>
          </label>
          <span className="small">Minute</span>
          <RadioGroup
            aria-label="Minute"
            className="minute-grid"
            value={String(minute)}
            onChange={(value) => update(hour, Number(value))}
          >
            {Array.from({ length: 12 }, (_, index) => index * 5).map((m) => (
              <Radio
                key={m}
                value={String(m)}
                isDisabled={
                  !allowedTime(
                    date,
                    `${String(hour).padStart(2, '0')}:${String(m).padStart(2, '0')}`,
                    start,
                  )
                }
              >
                {String(m).padStart(2, '0')}
              </Radio>
            ))}
          </RadioGroup>
          <RadioGroup
            aria-label="AM or PM"
            className="period-toggle"
            orientation="horizontal"
            value={hour >= 12 ? 'PM' : 'AM'}
            onChange={(period) => update((hour % 12) + (period === 'PM' ? 12 : 0), minute)}
          >
            <Radio value="AM">AM</Radio>
            <Radio value="PM">PM</Radio>
          </RadioGroup>
          <label>
            Type a time
            <input
              aria-label="Type a time"
              value={text}
              placeholder="2:30 PM, 14:30 or 1430"
              onChange={(event) => {
                setText(event.target.value)
                setError('')
                try {
                  setDraft(parseTimeText(event.target.value))
                } catch {
                  /* Validate on apply. */
                }
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  validate()
                }
              }}
            />
          </label>
          {value && Number(value.slice(3)) % 5 !== 0 && (
            <p className="small">
              Saved time {timeText(value)} is preserved. Choose a five-minute time to replace it.
            </p>
          )}
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
          {suggestions.length > 0 && (
            <div className="time-suggestions">
              {suggestions.map((item) => (
                <Button
                  key={item.label}
                  onPress={() => {
                    onSuggestion?.(item)
                    setOpen(false)
                  }}
                >
                  {item.label} ·{' '}
                  {nextBookingLabel(
                    toInstant(item.date, item.time, item.offset),
                    start ?? `${date}T16:00:00Z`,
                  )}
                </Button>
              ))}
            </div>
          )}
          <div className="picker-footer">
            <Button onPress={validate}>Use time</Button>
            <Button onPress={() => setOpen(false)}>Cancel</Button>
          </div>
        </Dialog>
      </Popover>
    </DialogTrigger>
  )
}
