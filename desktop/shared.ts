export type FavoriteStatus = {
  available: boolean
  is_favorite: boolean
  toggle_enabled: boolean
  unavailable_reason: string | null
}

export type PlaybackChapterMarker = {
  title: string
  start_time: number
  end_time: number
  start_percent: number
  end_percent: number
  index: number
  count: number
  current: boolean
}

export type PlaybackStatus = {
  schema_version: number
  state: string
  display_state: string
  media_id: string | null
  title: string | null
  artist: string | null
  source: string | null
  position_seconds: number
  duration_seconds: number | null
  percent: number | null
  buffered_seconds: number
  finite: boolean
  live: boolean
  seekable: boolean
  library_index: number | null
  queue_position: number | null
  queue_count: number
  favorite: FavoriteStatus
  chapter: {
    title: string
    start_time: number
    end_time: number
    index?: number | null
    count?: number | null
  } | null
  /** Optional while restoring snapshots emitted by pre-v7 backends. */
  chapter_markers?: PlaybackChapterMarker[]
  replaygain_db: number
  live_leveling: boolean
  safe_error: string | null
  policy: {
    blocked: boolean
    playable: boolean
    unavailable_reason: string | null
  }
  region: {
    active: boolean
    start_seconds: number | null
    end_seconds: number | null
  }
}

export function formatChapterLabel(chapter: PlaybackStatus['chapter']): string {
  if (!chapter) return ''
  const title = chapter.title?.trim() ?? ''
  const index = Number(chapter.index)
  const count = Number(chapter.count)
  const position = Number.isInteger(index) && Number.isInteger(count) && index >= 1 && index <= count
    ? `Ch ${index}/${count}`
    : ''
  return position && title ? `${position} · ${title}` : position || title
}

type BackendEventName = 'starting' | 'ready' | 'playback' | 'station' | 'sleep' | 'broadcast' | 'loudness' | 'queue' | 'playlist' | 'album' | 'download' | 'theme' | 'desktop-preferences' | 'desktop-notice' | 'update-safe' | 'update-prepared' | 'shutdown-ack' | 'fatal-error' | 'control-result'

export type BackendEvent = {
  event: Exclude<BackendEventName, 'playback'>
  payload: Record<string, unknown>
  timestamp: number
} | {
  event: 'playback'
  payload: PlaybackStatus
  timestamp: number
}

export type BackendSnapshot = {
  ready: boolean
  diagnostic: string | null
  desktopNotice: string | null
  closeButtonBehavior: 'tray' | 'quit'
  playbackState: string
  sleepActive: boolean
  playback: PlaybackStatus | null
}

export type MiniPlayerSnapshot = {
  ready: boolean
  diagnostic: string | null
  playback: PlaybackStatus | null
}

export type DesktopControlResult = {
  ok: boolean
  error?: string
}

export type FavoriteToggleResult = DesktopControlResult

export type SeekResult = DesktopControlResult

export type CommandCatalogRisk = 'read-only' | 'state-changing' | 'destructive' | 'external-action'

export type CommandCatalogForm = {
  tokens: string[]
  argument_kinds: string[]
  flags: string[]
}

export type CommandCatalogEntry = {
  key: string
  canonical: string
  category: string
  summary: string
  risk: CommandCatalogRisk
  aliases: string[]
  forms: CommandCatalogForm[]
  availability: string[]
}

export type CommandCatalogSnapshot = {
  schema_version: 1
  entries: CommandCatalogEntry[]
}

export type CommandCatalogOptions = {
  includeCompatibility?: boolean
  typedPrefix?: string
}

export type CommandCatalogResult = {
  ok: true
  catalog: CommandCatalogSnapshot
} | {
  ok: false
  error: string
}

function displayCells(value: string): number {
  return Array.from(value).reduce((total, character) => {
    if (/\p{Mark}/u.test(character)) return total
    return total + ((character.codePointAt(0) || 0) > 0xff ? 2 : 1)
  }, 0)
}

export function trimDisplayCells(value: string, maximum: number): string {
  if (displayCells(value) <= maximum) return value
  let result = ''
  let cells = 0
  for (const character of Array.from(value)) {
    const width = /\p{Mark}/u.test(character) ? 0 : (character.codePointAt(0) || 0) > 0xff ? 2 : 1
    if (cells + width > maximum - 1) break
    result += character
    cells += width
  }
  return `${result.trimEnd()}…`
}

export type UpdateState = {
  state: 'disabled' | 'idle' | 'checking' | 'available' | 'downloading' | 'downloaded' | 'error'
  version?: string
  percent?: number
  message?: string
  safeToInstall?: boolean
}

export type TerminalExit = {
  code: number
  intentional: boolean
}

export type MarianaDesktopApi = {
  terminal: {
    write(data: string): void
    resize(cols: number, rows: number): void
    restart(): Promise<void>
    history(): Promise<string>
    onData(callback: (data: string) => void): () => void
    onExit(callback: (event: TerminalExit) => void): () => void
  }
  backend: {
    snapshot(): Promise<BackendSnapshot>
    commandCatalog(options?: CommandCatalogOptions): Promise<CommandCatalogResult>
    toggleFavorite(mediaId: string): Promise<FavoriteToggleResult>
    seek(mediaId: string, targetSeconds: number): Promise<SeekResult>
    onEvent(callback: (event: BackendEvent) => void): () => void
  }
  updates: {
    check(): Promise<void>
    install(): Promise<boolean>
    onState(callback: (state: UpdateState) => void): () => void
  }
  clipboard: {
    writeText(value: string): Promise<void>
  }
  app: {
    close(): Promise<void>
    showMiniPlayer(): Promise<void>
  }
  openExternal(url: string): Promise<void>
  platform: string
}

export type MarianaMiniPlayerApi = {
  snapshot(): Promise<MiniPlayerSnapshot>
  onSnapshot(callback: (snapshot: MiniPlayerSnapshot) => void): () => void
  play(mediaId: string): Promise<DesktopControlResult>
  pause(mediaId: string): Promise<DesktopControlResult>
  previous(mediaId: string): Promise<DesktopControlResult>
  next(mediaId: string): Promise<DesktopControlResult>
  showMain(): Promise<void>
  hide(): Promise<void>
  platform: string
}
