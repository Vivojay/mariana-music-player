export type CloseButtonBehavior = 'tray' | 'quit'

export type CloseEvent = {
  preventDefault(): void
}

export type WindowPort = {
  focus(): void
  hide(): void
  isMinimized(): boolean
  restore(): void
  show(): void
}

export function normalizeCloseButtonBehavior(value: unknown): CloseButtonBehavior {
  return value === 'quit' ? 'quit' : 'tray'
}

export function handleWindowClose(
  event: CloseEvent,
  window: WindowPort,
  behavior: CloseButtonBehavior,
  trayAvailable: boolean,
  quitting: boolean,
): 'hidden' | 'closed' {
  if (behavior !== 'tray' || !trayAvailable || quitting) return 'closed'
  event.preventDefault()
  window.hide()
  return 'hidden'
}

export function createTrayActions(getWindow: () => WindowPort | null, quit: () => void) {
  return {
    show: () => {
      const window = getWindow()
      if (!window) return
      if (window.isMinimized()) window.restore()
      window.show()
      window.focus()
    },
    hide: () => getWindow()?.hide(),
    quit,
  }
}

export function ensureSingleTray<T>(current: T | null, create: () => T): T {
  return current ?? create()
}
