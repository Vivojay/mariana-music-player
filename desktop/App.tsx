import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { TerminalSurface } from './TerminalSurface'
import { themes, type ThemeName } from './themes'
import type { BackendEvent, UpdateState } from './shared'

const TIMER_PRESETS = [15, 30, 45, 60, 90]

function sendCommand(command: string) {
  window.mariana.terminal.write(`${command}\r`)
}

function formatRemaining(value: unknown): string {
  const total = Math.max(0, Math.round(Number(value) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return [hours, minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':')
}

export default function App() {
  const [themeName, setThemeName] = useState<ThemeName>(() => (localStorage.getItem('mariana.theme') as ThemeName) || 'aurora')
  const [fontSize, setFontSize] = useState(() => Number(localStorage.getItem('mariana.fontSize') || 14))
  const [reducedMotion, setReducedMotion] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [timerOpen, setTimerOpen] = useState(false)
  const [customTimer, setCustomTimer] = useState('30m')
  const [timerAction, setTimerAction] = useState<'pause' | 'stop'>('pause')
  const [timerStatus, setTimerStatus] = useState<Record<string, unknown>>({ active: false })
  const [search, setSearch] = useState('')
  const [update, setUpdate] = useState<UpdateState>({ state: 'idle' })
  const [backendState, setBackendState] = useState('starting')
  const theme = themes[themeName] ?? themes.aurora
  const style = useMemo(() => ({
    '--app-bg': theme.chrome.background,
    '--panel': theme.chrome.panel,
    '--border': theme.chrome.border,
    '--accent': theme.chrome.accent,
    '--text': theme.chrome.text,
    '--muted': theme.chrome.muted,
    '--glow': theme.chrome.glow,
  }) as CSSProperties, [theme])

  useEffect(() => {
    localStorage.setItem('mariana.theme', themeName)
    localStorage.setItem('mariana.fontSize', String(fontSize))
  }, [themeName, fontSize])

  useEffect(() => {
    void window.mariana.backend.snapshot().then((snapshot) => {
      if (snapshot.ready) setBackendState('ready')
      setTimerStatus((current) => ({ ...current, active: snapshot.sleepActive }))
    })
    const backend = window.mariana.backend.onEvent((event: BackendEvent) => {
      if (event.event === 'ready') setBackendState('ready')
      if (event.event === 'fatal-error') setBackendState('error')
      if (event.event === 'sleep') setTimerStatus(event.payload)
    })
    const updater = window.mariana.updates.onState(setUpdate)
    const exited = window.mariana.terminal.onExit(() => setBackendState('stopped'))
    const shortcut = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'p') {
        event.preventDefault()
        setTimerOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', shortcut)
    return () => { backend(); updater(); exited(); window.removeEventListener('keydown', shortcut) }
  }, [])

  const startTimer = (duration: string) => {
    sendCommand(`sleep ${duration} ${timerAction}`)
    setTimerOpen(false)
  }

  return (
    <main className={`app theme-${themeName}`} style={style}>
      <header className="titlebar">
        <div className="brand" aria-label="Mariana">
          <span className="brand-mark">M</span>
          <span>mariana</span>
          <span className={`backend-dot ${backendState}`} title={`Backend: ${backendState}`} />
        </div>
        <div className="title-actions">
          <label className="search-box">
            <span>⌕</span>
            <input
              aria-label="Search terminal"
              placeholder="Find output"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                window.dispatchEvent(new CustomEvent('mariana-search', { detail: event.target.value }))
              }}
            />
          </label>
          <select aria-label="Terminal theme" value={themeName} onChange={(event) => setThemeName(event.target.value as ThemeName)}>
            {Object.entries(themes).map(([id, value]) => <option key={id} value={id}>{value.name}</option>)}
          </select>
          <button title="Decrease font" onClick={() => setFontSize((value) => Math.max(10, value - 1))}>A−</button>
          <button title="Increase font" onClick={() => setFontSize((value) => Math.min(24, value + 1))}>A+</button>
          <button className={timerStatus.active ? 'active' : ''} onClick={() => setTimerOpen((open) => !open)}>
            ◷ {timerStatus.active ? formatRemaining(timerStatus.remaining_seconds) : 'Sleep'}
          </button>
          <button title="Restart Mariana session" onClick={() => void window.mariana.terminal.restart()}>↻</button>
        </div>
      </header>

      <section className="terminal-frame">
        <div className="terminal-lights" aria-hidden="true"><i /><i /><i /></div>
        <TerminalSurface theme={theme} fontSize={fontSize} reducedMotion={reducedMotion} />
      </section>

      <footer className="statusbar">
        <span><b>PTY</b> {backendState}</span>
        <span>{window.mariana.platform}</span>
        <button onClick={() => setReducedMotion((value) => !value)}>{reducedMotion ? 'motion off' : 'motion on'}</button>
        <span className="status-grow" />
        {update.state === 'downloaded' ? (
          <button className="update-ready" disabled={!update.safeToInstall} onClick={() => void window.mariana.updates.install()}>
            {update.safeToInstall ? `Install ${update.version}` : 'Update ready when idle'}
          </button>
        ) : (
          <button onClick={() => void window.mariana.updates.check()}>
            {update.state === 'downloading' ? `Updating ${Math.round(update.percent || 0)}%` : `Update: ${update.state}`}
          </button>
        )}
      </footer>

      {timerOpen && (
        <aside className="timer-popover" aria-label="Sleep timer">
          <div className="popover-heading"><strong>Sleep timer</strong><button onClick={() => setTimerOpen(false)}>×</button></div>
          <p>Fade through the final 10 minutes, then {timerAction}.</p>
          <div className="preset-grid">
            {TIMER_PRESETS.map((minutes) => <button key={minutes} onClick={() => startTimer(`${minutes}m`)}>{minutes} min</button>)}
          </div>
          <div className="timer-custom">
            <input aria-label="Custom timer duration" value={customTimer} onChange={(event) => setCustomTimer(event.target.value)} />
            <select aria-label="Timer action" value={timerAction} onChange={(event) => setTimerAction(event.target.value as 'pause' | 'stop')}>
              <option value="pause">Pause</option><option value="stop">Stop</option>
            </select>
            <button className="primary" onClick={() => startTimer(customTimer)}>Start</button>
          </div>
          <button className="cancel-timer" onClick={() => { sendCommand('sleep cancel'); setTimerOpen(false) }}>Cancel active timer</button>
        </aside>
      )}
    </main>
  )
}
