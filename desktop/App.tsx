import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { PlaybackStatusBar } from './PlaybackStatusBar'
import { TerminalSurface } from './TerminalSurface'
import { themes, type ThemeName } from './themes'
import { formatChapterLabel, trimDisplayCells, type BackendEvent, type PlaybackStatus, type UpdateState } from './shared'

const TIMER_PRESETS = [15, 30, 45, 60, 90]

type MediaView = 'queue' | 'playlists' | 'albums' | 'downloads'

type QueueNode = {
  type: 'group' | 'item'
  id: string
  path: string
  name?: string
  title?: string
  artist?: string
  strategy?: string
  atomic?: boolean
  active?: boolean
  children?: QueueNode[]
}

type PlaylistSummary = {
  id: string
  name: string
  description?: string
  revision: number
  tracks: number
}

type AlbumSummary = {
  id: string
  title: string
  artist?: string
  date?: string
  country?: string
  edition?: string
  tracks?: Array<{ position: string; title: string; artist?: string; status: string }>
}

type DownloadSummary = {
  job_id: string
  kind: string
  state: string
  completed_items: number
  total_items: number
  error?: string
}

function quoteCommand(value: string): string {
  return `"${value.replaceAll('"', '""')}"`
}

function QueueTree({ nodes }: { nodes: QueueNode[] }) {
  if (!nodes.length) return <p className="empty-state">The queue is empty.</p>
  return (
    <ol className="queue-tree">
      {nodes.map((node) => (
        <li key={node.id} className={node.active ? 'active' : ''}>
          <span className={`queue-node ${node.type}`}>
            <code>{node.path}</code>
            <strong>{node.type === 'group' ? node.name : node.title}</strong>
            {node.artist && <small>{node.artist}</small>}
            {node.type === 'group' && <small>{node.strategy}{node.atomic ? ' / atomic' : ''}</small>}
          </span>
          {node.children && <QueueTree nodes={node.children} />}
        </li>
      ))}
    </ol>
  )
}

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
  const [themeName, setThemeName] = useState<ThemeName>(() => {
    const stored = localStorage.getItem('mariana.theme')
    return stored && stored in themes ? stored as ThemeName : 'aurora'
  })
  const [fontSize, setFontSize] = useState(() => {
    const stored = Number(localStorage.getItem('mariana.fontSize') || 14)
    return Number.isFinite(stored) ? Math.max(10, Math.min(24, stored)) : 14
  })
  const [reducedMotion, setReducedMotion] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [timerOpen, setTimerOpen] = useState(false)
  const [customTimer, setCustomTimer] = useState('30m')
  const [timerAction, setTimerAction] = useState<'pause' | 'stop'>('pause')
  const [timerStatus, setTimerStatus] = useState<Record<string, unknown>>({ active: false })
  const [search, setSearch] = useState('')
  const [tabs, setTabs] = useState([{ id: 1, title: 'View 1' }])
  const [activeTab, setActiveTab] = useState(1)
  const tabsRef = useRef(tabs)
  const activeTabRef = useRef(activeTab)
  const [update, setUpdate] = useState<UpdateState>({ state: 'idle' })
  const [backendState, setBackendState] = useState('starting')
  const [backendDiagnostic, setBackendDiagnostic] = useState<string | null>(null)
  const [desktopNotice, setDesktopNotice] = useState<string | null>(null)
  const [broadcastStatus, setBroadcastStatus] = useState<Record<string, unknown>>({ state: 'idle' })
  const [loudnessStatus, setLoudnessStatus] = useState<Record<string, unknown>>({ replaygain_db: 0, live_leveling: false })
  const [playbackStatus, setPlaybackStatus] = useState<PlaybackStatus | null>(null)
  const playbackStatusRef = useRef<PlaybackStatus | null>(null)
  const favoritePendingRef = useRef(false)
  const favoriteRequestEpoch = useRef(0)
  const [favoritePending, setFavoritePending] = useState(false)
  const [favoriteError, setFavoriteError] = useState<string | null>(null)
  const [stationStatus, setStationStatus] = useState<Record<string, unknown>>({ state: 'stopped', next: [] })
  const [stationOpen, setStationOpen] = useState(false)
  const [mediaOpen, setMediaOpen] = useState(false)
  const [mediaView, setMediaView] = useState<MediaView>('queue')
  const [queueTree, setQueueTree] = useState<QueueNode[]>([])
  const [queueCount, setQueueCount] = useState(0)
  const [playlists, setPlaylists] = useState<PlaylistSummary[]>([])
  const [albumResults, setAlbumResults] = useState<AlbumSummary[]>([])
  const [selectedAlbum, setSelectedAlbum] = useState<AlbumSummary | undefined>()
  const [albumQuery, setAlbumQuery] = useState('')
  const [downloads, setDownloads] = useState<DownloadSummary[]>([])
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
    tabsRef.current = tabs
    activeTabRef.current = activeTab
  }, [tabs, activeTab])

  useEffect(() => {
    let playbackEventReceived = false
    const receivePlaybackStatus = (next: PlaybackStatus | null) => {
      if (playbackStatusRef.current?.media_id !== next?.media_id) {
        favoriteRequestEpoch.current += 1
        favoritePendingRef.current = false
        setFavoritePending(false)
      }
      playbackStatusRef.current = next
      setFavoriteError(null)
      setPlaybackStatus(next)
    }
    void window.mariana.backend.snapshot().then((snapshot) => {
      if (snapshot.ready) {
        setBackendState('ready')
        setBackendDiagnostic(null)
      } else if (snapshot.diagnostic) {
        setBackendState('error')
        setBackendDiagnostic(snapshot.diagnostic)
      }
      setTimerStatus((current) => ({ ...current, active: snapshot.sleepActive }))
      setDesktopNotice(snapshot.desktopNotice)
      if (!playbackEventReceived) receivePlaybackStatus(snapshot.playback)
    })
    const backend = window.mariana.backend.onEvent((event: BackendEvent) => {
      if (event.event === 'starting') {
        playbackEventReceived = true
        setBackendState('starting')
        setBackendDiagnostic(null)
        receivePlaybackStatus(null)
      }
      if (event.event === 'ready') {
        setBackendState('ready')
        setBackendDiagnostic(null)
        const name = String(event.payload.theme || '')
        if (name in themes) setThemeName(name as ThemeName)
      }
      if (event.event === 'fatal-error') {
        setBackendState('error')
        setBackendDiagnostic(
          event.payload.message === 'Backend control channel did not become ready'
            ? event.payload.message
            : 'Backend reported a startup error',
        )
      }
      if (event.event === 'sleep') setTimerStatus(event.payload)
      if (event.event === 'broadcast') setBroadcastStatus(event.payload)
      if (event.event === 'loudness') setLoudnessStatus(event.payload)
      if (event.event === 'playback') {
        playbackEventReceived = true
        receivePlaybackStatus(event.payload)
      }
      if (event.event === 'station') setStationStatus(event.payload)
      if (event.event === 'queue') {
        setQueueTree(Array.isArray(event.payload.tree) ? event.payload.tree as QueueNode[] : [])
        setQueueCount(Number(event.payload.count || 0))
      }
      if (event.event === 'playlist') {
        setPlaylists(Array.isArray(event.payload.playlists) ? event.payload.playlists as PlaylistSummary[] : [])
      }
      if (event.event === 'album') {
        if (event.payload.view === 'search') {
          setAlbumResults(Array.isArray(event.payload.results) ? event.payload.results as AlbumSummary[] : [])
          setSelectedAlbum(undefined)
        } else if (event.payload.album && typeof event.payload.album === 'object') {
          setSelectedAlbum(event.payload.album as AlbumSummary)
        }
      }
      if (event.event === 'download') {
        if (Array.isArray(event.payload.jobs)) {
          setDownloads(event.payload.jobs as DownloadSummary[])
        } else if (event.payload.job_id) {
          const job = event.payload as DownloadSummary
          setDownloads((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)])
        }
      }
      if (event.event === 'theme') {
        const name = String(event.payload.name || '')
        if (name in themes) setThemeName(name as ThemeName)
      }
      if (event.event === 'desktop-notice') {
        setDesktopNotice(
          event.payload.message === 'System tray is unavailable; the close button will quit Mariana'
            ? event.payload.message
            : 'Desktop integration is unavailable',
        )
      }
    })
    const updater = window.mariana.updates.onState(setUpdate)
    const exited = window.mariana.terminal.onExit((event) => {
      if (!event.intentional) {
        setBackendState('stopped')
        setBackendDiagnostic('Backend process stopped')
        return
      }
      const currentTabs = tabsRef.current
      if (currentTabs.length === 1) {
        void window.mariana.app.close()
        return
      }
      const exitingId = activeTabRef.current
      const index = currentTabs.findIndex((tab) => tab.id === exitingId)
      const remaining = currentTabs.filter((tab) => tab.id !== exitingId)
      const nextActive = remaining[Math.max(0, index - 1)].id
      tabsRef.current = remaining
      activeTabRef.current = nextActive
      setTabs(remaining)
      setActiveTab(nextActive)
      setBackendState('starting')
      setBackendDiagnostic(null)
      void window.mariana.terminal.restart()
    })
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

  const toggleFavorite = async () => {
    const mediaId = playbackStatusRef.current?.media_id
    if (!mediaId || favoritePendingRef.current) return
    favoritePendingRef.current = true
    const epoch = favoriteRequestEpoch.current
    setFavoritePending(true)
    setFavoriteError(null)
    let result
    try {
      result = await window.mariana.backend.toggleFavorite(mediaId)
    } catch {
      result = { ok: false, error: 'Favourite update failed' }
    }
    if (epoch !== favoriteRequestEpoch.current) return
    favoritePendingRef.current = false
    setFavoritePending(false)
    if (!result.ok) setFavoriteError(result.error || 'Favourite update failed')
  }

  const requestSearch = (direction: 'incremental' | 'next' | 'previous', query = search) => {
    window.dispatchEvent(new CustomEvent('mariana-search', { detail: { query, direction, tabId: activeTab } }))
  }

  const addTab = () => {
    const id = Math.max(0, ...tabs.map((tab) => tab.id)) + 1
    setTabs((current) => [...current, { id, title: `View ${id}` }])
    setActiveTab(id)
  }

  const closeTab = (id: number) => {
    if (tabs.length === 1) return
    const index = tabs.findIndex((tab) => tab.id === id)
    const remaining = tabs.filter((tab) => tab.id !== id)
    setTabs(remaining)
    if (activeTab === id) setActiveTab(remaining[Math.max(0, index - 1)].id)
  }

  const chapterLabel = formatChapterLabel(playbackStatus?.chapter ?? null)
  const stationTracks = Array.isArray(stationStatus.next)
    ? stationStatus.next as Array<{ id?: string; title?: string; artist?: string; reasons?: string[] }>
    : []
  const activeDownloads = downloads.filter((job) => ['queued', 'running', 'paused'].includes(job.state)).length

  return (
    <main className={`app platform-${window.mariana.platform} theme-${themeName}`} style={style}>
      <header className="titlebar">
        <div className="brand" aria-label="Mariana">
          <span className="brand-mark">M</span><span>mariana</span>
          <span className={`backend-dot ${backendState}`} title={`Backend: ${backendState}`} />
        </div>
        <div className="title-actions">
          <div className="search-box">
            <span aria-hidden="true">⌕</span>
            <input
              aria-label="Search terminal"
              placeholder="Find output"
              value={search}
              onChange={(event) => { setSearch(event.target.value); requestSearch('incremental', event.target.value) }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') requestSearch(event.shiftKey ? 'previous' : 'next')
                if (event.key === 'Escape') { setSearch(''); requestSearch('incremental', '') }
              }}
            />
            <button title="Find previous" aria-label="Find previous" onClick={() => requestSearch('previous')}>↑</button>
            <button title="Find next" aria-label="Find next" onClick={() => requestSearch('next')}>↓</button>
          </div>
          <select aria-label="Terminal theme" value={themeName} onChange={(event) => {
            const value = event.target.value as ThemeName
            setThemeName(value)
            sendCommand(`theme ${value}`)
          }}>
            {Object.entries(themes).map(([id, value]) => <option key={id} value={id}>{value.name}</option>)}
          </select>
          <button title="Decrease font" onClick={() => setFontSize((value) => Math.max(10, value - 1))}>A−</button>
          <button title="Increase font" onClick={() => setFontSize((value) => Math.min(24, value + 1))}>A+</button>
          <button className={timerStatus.active ? 'active' : ''} onClick={() => setTimerOpen((open) => !open)}>
            ◷ {timerStatus.active ? formatRemaining(timerStatus.remaining_seconds) : 'Sleep'}
          </button>
          <button className={mediaOpen ? 'active' : ''} aria-label="Open media workspace" onClick={() => setMediaOpen((open) => !open)}>Media</button>
          <button title="Restart Mariana session" onClick={() => void window.mariana.terminal.restart()}>↻</button>
        </div>
      </header>

      <nav className="tabbar" aria-label="Terminal views">
        {tabs.map((tab) => (
          <div key={tab.id} className={`terminal-tab ${activeTab === tab.id ? 'active' : ''}`}>
            <button role="tab" aria-selected={activeTab === tab.id} onClick={() => setActiveTab(tab.id)}>{tab.title}</button>
            {tabs.length > 1 && <button className="tab-close" aria-label={`Close ${tab.title}`} onClick={() => closeTab(tab.id)}>×</button>}
          </div>
        ))}
        <button className="tab-add" aria-label="New terminal view" title="New terminal view" onClick={addTab}>+</button>
        <span>Shared Mariana session</span>
      </nav>

      <section className="terminal-frame">
        <div className="terminal-lights" aria-hidden="true"><i /><i /><i /></div>
        {tabs.map((tab) => (
          <div key={tab.id} className="terminal-pane" hidden={activeTab !== tab.id}>
            <TerminalSurface theme={theme} fontSize={fontSize} reducedMotion={reducedMotion} tabId={tab.id} />
          </div>
        ))}
      </section>

      <footer className="statusbar">
        <PlaybackStatusBar
          status={playbackStatus}
          unavailableReason={backendDiagnostic}
          favoritePending={favoritePending}
          favoriteError={favoriteError}
          onToggleFavorite={() => void toggleFavorite()}
        />
        <div className="statusbar-operations" aria-label="Desktop operational status">
          <span><b>PTY</b> {backendState}</span><span>{window.mariana.platform}</span>
          {desktopNotice && <span role="status" title={desktopNotice}>{desktopNotice}</span>}
          <span title="Program loudness normalization"><b>RG</b> {Number(loudnessStatus.replaygain_db || 0).toFixed(1)} dB{loudnessStatus.live_leveling ? ' · live' : ''}</span>
          <span title={String(broadcastStatus.error || 'Icecast source status')}><b>CAST</b> {String(broadcastStatus.state || 'idle')}{broadcastStatus.codec ? ` · ${String(broadcastStatus.codec)}` : ''}{broadcastStatus.reconnects ? ` · ↻${String(broadcastStatus.reconnects)}` : ''}</span>
          <button
            className={String(stationStatus.state) === 'ready' ? 'active' : ''}
            title="Open the next ten station tracks"
            aria-label="Station recommendations"
            onClick={() => setStationOpen((open) => !open)}
          >
            <b>STN</b> {String(stationStatus.state || 'stopped')} {Number(stationStatus.ready_ahead || 0)}/10
          </button>
          <button aria-label="Open queue tree" onClick={() => { setMediaView('queue'); setMediaOpen(true) }}>
            <b>Q</b> {queueCount}
          </button>
          {activeDownloads > 0 && (
            <button className="active" aria-label="Open downloads" onClick={() => { setMediaView('downloads'); setMediaOpen(true) }}>
              <b>DL</b> {activeDownloads}
            </button>
          )}
          {chapterLabel && (
            <span className="chapter-status" title={chapterLabel}>
              {trimDisplayCells(chapterLabel, 64)}
            </span>
          )}
          <button onClick={() => setReducedMotion((value) => !value)}>{reducedMotion ? 'motion off' : 'motion on'}</button>
          <span className="status-grow" />
          {update.state === 'downloaded' ? (
            <button className="update-ready" disabled={!update.safeToInstall} onClick={() => void window.mariana.updates.install()}>
              {update.safeToInstall ? `Install ${update.version}` : 'Update ready when idle'}
            </button>
          ) : (
            <button onClick={() => void window.mariana.updates.check()}>{update.state === 'downloading' ? `Updating ${Math.round(update.percent || 0)}%` : `Update: ${update.state}`}</button>
          )}
        </div>
      </footer>

      {timerOpen && (
        <aside className="timer-popover" aria-label="Sleep timer">
          <div className="popover-heading"><strong>Sleep timer</strong><button onClick={() => setTimerOpen(false)}>×</button></div>
          <p>Fade through the final 10 minutes, then {timerAction}.</p>
          <div className="preset-grid">{TIMER_PRESETS.map((minutes) => <button key={minutes} onClick={() => startTimer(`${minutes}m`)}>{minutes} min</button>)}</div>
          <div className="timer-custom">
            <input aria-label="Custom timer duration" value={customTimer} onChange={(event) => setCustomTimer(event.target.value)} />
            <select aria-label="Timer action" value={timerAction} onChange={(event) => setTimerAction(event.target.value as 'pause' | 'stop')}><option value="pause">Pause</option><option value="stop">Stop</option></select>
            <button className="primary" onClick={() => startTimer(customTimer)}>Start</button>
          </div>
          <button className="cancel-timer" onClick={() => { sendCommand('sleep cancel'); setTimerOpen(false) }}>Cancel active timer</button>
        </aside>
      )}
      {stationOpen && (
        <aside className="station-popover" aria-label="Station upcoming tracks">
          <div className="popover-heading">
            <strong>Station · next {stationTracks.length}</strong>
            <button aria-label="Close station tracks" onClick={() => setStationOpen(false)}>×</button>
          </div>
          <p>
            {String(stationStatus.scope || 'hybrid')} · {String(stationStatus.progress || stationStatus.state || 'stopped')}
          </p>
          <ol>
            {stationTracks.map((track, index) => (
              <li key={track.id || `${track.title}-${index}`}>
                <strong>{track.title || 'Untitled track'}</strong>
                {track.artist && <span>{track.artist}</span>}
                {track.reasons?.length && <small>{track.reasons.join(' · ')}</small>}
              </li>
            ))}
          </ol>
          {!stationTracks.length && <p>No validated recommendations are ready yet.</p>}
        </aside>
      )}
      {mediaOpen && (
        <aside className="media-drawer" aria-label="Queue playlists albums and downloads">
          <div className="popover-heading">
            <strong>Media workspace</strong>
            <button aria-label="Close media workspace" onClick={() => setMediaOpen(false)}>Close</button>
          </div>
          <nav aria-label="Media workspace sections">
            {(['queue', 'playlists', 'albums', 'downloads'] as MediaView[]).map((view) => (
              <button key={view} className={mediaView === view ? 'active' : ''} onClick={() => setMediaView(view)}>
                {view[0].toUpperCase() + view.slice(1)}
              </button>
            ))}
          </nav>
          {mediaView === 'queue' && (
            <section aria-label="Queue tree">
              <div className="drawer-actions">
                <button onClick={() => sendCommand('queue previous')}>Previous</button>
                <button onClick={() => sendCommand('queue next')}>Next</button>
                <button onClick={() => sendCommand('queue undo')}>Undo</button>
                <button onClick={() => sendCommand('queue order shuffle')}>Shuffle</button>
              </div>
              <QueueTree nodes={queueTree} />
            </section>
          )}
          {mediaView === 'playlists' && (
            <section aria-label="Playlists">
              {!playlists.length && <p className="empty-state">No playlists have been created.</p>}
              {playlists.map((playlist) => (
                <article className="media-card" key={playlist.id}>
                  <div><strong>{playlist.name}</strong><small>{playlist.tracks} tracks / revision {playlist.revision}</small></div>
                  <div className="card-actions">
                    <button onClick={() => sendCommand(`playlist play ${quoteCommand(playlist.name)}`)}>Play</button>
                    <button onClick={() => sendCommand(`playlist queue ${quoteCommand(playlist.name)}`)}>Queue</button>
                  </div>
                </article>
              ))}
            </section>
          )}
          {mediaView === 'albums' && (
            <section aria-label="Albums">
              <form className="album-search" onSubmit={(event) => { event.preventDefault(); if (albumQuery.trim()) sendCommand(`album search ${quoteCommand(albumQuery.trim())}`) }}>
                <input aria-label="Search albums" placeholder="Artist or album" value={albumQuery} onChange={(event) => setAlbumQuery(event.target.value)} />
                <button type="submit">Search</button>
              </form>
              {selectedAlbum && (
                <article className="selected-album">
                  <strong>{selectedAlbum.title}</strong><span>{selectedAlbum.artist}</span>
                  <ol>{selectedAlbum.tracks?.map((track) => <li key={track.position}>{track.position} {track.title} <small>{track.status}</small></li>)}</ol>
                </article>
              )}
              {albumResults.map((album) => (
                <article className="media-card" key={album.id}>
                  <div><strong>{album.title}</strong><small>{album.artist || 'Unknown artist'}{album.date ? ` / ${album.date}` : ''}</small></div>
                  <div className="card-actions">
                    <button onClick={() => sendCommand(`album show ${album.id}`)}>Details</button>
                    <button onClick={() => sendCommand(`album play ${album.id}`)}>Play</button>
                    <button onClick={() => sendCommand(`album queue ${album.id}`)}>Queue</button>
                  </div>
                </article>
              ))}
            </section>
          )}
          {mediaView === 'downloads' && (
            <section aria-label="Downloads">
              {!downloads.length && <p className="empty-state">No download jobs.</p>}
              {downloads.map((job) => {
                const overall = job.total_items ? Math.round((job.completed_items / job.total_items) * 100) : 0
                return (
                  <article className="download-card" key={job.job_id}>
                    <div><strong>{job.kind} / {job.state}</strong><code>{job.job_id}</code></div>
                    <progress max="100" value={overall}>{overall}%</progress>
                    <small>{job.completed_items}/{job.total_items} tracks{job.error ? ` / ${job.error}` : ''}</small>
                    <div className="card-actions">
                      {job.state === 'running' && <button onClick={() => sendCommand(`download-ya pause ${job.job_id}`)}>Pause</button>}
                      {job.state === 'paused' && <button onClick={() => sendCommand(`download-ya resume ${job.job_id}`)}>Resume</button>}
                      {['queued', 'running', 'paused'].includes(job.state) && <button onClick={() => sendCommand(`download-ya cancel ${job.job_id}`)}>Cancel</button>}
                    </div>
                  </article>
                )
              })}
            </section>
          )}
        </aside>
      )}
    </main>
  )
}
