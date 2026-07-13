export type BackendEvent = {
  event: 'ready' | 'playback' | 'station' | 'sleep' | 'broadcast' | 'loudness' | 'queue' | 'playlist' | 'album' | 'download' | 'theme' | 'update-safe' | 'update-prepared' | 'shutdown-ack' | 'fatal-error'
  payload: Record<string, unknown>
  timestamp: number
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

export type MarianaDesktopApi = {
  terminal: {
    write(data: string): void
    resize(cols: number, rows: number): void
    restart(): Promise<void>
    history(): Promise<string>
    onData(callback: (data: string) => void): () => void
    onExit(callback: (code: number) => void): () => void
  }
  backend: {
    snapshot(): Promise<{ ready: boolean; playbackState: string; sleepActive: boolean }>
    onEvent(callback: (event: BackendEvent) => void): () => void
  }
  updates: {
    check(): Promise<void>
    install(): Promise<boolean>
    onState(callback: (state: UpdateState) => void): () => void
  }
  openExternal(url: string): Promise<void>
  platform: string
}
