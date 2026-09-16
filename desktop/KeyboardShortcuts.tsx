import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { isFocusAvailable, useModalFocusTrap } from './modalFocus'
import { matchShortcut, readShortcutsEnabled, saveShortcutsEnabled, SHORTCUTS, SHORTCUTS_KEY, type ShortcutActions } from './shortcutPreferences'
import './keyboardShortcuts.css'

export function KeyboardShortcuts({ actions, onVisibilityChange }: { actions: ShortcutActions; onVisibilityChange?: (open: boolean) => void }) {
  const [enabled, setEnabled] = useState(readShortcutsEnabled)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const returnFocus = useRef<HTMLElement | null>(null)
  const restoreFocus = useRef(false)
  const current = useRef({ actions, onVisibilityChange, open, enabled })
  useLayoutEffect(() => { current.current = { actions, onVisibilityChange, open, enabled } })

  function changeOpen(next: boolean) {
    if (next === current.current.open) return
    if (next) {
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    } else {
      restoreFocus.current = true
    }
    current.current.open = next
    current.current.onVisibilityChange?.(next)
    setOpen(next)
  }

  const { dialogRef, containTabFocus } = useModalFocusTrap(open, {
    onOutsidePointer: () => changeOpen(false),
    ignoredRefs: [triggerRef],
  })

  useEffect(() => {
    // Restore only after closing has committed and the modal trap has released.
    // A microtask queued by the native key listener can run before that commit.
    if (open || !restoreFocus.current) return
    restoreFocus.current = false
    const destination = returnFocus.current && isFocusAvailable(returnFocus.current) ? returnFocus.current : triggerRef.current
    returnFocus.current = null
    destination?.focus()
  }, [open])

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.isComposing || event.defaultPrevented || event.repeat) return
      const state = current.current
      const action = matchShortcut(event, state.enabled)
      if (action === 'guide' || (state.open && event.key === 'Escape')) {
        event.preventDefault()
        event.stopImmediatePropagation()
        changeOpen(!state.open)
        return
      }
      if (!action) return
      // A recognized app shortcut must not activate a focused checkbox/button
      // or become terminal input when its playback action is blocked by a modal.
      if (state.open || document.querySelector('[aria-modal="true"]')) {
        event.preventDefault()
        event.stopImmediatePropagation()
        return
      }
      const callback = state.actions[action]
      if (!callback) return
      event.preventDefault()
      event.stopImmediatePropagation()
      callback()
    }
    const storage = (event: StorageEvent) => {
      if (event.key === SHORTCUTS_KEY || event.key === null) setEnabled(readShortcutsEnabled())
    }
    const show = () => changeOpen(true)
    // Capture before xterm: handled combinations must never become PTY input.
    window.addEventListener('keydown', keydown, true)
    window.addEventListener('storage', storage)
    window.addEventListener('mariana-shortcut-guide', show)
    return () => {
      window.removeEventListener('keydown', keydown, true)
      window.removeEventListener('storage', storage)
      window.removeEventListener('mariana-shortcut-guide', show)
    }
  }, [])

  return <>
    <button ref={triggerRef} type="button" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (Ctrl+/)" onClick={() => changeOpen(!open)}>Keys</button>
    {open && createPortal(<aside ref={dialogRef} className="shortcut-dialog" role="dialog" aria-modal="true"
      aria-label="Keyboard shortcuts" tabIndex={-1} onKeyDown={containTabFocus}>
      <header><strong>Keyboard shortcuts</strong><button type="button" aria-label="Close keyboard shortcuts" onClick={() => changeOpen(false)}>×</button></header>
      <label><input type="checkbox" checked={enabled} onChange={(event) => {
        if (saveShortcutsEnabled(event.target.checked)) { setEnabled(event.target.checked); setError(null) }
        else setError('Could not save shortcut preference')
      }} />Enable app shortcuts</label>
      <p>Off by default. Ctrl+/ (⌘/ on macOS) always toggles this guide. Copy, paste and terminal interrupt are unchanged.</p>
      <p>Use Ctrl+Shift (⌘+Shift on macOS) with the keys below. Actions retain their normal availability checks.</p>
      <dl>{SHORTCUTS.filter((item) => actions[item.id]).map((item) => <div key={item.id}>
        <dt><kbd>{item.label}</kbd></dt><dd>{item.description}</dd>
      </div>)}</dl>
      <p>Focus a seek bar to use its arrow, Home and End keys. Tab and Enter activate other visible controls, including when app shortcuts are off.</p>
      {error && <p role="alert">{error}</p>}
    </aside>, document.querySelector('.app') ?? document.body)}
  </>
}
