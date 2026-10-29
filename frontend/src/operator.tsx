import { useEffect, useRef, useState } from 'react'
import { Dialog, Heading } from 'react-aria-components/Dialog'
import { Modal, ModalOverlay } from 'react-aria-components/Modal'
import { DatePicker, Select } from './Controls.tsx'
import { ThemeControl } from './theme.tsx'
import { campusDate } from './time.ts'
import { opsRequest } from './operator-api.ts'
import type { OpsHealth, Preview } from './operator-api.ts'
import './index.css'
import './App.css'
import './operator.css'

function daysFrom(start: string) {
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(`${start}T12:00:00Z`)
    d.setUTCDate(d.getUTCDate() + i)
    return d.toISOString().slice(0, 10)
  })
}
function weeksFor(start: string) {
  return [
    ...new Set(
      daysFrom(start).map((day) => {
        const d = new Date(`${day}T12:00:00Z`)
        d.setUTCDate(d.getUTCDate() - d.getUTCDay())
        return d.toISOString().slice(0, 10)
      }),
    ),
  ]
}
const friendly = (value: string | null) =>
  value
    ? new Date(value).toLocaleString('en-CA', {
        timeZone: 'America/Toronto',
        dateStyle: 'medium',
        timeStyle: 'short',
      }) + ' ET'
    : 'Not known'

