import { useCallback, useEffect, useRef, useState } from 'react'
import { Dialog, Heading } from 'react-aria-components/Dialog'
import { Modal, ModalOverlay } from 'react-aria-components/Modal'
import { ManifestBuilder } from './ManifestBuilder.tsx'
import { MultiweekImporter } from './MultiweekImporter.tsx'
import { ThemeControl } from './theme.tsx'
import { opsRequest } from './operator-api.ts'
import type { OpsHealth, Preview } from './operator-api.ts'
import './index.css'
import './App.css'
import './operator.css'

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
  const [batch, setBatch] = useState(''),
    [preview, setPreview] = useState<Preview | null>(null),
    [candidate, setCandidate] = useState('')
  const [reason, setReason] = useState(''),
    [ack, setAck] = useState(false),
    [confirm, setConfirm] = useState(false),
    [selection, setSelection] = useState('')
  const [notice, setNotice] = useState('')
  const task = useRef(false)
  const expire = useCallback(() => {
    setCsrf('')
    setHealth(null)
    setBatch('')
    setPreview(null)
    setCandidate('')
    setReason('')
    setAck(false)
    setConfirm(false)
    setNotice('')
  }, [])
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
      if (e instanceof Error && e.message.includes('authentication_required')) {
        expire()
      }
    } finally {
      task.current = false
      setBusy(false)
    }
  }
  if (!csrf)
    return (
      <div className="ops-login shell">
        <header className="ops-header">
          <strong>Intervella · Private operations</strong>
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
  const findings =
    health?.history
      .filter(
        (run) =>
          run.status === 'failed' ||
          (Array.isArray(run.counts.anomalies) && run.counts.anomalies.length > 0) ||
          (Array.isArray(run.counts.publication_anomalies) &&
            run.counts.publication_anomalies.length > 0),
      )
      .slice(0, 3) ?? []
  return (
    <div className="ops-shell">
      <header className="ops-header">
        <a href="#overview" className="brand">
          Intervella <span className="small">/ operations</span>
        </a>
        <div className="ops-actions">
          <ThemeControl />
          <button
            className="button secondary"
            onClick={() =>
              void run(async () => {
                await opsRequest('logout', csrf, 'POST')
                expire()
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
                <p>Independent active periods, backed by audited imports.</p>
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
            {!!health?.active_periods?.length && <div className="ops-card">
              <h3>All active periods</h3>
              <p>End dates are exclusive. Gaps between periods have no published schedule.</p>
              {health.active_periods.map((period) => <details key={period.dataset_id}>
                <summary>{period.start_date} → {period.end_date} · {period.freshness}</summary>
                <p className="ops-id">{period.dataset_id}</p>
                {period.days.map((day) => <p key={day.date}>{day.date}: captured {friendly(day.fetched_at)}</p>)}
              </details>)}
            </div>}
            <div className="ops-card">
              <h3>Recent import findings</h3>
              {findings.length === 0 ? (
                <p>No findings in the recent recorded imports.</p>
              ) : (
                findings.map((run) => (
                  <p className="notice warning" key={run.run_id}>
                    {friendly(run.started_at)} -{' '}
                    {run.error_code?.replaceAll('_', ' ') ??
                      JSON.stringify(
                        run.counts.anomalies ?? run.counts.publication_anomalies ?? [],
                      )}
                  </p>
                ))
              )}
              <button className="text-button" onClick={() => setTab('history')}>
                View audited history
              </button>
            </div>
          </section>
        )}
        <section className="ops-section" hidden={tab !== 'import'}>
          <div className="ops-section-heading">
            <div>
              <h2>Import a timetable</h2>
              <p>Upload → validate → compare → stage → explicitly publish.</p>
            </div>
          </div>
          <MultiweekImporter csrf={csrf} busy={busy} run={run} onHealth={setHealth} />
          <details className="ops-card"><summary>Existing inventory editor & single seven-day import</summary>
          <ManifestBuilder
            csrf={csrf}
            busy={busy}
            locked={!!candidate}
            run={run}
            onExpired={expire}
            onInvalidate={() => {
              setPreview(null)
              setAck(false)
            }}
            onPrepared={(result) => {
              setBatch(result.batch)
              setPreview(result.preview)
              setReason(result.reason)
              setAck(false)
            }}
            onDiscard={() => {
              setBatch('')
              setCandidate('')
              setPreview(null)
              setAck(false)
            }}
          />
          </details>
          {preview && (
            <div className="ops-card ops-comparison">
              <h3>4. Validation & comparison</h3>
              <p>
                {preview.summary.rooms} rooms · {preview.summary.buildings} buildings ·{' '}
                {preview.summary.occurrences} bookings · {preview.summary.unknown_rooms} rooms with
                unknown coverage
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
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I
                reviewed the candidate comparison and warnings.
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
                This adds or replaces this period atomically. Other active periods are retained. Confirm the identifier and current
                comparison before proceeding.
              </p>
              <strong className="ops-id">{candidate}</strong>
              <p>
                Dates: {preview?.summary.dates[0]} through {preview?.summary.dates[6]}
              </p>
              <p>Replacing: {preview?.comparison.replaced_dataset_id ?? 'No active dataset for these dates'}</p>
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
