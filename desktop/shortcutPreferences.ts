export const SHORTCUTS_KEY = 'mariana.shortcuts.enabled'

export const SHORTCUTS = [
  { id: 'toggle', key: ' ', label: 'Space', description: 'Play / pause current media' },
  { id: 'previous', key: 'ArrowLeft', label: '←', description: 'Previous queue item' },
  { id: 'next', key: 'ArrowRight', label: '→', description: 'Next queue item' },
  { id: 'favorite', key: 'l', label: 'L', description: 'Like / unlike current media' },
  { id: 'home', key: 'h', label: 'H', description: 'Open Home' },
  { id: 'settings', key: ',', label: ',', description: 'Open settings' },
  { id: 'equalizer', key: 'e', label: 'E', description: 'Open equalizer' },
  { id: 'artwork', key: 'a', label: 'A', description: 'Show current artwork' },
  { id: 'video', key: 'b', label: 'B', description: 'Focus video presentation control' },
  { id: 'mini', key: 'm', label: 'M', description: 'Show Mini-player / main window' },
  { id: 'sleep', key: 'p', label: 'P', description: 'Open sleep timer' },
  { id: 'queue', key: 'q', label: 'Q', description: 'Open queue' },
  { id: 'downloads', key: 'd', label: 'D', description: 'Open downloads' },
  { id: 'search', key: 'f', label: 'F', description: 'Find terminal output' },
  { id: 'commands', key: 'k', label: 'K', description: 'Explore commands (display only)' },
  { id: 'newView', key: 't', label: 'T', description: 'New terminal view' },
  { id: 'fontLarger', key: 'ArrowUp', label: '↑', description: 'Larger terminal text' },
  { id: 'fontSmaller', key: 'ArrowDown', label: '↓', description: 'Smaller terminal text' },
  { id: 'playlists', key: 'o', label: 'O', description: 'Open playlists' },
  { id: 'albums', key: 'g', label: 'G', description: 'Open albums' },
] as const

export type ShortcutAction = typeof SHORTCUTS[number]['id']
export type ShortcutActions = Partial<Record<ShortcutAction, () => void>>

export function readShortcutsEnabled(): boolean {
  try { return localStorage.getItem(SHORTCUTS_KEY) === 'true' } catch { return false }
}

export function saveShortcutsEnabled(enabled: boolean): boolean {
  try { localStorage.setItem(SHORTCUTS_KEY, String(enabled)); return true } catch { return false }
}

/** Standard editing/terminal combinations and AltGr never belong to this map. */
export function matchShortcut(event: KeyboardEvent, enabled: boolean): ShortcutAction | 'guide' | null {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.altKey) return null
  if (!(event.ctrlKey || event.metaKey) || (event.ctrlKey && event.metaKey)) return null
  if (event.key === '/') return 'guide'
  if (!enabled || !event.shiftKey) return null
  const key = event.key === '<' ? ',' : event.key.toLowerCase()
  return SHORTCUTS.find((item) => item.key.toLowerCase() === key)?.id ?? null
}