export default function Operator() {
  const [csrf, setCsrf] = useState(''),
    [secret, setSecret] = useState(''),
    [health, setHealth] = useState<OpsHealth | null>(null)
  const [tab, setTab] = useState('health'),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false)
  const [format, setFormat] = useState('weekly'),
    [start, setStart] = useState(campusDate(new Date()))
  const [inventory, setInventory] = useState(''),
    [captures, setCaptures] = useState<Record<string, string>>({}),
    [files, setFiles] = useState<Record<string, File>>({})
  const [batch, setBatch] = useState(''),
    [preview, setPreview] = useState<Preview | null>(null),
    [candidate, setCandidate] = useState('')
  const [reason, setReason] = useState(''),
    [ack, setAck] = useState(false),
    [confirm, setConfirm] = useState(false),
    [selection, setSelection] = useState('')
  const [notice, setNotice] = useState('')
  const task = useRef(false)
  const sourceDates = format === 'weekly' ? weeksFor(start) : daysFrom(start)
  const filename = (day: string) => (format === 'weekly' ? `week-${day}.html` : `${day}.html`)
  useEffect(() => {
    let alive = true
    opsRequest<{ csrf: string }>('session', '')
      .then((session) => {
        if (alive) setCsrf(session.csrf)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])
  useEffect(() => {
    if (!csrf) return
    let alive = true
    opsRequest<OpsHealth>('health', csrf)
      .then((h) => {
        if (alive) setHealth(h)
      })
      .catch((e) => {
        if (alive) setError(e.message)
      })
    return () => {
      alive = false
    }
  }, [csrf])
  async function run(action: () => Promise<void>) {
    if (task.current) return
    task.current = true
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed')
    } finally {
      task.current = false
      setBusy(false)
    }
  }
  async function loadInventory(file: File) {
    try {
      if (file.size > 1024 * 1024) throw new Error('Manifest must be smaller than 1 MB')
      const text = await file.text()
      const data = JSON.parse(text)
      setInventory(text)
      const items = data.weeks ?? data.snapshots ?? []
      setCaptures(
        Object.fromEntries(
          items.map((i: { week_start?: string; date?: string; fetched_at: string }) => [
            i.week_start ?? i.date,
            i.fetched_at,
          ]),
        ),
      )
    } catch {
      setError('Choose a valid approved JSON manifest.')
    }
  }
  async function dryRun() {
    const approved = JSON.parse(inventory)
    if (!ack || !reason.match(/^[a-z][a-z0-9_-]{0,63}$/))
      throw new Error('Acknowledge the reviewed inventory and enter a structured review reason.')
    if (!approved.buildings?.length || !approved.window)
      throw new Error('Load the approved inventory manifest with buildings and expected windows.')
    for (const day of sourceDates) {
      if (!files[day]) throw new Error(`Missing export for ${day}`)
      if (files[day].size > 10 * 1024 * 1024) throw new Error('HTML files must be at most 10 MB')
      if (!captures[day]) throw new Error(`Enter the actual capture timestamp for ${day}`)
    }
    const manifest = {
      version: format === 'weekly' ? 2 : 1,
      source_format: format,
      start_date: start,
      window: approved.window,
      buildings: approved.buildings,
      ...(format === 'weekly'
        ? {
            inventory_scope: 'complete',
            inventory_review_reason: reason,
            weeks: sourceDates.map((day) => ({
              week_start: day,
              file: filename(day),
              fetched_at: captures[day],
            })),
          }
        : { snapshots: sourceDates.map((day) => ({ date: day, fetched_at: captures[day] })) }),
    }
    if (batch) await opsRequest(`batches/${batch}`, csrf, 'DELETE')
    const created = await opsRequest<{ batch_id: string }>('batches', csrf, 'POST')
    setBatch(created.batch_id)
    const manifestFile = new File([JSON.stringify(manifest)], 'manifest.json', {
      type: 'application/json',
    })
    await opsRequest(`batches/${created.batch_id}/files/manifest.json`, csrf, 'PUT', manifestFile)
    for (const day of sourceDates)
      await opsRequest(
        `batches/${created.batch_id}/files/${filename(day)}`,
        csrf,
        'PUT',
        files[day],
      )
    setPreview(await opsRequest<Preview>(`batches/${created.batch_id}/preview`, csrf, 'POST'))
    setAck(false)
  }
  if (!csrf)
    return (
      <div className="ops-login shell">
        <header className="ops-header">
          <strong>UTSCVacant · Private operations</strong>
          <ThemeControl />
        </header>
        <main className="ops-login-card">
          <span className="eyebrow">Operator access only</span>
          <h1>Keep the schedule trustworthy.</h1>
          <p>
            Sign in to review local exports and deliberately publish validated data. This service
            does not fetch the intranet.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void run(async () => {
                try {
                  await opsRequest('login', '', 'POST', { secret })
                  const session = await opsRequest<{ csrf: string }>('session', '')
                  setCsrf(session.csrf)
                } finally {
                  setSecret('')
                }
              })
            }}
          >
            <label>
              Operator secret
              <input
                type="password"
                autoComplete="current-password"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                required
              />
            </label>
            <button className="button primary" disabled={busy}>
              Unlock private dashboard
            </button>
          </form>
          {error && (
            <p role="alert" className="form-error">
              {error.replaceAll('_', ' ')}
            </p>
          )}
        </main>
      </div>
    )
  const active = health?.active
  return (
    <div className="ops-shell">
      <header className="ops-header">
        <a href="#overview" className="brand">
          UTSCVacant <span className="small">/ operations</span>
        </a>
        <div className="ops-actions">
          <ThemeControl />
          <button
            className="button secondary"
            onClick={() =>
              void run(async () => {
                await opsRequest('logout', csrf, 'POST')
                setCsrf('')
                setHealth(null)
                setPreview(null)
                setFiles({})
                setInventory('')
              })
            }
          >
            Sign out
          </button>
        </div>
      </header>
      <main>
        <section className="ops-intro">
          <span className="eyebrow">Private local workspace</span>
          <h1>Data health & publication</h1>
          <p>Review the source. Check the gaps. Publish with confidence.</p>
          <p className="small">
            Source freshness describes the timetable, never physical vacancy. No live intranet
            access.
          </p>
        </section>
        <nav className="ops-tabs" aria-label="Operator sections">
          {[
            ['health', 'Overview'],
            ['import', 'Import timetable'],
            ['history', 'Import history'],
          ].map(([id, title]) => (
            <button
              key={id}
              aria-current={tab === id ? 'page' : undefined}
              onClick={() => setTab(id)}
            >
              {title}
            </button>
          ))}
        </nav>
        {error && (
          <div className="notice warning" role="alert">
            <strong>Action not completed</strong>
            <p>{error.replaceAll('_', ' ')}</p>
            <p>
              No success has been confirmed. Refresh data health to check the active identifier
              before retrying.
            </p>
          </div>
        )}
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        {busy && <p role="status">Working…</p>}
        {tab === 'health' && (
          <section id="overview" className="ops-section">
            <div className="ops-section-heading">
              <div>
                <h2>Published dataset</h2>
                <p>One active snapshot, backed by audited imports.</p>
              </div>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() =>
                  void run(async () => setHealth(await opsRequest<OpsHealth>('health', csrf)))
                }
              >
                Refresh health
              </button>
            </div>
            {!health ? (
              <p role="status">Loading data health…</p>
            ) : !active ? (
              <div className="ops-card">
                <h3>No published dataset</h3>
                <p>Validate and stage an approved export to begin.</p>
              </div>
            ) : (
              <>
                <div className="ops-metrics">
                  {[
                    ['Source state', active.freshness],
                    ['Rooms', active.rooms],
                    ['Buildings', active.buildings ?? 'Unknown'],
                    ['Bookings', active.occurrences ?? 'Unknown'],
                  ].map(([label, value]) => (
                    <div className="ops-card" key={label}>
                      <span className="eyebrow">{label}</span>
                      <strong>{value}</strong>
                    </div>
                  ))}
                </div>
                <div className="ops-card">
                  <span className="badge">{active.source_format}</span>
                  <p>
                    Coverage: {active.days[0]?.date ?? 'Unknown'} through{' '}
                    {active.days.at(-1)?.date ?? 'Unknown'}
                  </p>
                  <h3>Active · {active.dataset_id}</h3>
                  <dl className="ops-details">
                    <div>
                      <dt>Source captured</dt>
                      <dd>{friendly(active.source_fetched_at)}</dd>
                    </div>
                    <div>
                      <dt>Imported</dt>
                      <dd>{friendly(active.imported_at)}</dd>
                    </div>
                    <div>
                      <dt>Published</dt>
                      <dd>{friendly(active.published_at)}</dd>
                    </div>
                    <div>
                      <dt>Parser</dt>
                      <dd>{active.parser_version}</dd>
                    </div>
                  </dl>
                  {active.freshness === 'stale' && (
                    <p className="notice warning">
                      Stale source: importing again does not refresh its capture time.
                    </p>
                  )}
                </div>
                <div
                  className="ops-table"
                  tabIndex={0}
                  role="region"
                  aria-label="Daily provenance and coverage scrolling area"
                >
                  <table>
                    <caption>Daily provenance and coverage</caption>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Source capture</th>
                        <th>Complete rooms</th>
                        <th>Unknown</th>
                        <th>Missing</th>
                      </tr>
                    </thead>
                    <tbody>
                      {active.days.map((day) => (
                        <tr key={day.date}>
                          <th>{day.date}</th>
                          <td>
                            {friendly(day.fetched_at)} · {day.freshness ?? 'unknown'}
                          </td>
                          <td>{day.complete_rooms}</td>
                          <td>{day.unknown_rooms}</td>
                          <td>{day.missing_rooms}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        )}
        {tab === 'import' && (
          <section className="ops-section">
            <div className="ops-section-heading">
              <div>
                <h2>Import a timetable</h2>
                <p>Upload → validate → compare → stage → explicitly publish.</p>
              </div>
            </div>
            <div className="ops-import-grid">
              <div className="ops-card">
                <h3>1. Source & coverage</h3>
                <fieldset disabled={busy || !!candidate}>
                  <label>
                    Source format
                    <Select
                      label="Source format"
                      value={format}
                      onChange={(v) => {
                        setFormat(v)
                        setFiles({})
                        setPreview(null)
                      }}
                    >
                      <option value="weekly">Weekly exports</option>
                      <option value="daily">Daily exports</option>
                    </Select>
                  </label>
                  <p className="small">
                    Weekly is convenient only when the export is complete. Format and refresh
                    frequency are separate.
                  </p>
                  <label>
                    Target start date
                    <DatePicker
                      label="Target start date"
                      value={start}
                      onChange={(v) => {
                        setStart(v)
                        setFiles({})
                        setPreview(null)
                      }}
                    />
                  </label>
                  <p>
                    Seven days: {start} through {daysFrom(start)[6]}
                  </p>
                  {sourceDates.length === 2 && format === 'weekly' && (
                    <p className="notice warning">
                      This window crosses Sunday. Both enclosing-week exports are required.
                    </p>
                  )}
                </fieldset>
                <h3>2. Approved inventory</h3>
                <p className="small">
                  Load the reviewed daily/weekly manifest to reuse its building/room mappings,
                  capacities and expected time windows. Capture times below must reflect the actual
                  exports.
                </p>
                <label>
                  Load approved manifest
                  <input
                    type="file"
                    accept=".json,application/json"
                    disabled={busy || !!candidate}
                    onChange={(e) => {
                      if (e.target.files?.[0]) void loadInventory(e.target.files[0])
                    }}
                  />
                </label>
                <label>
                  Inventory and expected windows
                  <textarea
                    value={inventory}
                    onChange={(e) => setInventory(e.target.value)}
                    disabled={busy || !!candidate}
                    rows={8}
                    spellCheck={false}
                    placeholder="Approved manifest JSON"
                  />
                </label>
                <label>
                  Structured review reason
                  <input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="reviewed-inventory-2026-11"
                    pattern="[a-z][a-z0-9_-]{0,63}"
                  />
                </label>
                <label className="ops-check">
                  <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  I reviewed this complete inventory, capture metadata and any reported anomalies.
                </label>
              </div>
              <div className="ops-card">
                <h3>3. Private source files</h3>
                <p className="small">
                  Up to 10 MB per HTML file. Files expire after one hour or can be discarded below;
                  they are never publicly served.
                </p>
                <fieldset disabled={busy || !!candidate}>
                  {sourceDates.map((day) => (
                    <div
                      className="ops-upload"
                      key={day}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault()
                        if (!candidate && !busy && e.dataTransfer.files[0])
                          setFiles({ ...files, [day]: e.dataTransfer.files[0] })
                      }}
                    >
                      <strong>
                        {format === 'weekly' ? 'Week of' : 'Day'} {day}
                      </strong>
                      <label>
                        Export for {day}
                        <input
                          type="file"
                          accept=".html,text/html"
                          onChange={(e) => {
                            const updated = { ...files }
                            const file = e.target.files?.[0]
                            if (file) updated[day] = file
                            else delete updated[day]
                            setFiles(updated)
                          }}
                        />
                      </label>
                      <p className="small">
                        {files[day]
                          ? `${files[day].name} · ${Math.ceil(files[day].size / 1024)} KB`
                          : 'Choose or drop an authorized local export.'}
                      </p>
                      <label>
                        Actual capture timestamp for {day}
                        <input
                          value={captures[day] ?? ''}
                          placeholder="2026-10-29T12:30:00-04:00"
                          onChange={(e) => setCaptures({ ...captures, [day]: e.target.value })}
                        />
                      </label>
                      <p className="small">
                        Include an explicit UTC offset. Never replace an older capture time with
                        upload time.
                      </p>
                    </div>
                  ))}
                </fieldset>
                <div className="ops-actions">
                  <button
                    className="button primary"
                    disabled={busy || !!candidate}
                    onClick={() => void run(dryRun)}
                  >
                    Validate & compare (no database writes)
                  </button>
                  {batch && (
                    <button
                      className="button secondary"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          await opsRequest(`batches/${batch}`, csrf, 'DELETE')
                          setBatch('')
                          setCandidate('')
                          setPreview(null)
                          setNotice(
                            'Private uploaded files discarded. Audited datasets are retained.',
                          )
                        })
                      }
                    >
                      Discard uploads
                    </button>
                  )}
                </div>
              </div>
            </div>
            {preview && (
              <div className="ops-card ops-comparison">
                <h3>4. Validation & comparison</h3>
                <p>
                  {preview.summary.rooms} rooms · {preview.summary.buildings} buildings ·{' '}
                  {preview.summary.occurrences} bookings · {preview.summary.unknown_rooms} rooms
                  with unknown coverage
                </p>
                <p>Source captured {friendly(preview.summary.source_fetched_at)}</p>
                <p className="small">
                  Baseline: {preview.comparison.baseline_dataset_id ?? 'No active dataset'}
                </p>
                <div className="ops-metrics">
                  {[
                    ['Added rooms', preview.comparison.added_rooms.length],
                    ['Missing rooms', preview.comparison.missing_rooms.length],
                    ['Added intervals', preview.comparison.added_intervals],
                    ['Removed intervals', preview.comparison.removed_intervals],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <span>{label}</span>
                      <strong>{value}</strong>
                    </div>
                  ))}
                </div>
                {preview.comparison.warnings.map((w) => (
                  <p key={w} className="notice warning">
                    {w.replaceAll('_', ' ')}
                  </p>
                ))}
                <details>
                  <summary>Review room, capacity, coverage and daily changes</summary>
                  <p>New rooms: {preview.comparison.added_rooms.join(', ') || 'None'}</p>
                  <p>Missing rooms: {preview.comparison.missing_rooms.join(', ') || 'None'}</p>
                  <p>
                    Unknown rooms: {preview.comparison.previous_unknown_rooms ?? 'Unknown'} →{' '}
                    {preview.comparison.candidate_unknown_rooms}
                  </p>
                  {preview.comparison.capacity_changes.map((c) => (
                    <p key={c.room}>
                      {c.room}: {c.previous} → {c.candidate} seats
                    </p>
                  ))}
                  {preview.comparison.by_building_date.map((c) => (
                    <p key={c.building + c.date}>
                      {c.building} · {c.date}: {c.bookings} candidate bookings
                    </p>
                  ))}
                  {preview.sources.map((s) => (
                    <p key={s.date}>
                      {s.date} captured {friendly(s.fetched_at)}
                    </p>
                  ))}
                </details>
                <h3>5. Stage & review</h3>
                <label className="ops-check">
                  <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  I reviewed the candidate comparison and warnings.
                </label>
                {candidate ? (
                  <p role="status">
                    Staged candidate: <strong>{candidate}</strong>
                  </p>
                ) : (
                  <button
                    className="button secondary"
                    disabled={busy || !ack}
                    onClick={() =>
                      void run(async () => {
                        const result = await opsRequest<{ dataset_id: string }>(
                          `batches/${batch}/stage`,
                          csrf,
                          'POST',
                          { review_reason: reason, review_acknowledged: ack },
                        )
                        setCandidate(result.dataset_id)
                        setNotice('Candidate staged. The active dataset has not changed.')
                        setHealth(await opsRequest<OpsHealth>('health', csrf))
                      })
                    }
                  >
                    Stage reviewed candidate
                  </button>
                )}
                {candidate && (
                  <>
                    <h3>6. Explicit publication</h3>
                    <button
                      className="button primary"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          setPreview(
                            await opsRequest<Preview>(`batches/${batch}/preview`, csrf, 'POST'),
                          )
                          setAck(false)
                          setConfirm(true)
                        })
                      }
                    >
                      Review publication
                    </button>
                  </>
                )}
              </div>
            )}
          </section>
        )}
        {tab === 'history' && (
          <section className="ops-section">
            <h2>Audited import history</h2>
            <p>
              Sanitized results and aggregate findings. Source HTML and event names are never
              displayed.
            </p>
            {health?.history.map((run) => (
              <div className="ops-card" key={run.run_id}>
                <button
                  className="text-button"
                  onClick={() => setSelection(selection === run.run_id ? '' : run.run_id)}
                  aria-expanded={selection === run.run_id}
                >
                  {friendly(run.started_at)} · {run.status} ·{' '}
                  {run.published_at ? 'published' : run.dataset_id ? 'staged' : 'not published'}
                </button>
                {selection === run.run_id && (
                  <dl className="ops-details">
                    {[
                      ['Run', run.run_id],
                      ['Dataset', run.dataset_id ?? 'None'],
                      ['Error', run.error_code ?? 'None'],
                      ['Format', String(run.counts.source_format ?? 'unknown / legacy')],
                      [
                        'Review reason',
                        String(
                          run.counts.review_reason ??
                            run.counts.publication_review_reason ??
                            'None',
                        ),
                      ],
                      [
                        'Findings',
                        JSON.stringify(
                          run.counts.anomalies ?? run.counts.publication_anomalies ?? [],
                        ),
                      ],
                      ['Dates', JSON.stringify(run.counts.dates ?? [])],
                      ['Rooms', String(run.counts.rooms ?? 'Unknown')],
                      ['Bookings', String(run.counts.occurrences ?? 'Unknown')],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <dt>{label}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            ))}
          </section>
        )}
        <ModalOverlay isOpen={confirm} onOpenChange={setConfirm} className="ops-overlay">
          <Modal className="ops-modal">
            <Dialog aria-label="Confirm dataset publication">
              <Heading slot="title">Publish this candidate?</Heading>
              <p>
                This changes the active dataset atomically. Confirm the identifier and current
                comparison before proceeding.
              </p>
              <strong className="ops-id">{candidate}</strong>
              <p>
                Dates: {preview?.summary.dates[0]} through {preview?.summary.dates[6]}
              </p>
              <p>Replacing: {preview?.comparison.baseline_dataset_id ?? 'No active dataset'}</p>
              <p>
                {preview?.summary.rooms} rooms · {preview?.summary.occurrences} bookings
              </p>
              <p>
                {preview?.comparison.added_intervals} added /{' '}
                {preview?.comparison.removed_intervals} removed intervals;{' '}
                {preview?.comparison.capacity_changes.length} capacity changes.
              </p>
              {preview?.comparison.warnings.map((w) => (
                <p className="notice warning" key={w}>
                  {w.replaceAll('_', ' ')}
                </p>
              ))}
              <label className="ops-check">
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I
                reviewed this publication identifier, baseline, and warnings.
              </label>
              <div className="ops-actions">
                <button
                  className="button primary"
                  disabled={busy || !ack}
                  onClick={() =>
                    void run(async () => {
                      const result = await opsRequest<{ health: OpsHealth }>(
                        `batches/${batch}/publish`,
                        csrf,
                        'POST',
                        {
                          confirm_dataset_id: candidate,
                          baseline_dataset_id: preview!.comparison.baseline_dataset_id,
                          review_reason: reason,
                          review_acknowledged: ack,
                        },
                      )
                      setHealth(result.health)
                      setConfirm(false)
                      setNotice(`Publication verified: ${result.health.active?.dataset_id}`)
                      setTab('health')
                    })
                  }
                >
                  Confirm publish dataset
                </button>
                <button className="button secondary" onClick={() => setConfirm(false)}>
                  Cancel
                </button>
              </div>
            </Dialog>
          </Modal>
        </ModalOverlay>
      </main>
      <footer className="ops-footer">
        Private operator service · localhost only · publication does not authorize public
        republication.
      </footer>
    </div>
  )
}
