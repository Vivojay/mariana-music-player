export type BackendEvent = {
  event: 'ready' | 'playback' | 'sleep' | 'broadcast' | 'loudness' | 'theme' | 'update-safe' | 'update-prepared' | 'shutdown-ack' | 'fatal-error'
  payload: Record<string, unknown>
  timestamp: number
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
