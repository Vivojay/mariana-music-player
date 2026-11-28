import { exploreCommandSuggestions } from './commandExplorer'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  isCommandSuggestionProjectionCurrent,
  type CommandSuggestionProjection,
} from './commandCatalog'
import { acceptPlaybackStatusEvent, projectPlaybackStatus } from './playbackProjection'
import { projectPlaybackHotspots } from './playbackHotspots'
import { PlaybackStatusBar } from './PlaybackStatusBar'
import { PlaybackTimeline } from './PlaybackTimeline'
import { MediaStudio } from './MediaStudio'
import { HomepagePanel } from './HomepagePanel'
import { projectLocalVideo, type LocalVideoStatus } from './localVideo'
import { projectHomepage } from './discoveryProjection'
import { StrudelPanel } from './StrudelPanel'
import { projectStrudelProjection, type StrudelProjection } from './strudelProjects'
import { ListeningControls } from './ListeningControls'
import { validateSeekIntent } from './playbackSeek'
import { readChapterSnapping, SNAP_CHAPTERS_KEY } from './seekPreferences'
import { TerminalSurface } from './TerminalSurface'
import { isThemeName, readSelection, resolveTheme, selection, themes, themeStyle, type ThemeName } from './themes'
import { AccountConnections } from './AccountConnections'
import { PaletteEditor } from './PaletteEditor'
import {
  formatChapterLabel,
  trimDisplayCells,
  type BackendEvent,
  type CommandCatalogResult,
  type CommandCatalogSnapshot,
  type HomepageProjection,
  type PlaybackHotspots,
  type PlaybackStatus,
  type UpdateState,
} from './shared'

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
  const [palette, setPalette] = useState(readSelection)
  const themeName = palette.name
  const [fontSize, setFontSize] = useState(() => {
    const stored = Number(localStorage.getItem('mariana.fontSize') || 14)
    return Number.isFinite(stored) ? Math.max(10, Math.min(24, stored)) : 14
  })
  const [reducedMotion, setReducedMotion] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [homepage, setHomepage] = useState<HomepageProjection | null>(null)
  const [homeVideo, setHomeVideo] = useState<LocalVideoStatus | null>(null)
  const [homeOpen, setHomeOpen] = useState(false)
  const [homeSettingsOpen, setHomeSettingsOpen] = useState(false)
  const [homeRefreshing, setHomeRefreshing] = useState(false)
  const [homeConfiguring, setHomeConfiguring] = useState(false)
  const [homeError, setHomeError] = useState<string | null>(null)
  const homeButtonRef = useRef<HTMLButtonElement>(null)
  const [strudel, setStrudel] = useState<StrudelProjection | null>(null)
  const [strudelOpen, setStrudelOpen] = useState(false)
  const [accountsOpen,setAccountsOpen] = useState(false)
  const [timerOpen, setTimerOpen] = useState(false)
  const [customTimer, setCustomTimer] = useState('30m')
  const [timerAction, setTimerAction] = useState<'pause' | 'stop'>('pause')
  const [timerStatus, setTimerStatus] = useState<Record<string, unknown>>({ active: false })
  const [search, setSearch] = useState('')
  const autocompleteGenerationRef = useRef(0)
  const autocompleteRequestRef = useRef({ typedPrefix: '', generation: 0 })
  const autocompleteInitialSelectionRef = useRef<'first' | 'last'>('first')
  const autocompleteCatalogRef = useRef<CommandCatalogSnapshot | null>(null)
  const autocompleteCatalogRequestRef = useRef<Promise<CommandCatalogResult> | null>(null)
  const [autocompleteRequest, setAutocompleteRequest] = useState({ typedPrefix: '', generation: 0 })
  const [autocompleteOpen, setAutocompleteOpen] = useState(false)
  const [autocompletePending, setAutocompletePending] = useState(false)
  const [autocompleteError, setAutocompleteError] = useState(false)
  const [autocompleteProjection, setAutocompleteProjection] = useState<CommandSuggestionProjection | null>(null)
  const [autocompleteActiveIndex, setAutocompleteActiveIndex] = useState(0)
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
  const [hotspots, setHotspots] = useState<PlaybackHotspots | null>(null)
  const [snapChapters, setSnapChapters] = useState(readChapterSnapping)
  const playbackStatusRef = useRef<PlaybackStatus | null>(null)
  const playbackEventTimestampRef = useRef<number | null>(null)
  const favoritePendingRef = useRef(false)
  const favoriteRequestEpoch = useRef(0)
  const [favoritePending, setFavoritePending] = useState(false)
  const [favoriteError, setFavoriteError] = useState<string | null>(null)
  const seekPendingRef = useRef(false)
  const seekRequestEpoch = useRef(0)
  const [seekPending, setSeekPending] = useState(false)
  const [seekError, setSeekError] = useState<string | null>(null)
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
  const theme = useMemo(() => resolveTheme(palette), [palette])
  const style = useMemo(() => themeStyle(theme), [theme])

  useEffect(() => {
    localStorage.setItem('mariana.theme', palette.name)
    localStorage.setItem('mariana.themeColors', JSON.stringify(palette))
  }, [palette])
  useEffect(() => {
    localStorage.setItem('mariana.fontSize', String(fontSize))
  }, [fontSize])
  useEffect(() => {
    const syncSnapping = (event: StorageEvent) => {
      if (event.key === SNAP_CHAPTERS_KEY || event.key === null) setSnapChapters(readChapterSnapping())
    }
    window.addEventListener('storage', syncSnapping)
    return () => window.removeEventListener('storage', syncSnapping)
  }, [])

  useEffect(() => {
    tabsRef.current = tabs
    activeTabRef.current = activeTab
  }, [tabs, activeTab])

  useEffect(() => {
    let strudelEventReceived = false
    let playbackEventReceived = false
    let hotspotsEventReceived = false
    let homepageEventReceived = false
    let homeVideoEventReceived = false
    let homepageInitialized = false
    let active = true
    const receiveHomepage = (value: unknown) => {
      const projected = projectHomepage(value)
      if (!projected) return false
      setHomepage(projected)
      if (projected.open_requested || (!homepageInitialized && projected.show_on_startup)) setHomeOpen(true)
      homepageInitialized = true
      return true
    }
    const receivePlaybackStatus = (next: PlaybackStatus | null): boolean => {
      const projected = next === null ? null : projectPlaybackStatus(next)
      if (next !== null && !projected) return false
      if (playbackStatusRef.current?.media_id !== projected?.media_id) {
        setHotspots(null)
        favoriteRequestEpoch.current += 1
        favoritePendingRef.current = false
        setFavoritePending(false)
        seekRequestEpoch.current += 1
        seekPendingRef.current = false
        setSeekPending(false)
      }
      playbackStatusRef.current = projected
      setFavoriteError(null)
      setSeekError(null)
      setPlaybackStatus(projected)
      return true
    }
    void window.mariana.backend.snapshot().then((snapshot) => {
      if (!active) return
      if (snapshot.ready) {
        setBackendState('ready')
        setBackendDiagnostic(null)
      } else if (snapshot.diagnostic) {
        setBackendState('error')
        setBackendDiagnostic(snapshot.diagnostic)
      }
      setTimerStatus((current) => ({ ...current, active: snapshot.sleepActive }))
      setDesktopNotice(snapshot.desktopNotice)
      if (!strudelEventReceived && snapshot.strudel) setStrudel(snapshot.strudel)
      if (!playbackEventReceived) receivePlaybackStatus(snapshot.playback)
      if (!hotspotsEventReceived) setHotspots(projectPlaybackHotspots(snapshot.hotspots))
      if (!homepageEventReceived) receiveHomepage(snapshot.homepage)
      if (!homeVideoEventReceived) setHomeVideo(projectLocalVideo(snapshot.video))
    })
    const backend = window.mariana.backend.onEvent((event: BackendEvent) => {
      if (event.event === 'starting') {
        homepageEventReceived = true
        homepageInitialized = false
        setHomepage(null)
        setHomeOpen(false)
        setHomeSettingsOpen(false)
        setHomeError(null)
        homeVideoEventReceived = true
        setHomeVideo(null)
        playbackEventReceived = true
        hotspotsEventReceived = true
        setHotspots(null)
        playbackEventTimestampRef.current = null
        setBackendState('starting')
        setBackendDiagnostic(null)
        receivePlaybackStatus(null)
      }
      if (event.event === 'ready') {
        setBackendState('ready')
        setBackendDiagnostic(null)
        const name = String(event.payload.theme || '')
        if (isThemeName(name)) setPalette(selection(name, event.payload.theme_colors))
      }
      if (event.event === 'fatal-error') {
        seekRequestEpoch.current += 1
        seekPendingRef.current = false
        setSeekPending(false)
        setSeekError(null)
        setBackendState('error')
        setBackendDiagnostic(
          event.payload.message === 'Backend control channel did not become ready'
            ? event.payload.message
            : 'Backend reported a startup error',
        )
      }
      if (event.event === 'homepage' && receiveHomepage(event.payload)) homepageEventReceived = true
      if (event.event === 'video') {
        const next = projectLocalVideo(event.payload)
        if (next) {
          homeVideoEventReceived = true
          setHomeVideo((current) => current?.handle && current.handle === next.handle && current.media_id === next.media_id
            ? current : next.state === 'ready' ? next : null)
        }
      }
      if (event.event === 'strudel') {
        const next = projectStrudelProjection(event.payload)
        if (next) {
          strudelEventReceived = true
          setStrudel(next)
          if (next.open_requested) setStrudelOpen(true)
        }
      }
      if (event.event === 'desktop-open') {
        const panel = event.payload.panel
        if (panel === 'queue' || panel === 'playlists' || panel === 'albums' || panel === 'downloads') {
          setMediaView(panel)
          setMediaOpen(true)
        } else if (panel === 'sleep') setTimerOpen(true)
        else if (panel === 'station') setStationOpen(true)
        else if (panel === 'mini') void window.mariana.app.showMiniPlayer()
      }
      if (event.event === 'sleep') setTimerStatus(event.payload)
      if (event.event === 'broadcast') setBroadcastStatus(event.payload)
      if (event.event === 'loudness') setLoudnessStatus(event.payload)
      if (event.event === 'playback') {
        const accepted = acceptPlaybackStatusEvent(
          event.payload,
          event.timestamp,
          playbackEventTimestampRef.current,
        )
        if (accepted && receivePlaybackStatus(accepted.status)) {
          playbackEventTimestampRef.current = accepted.timestamp
          playbackEventReceived = true
        }
      }
      if (event.event === 'hotspots') {
        const next = projectPlaybackHotspots(event.payload)
        if (next?.media_id && next.media_id === playbackStatusRef.current?.media_id) {
          hotspotsEventReceived = true
          setHotspots(next)
        }
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
        if (isThemeName(name)) setPalette(selection(name, event.payload.colors))
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
    return () => { active = false; backend(); updater(); exited(); window.removeEventListener('keydown', shortcut) }
  }, [])

  useEffect(() => {
    if (!autocompleteOpen) return
    const request = autocompleteRequest
    let cancelled = false
    const cachedCatalog = autocompleteCatalogRef.current
    let catalogRequest: Promise<CommandCatalogResult>
    if (cachedCatalog) {
      catalogRequest = Promise.resolve({ ok: true, catalog: cachedCatalog })
    } else {
      catalogRequest = autocompleteCatalogRequestRef.current
        ?? window.mariana.backend.commandCatalog({ includeCompatibility: true })
      autocompleteCatalogRequestRef.current = catalogRequest
      void catalogRequest.then((result) => {
        if (result.ok) autocompleteCatalogRef.current = result.catalog
      }).catch(() => undefined).finally(() => {
        if (autocompleteCatalogRequestRef.current === catalogRequest) {
          autocompleteCatalogRequestRef.current = null
        }
      })
    }
    void catalogRequest.then((result) => {
      if (cancelled) return
      const current = autocompleteRequestRef.current
      if (current.generation !== request.generation || current.typedPrefix !== request.typedPrefix) return
      if (!result.ok) {
        setAutocompleteProjection(null)
        setAutocompletePending(false)
        setAutocompleteError(true)
        return
      }
      const projection = exploreCommandSuggestions(result.catalog, request)
      if (!isCommandSuggestionProjectionCurrent(projection, current.typedPrefix, current.generation)) return
      setAutocompleteProjection(projection)
      setAutocompleteActiveIndex(
        autocompleteInitialSelectionRef.current === 'last'
          ? Math.max(0, projection.suggestions.length - 1)
          : 0,
      )
      setAutocompletePending(false)
    }).catch(() => {
      if (cancelled) return
      const current = autocompleteRequestRef.current
      if (current.generation !== request.generation || current.typedPrefix !== request.typedPrefix) return
      setAutocompleteProjection(null)
      setAutocompletePending(false)
      setAutocompleteError(true)
    })
    return () => { cancelled = true }
  }, [autocompleteOpen, autocompleteRequest])

  const closeHomepage = () => {
    setHomeOpen(false)
    setHomeSettingsOpen(false)
    requestAnimationFrame(() => homeButtonRef.current?.focus())
  }

  const openHomepage = async () => {
    if (homeOpen) { closeHomepage(); return }
    setHomeError(null)
    try {
      const result = await window.mariana.backend.homepageOpen()
      if (!result.ok) setDesktopNotice(result.error || 'Home is unavailable')
    } catch {
      setDesktopNotice('Home is unavailable')
    }
  }

  const refreshHomepage = async () => {
    setHomeError(null)
    setHomeRefreshing(true)
    try {
      const result = await window.mariana.backend.homepageRefresh()
      if (!result.ok) setHomeError(result.error || 'Could not refresh Home')
    } catch {
      setHomeError('Could not refresh Home')
    } finally {
      setHomeRefreshing(false)
    }
  }

  const configureHomepage = async (setting: 'startup' | 'online', enabled: boolean) => {
    setHomeError(null)
    setHomeConfiguring(true)
    try {
      const result = await window.mariana.backend.homepageConfigure(setting, enabled)
      if (!result.ok) setHomeError(result.error || 'Could not update Home settings')
    } catch {
      setHomeError('Could not update Home settings')
    } finally {
      setHomeConfiguring(false)
    }
  }

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

  const seekPlayback = async (targetSeconds: number, mediaId = playbackStatusRef.current?.media_id) => {
    const status = playbackStatusRef.current
    const validation = validateSeekIntent(
      status,
      mediaId,
      targetSeconds,
      backendState === 'ready',
    )
    if (!validation.ok || seekPendingRef.current || !status?.media_id) return
    seekPendingRef.current = true
    const epoch = seekRequestEpoch.current
    setSeekPending(true)
    setSeekError(null)
    let result
    try {
      result = await window.mariana.backend.seek(status.media_id, validation.targetSeconds)
    } catch {
      result = { ok: false, error: 'Seek failed' }
    }
    if (epoch !== seekRequestEpoch.current) return
    seekPendingRef.current = false
    setSeekPending(false)
    if (!result.ok) setSeekError(result.error || 'Seek failed')
  }

  const requestSearch = (direction: 'incremental' | 'next' | 'previous', query = search) => {
    window.dispatchEvent(new CustomEvent('mariana-search', { detail: { query, direction, tabId: activeTab } }))
  }

  const requestCommandSuggestions = (typedPrefix: string, initialSelection: 'first' | 'last' = 'first') => {
    const request = { typedPrefix, generation: autocompleteGenerationRef.current + 1 }
    autocompleteGenerationRef.current = request.generation
    autocompleteRequestRef.current = request
    autocompleteInitialSelectionRef.current = initialSelection
    setAutocompleteRequest(request)
    setAutocompleteProjection(null)
    setAutocompleteActiveIndex(0)
    setAutocompletePending(true)
    setAutocompleteError(false)
    setAutocompleteOpen(true)
  }

  const closeCommandSuggestions = () => {
    autocompleteGenerationRef.current += 1
    autocompleteRequestRef.current = {
      typedPrefix: autocompleteRequestRef.current.typedPrefix,
      generation: autocompleteGenerationRef.current,
    }
    setAutocompleteOpen(false)
    setAutocompletePending(false)
    setAutocompleteError(false)
    setAutocompleteProjection(null)
    setAutocompleteActiveIndex(0)
  }

  const acceptCommandSuggestion = (
    suggestionKey: string,
    expectedRequest: { typedPrefix: string; generation: number },
  ) => {
    const current = autocompleteRequestRef.current
    const projection = autocompleteProjection
    if (
      !autocompleteOpen
      || !projection
      || current.generation !== expectedRequest.generation
      || current.typedPrefix !== expectedRequest.typedPrefix
      || !isCommandSuggestionProjectionCurrent(projection, current.typedPrefix, current.generation)
    ) return
    const suggestion = projection.suggestions.find((candidate) => candidate.key === suggestionKey)
    if (!suggestion) return

    const accepted = {
      typedPrefix: suggestion.display_label,
      generation: autocompleteGenerationRef.current + 1,
    }
    autocompleteGenerationRef.current = accepted.generation
    autocompleteRequestRef.current = accepted
    setAutocompleteRequest(accepted)
    setAutocompleteOpen(false)
    setAutocompletePending(false)
    setAutocompleteError(false)
    setAutocompleteProjection(null)
    setAutocompleteActiveIndex(0)
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
  const seekEnabled = validateSeekIntent(
    playbackStatus,
    playbackStatus?.media_id,
    playbackStatus?.position_seconds,
    backendState === 'ready',
  ).ok
  const commandSuggestions = autocompleteProjection
    && isCommandSuggestionProjectionCurrent(
      autocompleteProjection,
      autocompleteRequest.typedPrefix,
      autocompleteRequest.generation,
    )
    ? autocompleteProjection.suggestions
    : []
  const activeSuggestionId = autocompleteOpen && commandSuggestions.length
    ? `command-suggestion-${autocompleteRequest.generation}-${autocompleteActiveIndex}`
    : undefined
  const commandSuggestionStatus = (() => {
    if (autocompletePending) return 'Loading command suggestions'
    if (autocompleteError) return 'Command suggestions unavailable'
    if (!commandSuggestions.length) return 'No command suggestions'
    const label = commandSuggestions.length === 1 ? 'suggestion' : 'suggestions'
    return `${commandSuggestions.length} command ${label}. Enter selects without running.`
  })()

  return (
    <main className={`app platform-${window.mariana.platform} theme-${themeName}`} style={style}>
      <header className="titlebar">
        <div className="brand" aria-label="Mariana">
          <span className="brand-mark">M</span><span>mariana</span>
          <span className={`backend-dot ${backendState}`} title={`Backend: ${backendState}`} />
        </div>
        <div className="title-actions">
          <div className="command-autocomplete">
            <span aria-hidden="true">&gt;</span>
            <input
              role="combobox"
              aria-label="Command suggestions"
              aria-autocomplete="list"
              aria-haspopup="listbox"
              aria-expanded={autocompleteOpen}
              aria-controls={autocompleteOpen ? 'command-suggestion-list' : undefined}
              aria-activedescendant={activeSuggestionId}
              aria-busy={autocompletePending || undefined}
              aria-describedby={autocompleteOpen ? 'command-suggestion-status' : undefined}
              autoComplete="off"
              spellCheck={false}
              placeholder="Explore commands"
              value={autocompleteRequest.typedPrefix}
              onFocus={() => {
                if (!autocompleteOpen) requestCommandSuggestions(autocompleteRequestRef.current.typedPrefix)
              }}
              onBlur={() => {
                if (autocompleteOpen) closeCommandSuggestions()
              }}
              onChange={(event) => requestCommandSuggestions(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.preventDefault()
                  closeCommandSuggestions()
                  return
                }
                if (event.key === 'Enter' || (event.key === 'Tab' && !event.shiftKey && commandSuggestions.length)) {
                  event.preventDefault()
                  const suggestion = commandSuggestions[autocompleteActiveIndex]
                  if (suggestion) acceptCommandSuggestion(suggestion.key, autocompleteRequest)
                  return
                }
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                  event.preventDefault()
                  if (!autocompleteOpen) {
                    requestCommandSuggestions(
                      autocompleteRequestRef.current.typedPrefix,
                      event.key === 'ArrowUp' ? 'last' : 'first',
                    )
                    return
                  }
                  if (!commandSuggestions.length) return
                  const direction = event.key === 'ArrowDown' ? 1 : -1
                  setAutocompleteActiveIndex((index) => (
                    (index + direction + commandSuggestions.length) % commandSuggestions.length
                  ))
                }
              }}
            />
            {autocompleteOpen && (
              <div className="command-suggestion-popover">
                <p
                  id="command-suggestion-status"
                  className="command-suggestion-count"
                  role="status"
                  aria-live="polite"
                >
                  {commandSuggestionStatus}
                </p>
                <ul
                  id="command-suggestion-list"
                  role="listbox"
                  aria-label="Available commands"
                  aria-busy={autocompletePending || undefined}
                >
                  {!autocompletePending && !autocompleteError && commandSuggestions.map((suggestion, index) => (
                    <li
                      id={`command-suggestion-${autocompleteRequest.generation}-${index}`}
                      key={suggestion.key}
                      role="option"
                      aria-selected={index === autocompleteActiveIndex}
                      className={index === autocompleteActiveIndex ? 'active' : ''}
                      onMouseEnter={() => setAutocompleteActiveIndex(index)}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => acceptCommandSuggestion(suggestion.key, autocompleteRequest)}
                    >
                      <span className="command-suggestion-identity">
                        <strong>{suggestion.display_label}</strong>
                        {suggestion.matched_alias && <code>{suggestion.matched_alias}</code>}
                      </span>
                      <span>{suggestion.detail}</span>
                      <small>{suggestion.category} / {suggestion.risk}</small>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
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
            setPalette(selection(value))
            sendCommand(`theme ${value}`)
          }}>
            {Object.entries(themes).map(([id, value]) => <option key={id} value={id}>{value.name}</option>)}
          </select>
          <PaletteEditor key={themeName} theme={theme} onSave={(key, color) => sendCommand(`theme color ${key} ${color}`)}
            onReset={() => sendCommand('theme reset')} />
          <button aria-expanded={strudelOpen} onClick={() => {
            void window.mariana.backend.strudelOpen().then(result => {
              if (!result.ok) setDesktopNotice(result.error || 'The pattern editor could not open.')
            }).catch(() => setDesktopNotice('The pattern editor could not open.'))
          }}>Strudel</button>
          <button aria-expanded={accountsOpen} onClick={()=>setAccountsOpen(open=>!open)}>Connections</button>
          <button title="Decrease font" onClick={() => setFontSize((value) => Math.max(10, value - 1))}>A−</button>
          <button title="Increase font" onClick={() => setFontSize((value) => Math.min(24, value + 1))}>A+</button>
          <button className={timerStatus.active ? 'active' : ''} onClick={() => setTimerOpen((open) => !open)}>
            ◷ {timerStatus.active ? formatRemaining(timerStatus.remaining_seconds) : 'Sleep'}
          </button>
          <button className={mediaOpen ? 'active' : ''} aria-label="Open media workspace" onClick={() => setMediaOpen((open) => !open)}>Media</button>
          <button type="button" aria-label="Open Mini-player" onClick={() => void window.mariana.app.showMiniPlayer()}>Mini</button>
          <button title="Restart Mariana session" onClick={() => void window.mariana.terminal.restart()}>↻</button>
        </div>
      </header>

      <nav className="tabbar" aria-label="Terminal views">
        <button type="button" ref={homeButtonRef} className="desktop-home-button" aria-haspopup="dialog"
          aria-expanded={homeOpen} disabled={backendState !== 'ready'} onClick={() => void openHomepage()}>
          Home
        </button>
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
            <TerminalSurface theme={theme} fontSize={fontSize} reducedMotion={reducedMotion} tabId={tab.id} interactive={!homeOpen} />
          </div>
        ))}
      </section>

      <footer className="statusbar">
        <ListeningControls key={backendState} ready={backendState === 'ready'} status={playbackStatus}
          seekEnabled={seekEnabled && !seekPending} onSeek={(target) => void seekPlayback(target)} />
        <PlaybackStatusBar
          status={playbackStatus}
          unavailableReason={backendDiagnostic}
          favoritePending={favoritePending}
          favoriteError={favoriteError}
          onToggleFavorite={() => void toggleFavorite()}
          seekError={seekError}
          timeline={playbackStatus && <PlaybackTimeline status={playbackStatus} seekEnabled={seekEnabled}
            seekPending={seekPending} snapChapters={snapChapters} hotspots={hotspots}
            onSeek={(targetSeconds, mediaId) => void seekPlayback(targetSeconds, mediaId)} />}
        />
        <div className="statusbar-operations" aria-label="Desktop operational status">
          <MediaStudio ready={backendState === 'ready'} status={playbackStatus} />
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

      {homeOpen && (
        <div className="homepage-backdrop">
          <HomepagePanel homepage={homepage} error={homeError} refreshing={homeRefreshing}
            onClose={closeHomepage} onRefresh={() => void refreshHomepage()}
            onOpenSettings={() => setHomeSettingsOpen((open) => !open)}
            onOpenLink={(link) => { void window.mariana.openExternal(link).catch(() => setHomeError('Could not open this source')) }}
            loadImage={window.mariana.backend.homepageImageData}
            selectionApi={window.mariana.backend} backendReady={backendState === 'ready'}
            playback={playbackStatus} video={homeVideo} reducedMotion={reducedMotion}
            active={!strudelOpen && !accountsOpen}
            settings={homeSettingsOpen ? (
              <fieldset className="homepage-settings" disabled={!homepage || homeConfiguring}>
                <legend>Home settings</legend>
                <label><input type="checkbox" checked={Boolean(homepage?.show_on_startup)}
                  onChange={(event) => void configureHomepage('startup', event.target.checked)} /> Show Home on startup</label>
                <label><input type="checkbox" checked={Boolean(homepage?.online_enabled)}
                  onChange={(event) => void configureHomepage('online', event.target.checked)} /> Enable online discovery</label>
              </fieldset>
            ) : undefined}
          />
        </div>
      )}
      {strudelOpen && <div className="studio-backdrop"><StrudelPanel projection={strudel} api={window.mariana.backend} onClose={() => setStrudelOpen(false)} /></div>}
      {accountsOpen && <AccountConnections close={()=>setAccountsOpen(false)} />}
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
