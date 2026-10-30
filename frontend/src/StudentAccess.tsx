import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ThemeControl } from './theme.tsx'
import { Button } from './ui.tsx'
import './student-auth.css'

type StudentSession = {
  mode: 'beta' | 'university'
  authenticated: boolean
  csrf?: string
  expires_at?: string
  needs_renewal: boolean
}
const messages: Record<string, string> = {
  invalid_signin: 'Sign-in was not accepted. Check your passcode or request a new email code.',
  rate_limited: 'Too many attempts. Wait 15 minutes before trying again.',
  email_not_eligible: 'This address or account is not approved for access.',
  email_not_verified: 'A verified university email address is required.',
  beta_closed: 'This private beta has ended.',
  csrf_rejected: 'Reload this page and try again.',
}
async function authRequest(path: string, body?: object, csrf?: string) {
  let response: Response
  try {
    response = await fetch(`/auth/${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers:
        body === undefined
          ? {}
          : {
              'Content-Type': 'application/json',
              'X-Student-Request': '1',
              ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
            },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
  } catch {
    throw new Error('Connect to the internet and try again.')
  }
  let data
  try {
    data = await response.json()
  } catch {
    throw new Error('Sign-in service returned an invalid response. Try again shortly.')
  }
  if (!response.ok) {
    const code = data?.error?.code
    throw new Error(
      typeof code === 'string' && Object.hasOwn(messages, code)
        ? messages[code]
        : 'Sign-in is temporarily unavailable. Try again shortly.',
    )
  }
  return data
}
function sessionShape(value: unknown): StudentSession {
  if (!value || typeof value !== 'object') throw new Error('Invalid sign-in response.')
  const data = value as StudentSession
  if (
    !['beta', 'university'].includes(data.mode) ||
    typeof data.authenticated !== 'boolean' ||
    typeof data.needs_renewal !== 'boolean' ||
    ((data.authenticated || data.needs_renewal) &&
      (typeof data.csrf !== 'string' ||
        typeof data.expires_at !== 'string' ||
        !/^[a-f0-9]{64}$/.test(data.csrf) ||
        !/(Z|[+-][0-9]{2}:[0-9]{2})$/.test(data.expires_at) ||
        !Number.isFinite(Date.parse(data.expires_at ?? ''))))
  )
    throw new Error('Invalid sign-in response.')
  if (data.authenticated && Date.parse(data.expires_at!) <= Date.now())
    return { ...data, authenticated: false }
  return data
}
const AuthContext = createContext<{ logout: () => void } | null>(null)
export function StudentSignOut() {
  const auth = useContext(AuthContext)
  return auth ? (
    <Button
      variant="secondary"
      className="student-signout"
      aria-label="Sign out"
      title="Sign out"
      onClick={auth.logout}
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        aria-hidden="true"
      >
        <path d="M10 4H4v16h6M14 8l4 4-4 4M8 12h10" />
      </svg>
      <span>Sign out</span>
    </Button>
  ) : null
}

export function StudentAccess({ children }: { children: ReactNode }) {
  const queries = useQueryClient()
  const [session, setSession] = useState<StudentSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [passcode, setPasscode] = useState('')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(false)
  const generation = useRef(0)
  const advanceGeneration = useCallback(() => ++generation.current, [])
  const logoutIntent = useRef(false)
  const [logoutFailed, setLogoutFailed] = useState(false)
  const clearProtected = useCallback(() => {
    setSession((previous) => (previous ? { ...previous, authenticated: false } : previous))
    void queries.cancelQueries().then(() => queries.clear())
  }, [queries])
  const load = useCallback(async () => {
    if (logoutIntent.current) return
    const current = advanceGeneration()
    try {
      let next = sessionShape(await authRequest('session'))
      if (next.needs_renewal) next = sessionShape(await authRequest('renew', {}, next.csrf))
      if (current !== generation.current || logoutIntent.current) return
      if (!next.authenticated) clearProtected()
      setSession(next)
      setError('')
    } catch (cause) {
      if (current !== generation.current || logoutIntent.current) return
      clearProtected()
      setError(
        cause instanceof Error && cause.message !== 'Failed to fetch'
          ? cause.message
          : 'Connect to the internet to restore your sign-in session.',
      )
    } finally {
      if (current === generation.current) setLoading(false)
    }
  }, [clearProtected, advanceGeneration])
  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0)
    const check = () => {
      if (document.visibilityState === 'visible') void load()
    }
    const expired = () => {
      clearProtected()
      void load()
    }
    const timer = window.setInterval(check, 30_000)
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', check)
    window.addEventListener('intervella:auth-required', expired)
    return () => {
      advanceGeneration()
      clearTimeout(initial)
      clearInterval(timer)
      window.removeEventListener('focus', check)
      document.removeEventListener('visibilitychange', check)
      window.removeEventListener('intervella:auth-required', expired)
    }
  }, [load, clearProtected, advanceGeneration])
  useEffect(() => {
    if (!session?.authenticated || !session.expires_at) return
    const timer = setTimeout(
      () => {
        clearProtected()
        void load()
      },
      Math.max(1, Math.min(2147483647, Date.parse(session.expires_at) - Date.now())),
    )
    return () => clearTimeout(timer)
  }, [session, load, clearProtected])

  const logout = async () => {
    logoutIntent.current = true
    advanceGeneration()
    clearProtected()
    setLoading(false)
    setBusy(true)
    try {
      await authRequest('logout', {}, session?.csrf)
      setLogoutFailed(false)
      setError('')
    } catch {
      setLogoutFailed(true)
      setError('Sign-out could not be confirmed. Reconnect and retry sign-out.')
    } finally {
      setBusy(false)
    }
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (session?.mode === 'university' && !sent) {
        await authRequest('university/code', { email })
        setSent(true)
      } else {
        await authRequest(
          session?.mode === 'university' ? 'university/verify' : 'beta',
          session?.mode === 'university' ? { email, code } : { passcode },
        )
        logoutIntent.current = false
        setLogoutFailed(false)
        await load()
      }
    } catch (cause) {
      setError(
        cause instanceof Error && cause.message !== 'Failed to fetch'
          ? cause.message
          : 'Connect to the internet and try again.',
      )
    } finally {
      setPasscode('')
      setCode('')
      setBusy(false)
    }
  }
  if (session?.authenticated && session.expires_at)
    return (
      <AuthContext.Provider value={{ logout: () => void logout() }}>
        {children}
      </AuthContext.Provider>
    )
  return (
    <div className="auth-page">
      <a className="skip-link" href="#student-login">
        Skip to sign in
      </a>
      <header className="site-header shell">
        <a className="brand" href="/">
          <img className="brand-mark" src="/assets/intervella.svg" alt="" width="40" height="40" />
          Intervella
        </a>
        <ThemeControl />
      </header>
      <main id="student-login" className="auth-main" tabIndex={-1}>
        <section className="auth-card" aria-labelledby="auth-title">
          <span className="eyebrow">Your space between classes</span>
          <h1 id="auth-title">
            {session
              ? session.mode === 'university'
                ? 'University sign-in'
                : 'Welcome to the private beta'
              : 'Sign in to Intervella'}
          </h1>
          <p>
            {session?.mode === 'university'
              ? 'Use an approved university email address. We’ll send you a one-time code.'
              : 'Intervella is being tested with a small group. Enter your invitation passcode to continue.'}
          </p>
          {loading ? (
            <p role="status">Restoring your session…</p>
          ) : session ? (
            <form onSubmit={(event) => void submit(event)} aria-label="Student sign in">
              {session.mode === 'beta' ? (
                <label>
                  Beta passcode
                  <input
                    type="password"
                    autoComplete="current-password"
                    required
                    maxLength={256}
                    value={passcode}
                    onChange={(event) => setPasscode(event.target.value)}
                    aria-describedby="auth-error"
                  />
                </label>
              ) : (
                <>
                  <label>
                    University email
                    <input
                      type="email"
                      autoComplete="email"
                      required
                      maxLength={254}
                      value={email}
                      readOnly={sent}
                      onChange={(event) => setEmail(event.target.value)}
                    />
                  </label>
                  {sent && (
                    <>
                      <p role="status">Check your inbox for your one-time code.</p>
                      <label>
                        Email code
                        <input
                          type="text"
                          inputMode="numeric"
                          autoComplete="one-time-code"
                          pattern="[0-9]{6,10}"
                          required
                          maxLength={10}
                          value={code}
                          onChange={(event) => setCode(event.target.value)}
                        />
                      </label>
                      <Button
                        variant="secondary"
                        disabled={busy}
                        onClick={() => {
                          setSent(false)
                          setCode('')
                        }}
                      >
                        Use another address
                      </Button>
                    </>
                  )}
                </>
              )}
              <Button type="submit" disabled={busy}>
                {busy
                  ? 'Please wait…'
                  : session.mode === 'university' && !sent
                    ? 'Send email code'
                    : 'Sign in'}
              </Button>
            </form>
          ) : (
            <Button variant="secondary" onClick={() => void load()}>
              Retry sign-in service
            </Button>
          )}
          <p id="auth-error" className="form-error" role={error ? 'alert' : undefined}>
            {error}
          </p>
          {logoutFailed && (
            <Button variant="secondary" disabled={busy} onClick={() => void logout()}>
              Retry sign-out
            </Button>
          )}
          <p className="small">
            {session?.mode === 'university'
              ? 'Email verification does not establish current student enrolment. Access follows the configured eligibility policy.'
              : 'Keep your shared passcode private. Access expires automatically at the beta closing time.'}
          </p>
        </section>
      </main>
      <footer className="site-footer shell">
        Independent student project. Not an official University of Toronto service. Timetable
        coverage does not guarantee room access or vacancy.
      </footer>
    </div>
  )
}
