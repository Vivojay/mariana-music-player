import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useLayoutEffect } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { KeyboardShortcuts } from './KeyboardShortcuts'
import { matchShortcut, readShortcutsEnabled, SHORTCUTS_KEY } from './shortcutPreferences'

beforeEach(() => localStorage.clear())
afterEach(cleanup)

it('defaults off, always opens the guide, persists opt-in and stops captured keys before terminal handlers', () => {
  const toggle = vi.fn()
  const terminal = vi.fn()
  render(<KeyboardShortcuts actions={{ toggle }} />)
  expect(readShortcutsEnabled()).toBe(false)
  fireEvent.keyDown(window, { key: ' ', ctrlKey: true, shiftKey: true })
  expect(toggle).not.toHaveBeenCalled()
  fireEvent.keyDown(window, { key: '/', ctrlKey: true })
  expect(screen.getByRole('dialog')).toBeVisible()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Enable app shortcuts' }))
  expect(localStorage.getItem(SHORTCUTS_KEY)).toBe('true')
  fireEvent.keyDown(window, { key: '/', ctrlKey: true })
  expect(screen.queryByRole('dialog')).toBeNull()
  window.addEventListener('keydown', terminal)
  fireEvent.keyDown(window, { key: ' ', ctrlKey: true, shiftKey: true })
  expect(toggle).toHaveBeenCalledOnce()
  expect(terminal).not.toHaveBeenCalled()
  fireEvent.keyDown(window, { key: 'c', ctrlKey: true })
  expect(terminal).toHaveBeenCalledOnce()
  window.removeEventListener('keydown', terminal)
})

it('keeps inside clicks active and closes the guide on an outside click', () => {
  render(<KeyboardShortcuts actions={{}} />)
  const trigger = screen.getByRole('button', { name: 'Keyboard shortcuts' })
  fireEvent.click(trigger)
  const dialog = screen.getByRole('dialog', { name: 'Keyboard shortcuts' })
  fireEvent.pointerDown(dialog, { pointerType: 'mouse', button: 0, isPrimary: true })
  expect(dialog).toBeVisible()
  fireEvent.pointerDown(document.body, { pointerType: 'mouse', button: 0, isPrimary: true })
  expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull()
})

it('blocks actions during a modal, repeated keys and IME/AltGr; preserves standard editing keys', () => {
  localStorage.setItem(SHORTCUTS_KEY, 'true')
  const toggle = vi.fn()
  render(<KeyboardShortcuts actions={{ toggle }} />)
  fireEvent.keyDown(window, { key: '/', ctrlKey: true })
  const blocked = new KeyboardEvent('keydown', { key: ' ', ctrlKey: true, shiftKey: true, cancelable: true })
  fireEvent(window, blocked)
  expect(toggle).not.toHaveBeenCalled()
  expect(blocked.defaultPrevented).toBe(true)
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  for (const key of ['c', 'v', 'x', 'z', 'a']) {
    expect(matchShortcut(new KeyboardEvent('keydown', { key, ctrlKey: true }), true)).toBeNull()
  }
  for (const key of ['c', 'v']) {
    expect(matchShortcut(new KeyboardEvent('keydown', { key, ctrlKey: true, shiftKey: true }), true)).toBeNull()
  }
  for (const extra of [{ repeat: true }, { isComposing: true }, { altKey: true }]) {
    expect(matchShortcut(new KeyboardEvent('keydown', { key: ' ', ctrlKey: true, shiftKey: true, ...extra }), true)).toBeNull()
  }
})

it('updates an open second window when shortcuts are disabled, without disabling the guide', () => {
  localStorage.setItem(SHORTCUTS_KEY, 'true')
  const toggle = vi.fn()
  render(<KeyboardShortcuts actions={{ toggle }} />)
  localStorage.setItem(SHORTCUTS_KEY, 'false')
  fireEvent(window, new StorageEvent('storage', { key: SHORTCUTS_KEY }))
  fireEvent.keyDown(window, { key: ' ', ctrlKey: true, shiftKey: true })
  expect(toggle).not.toHaveBeenCalled()
  fireEvent.keyDown(window, { key: '/', metaKey: true })
  expect(screen.getByRole('dialog')).toBeVisible()
})

it('handles shifted punctuation without taking standard clipboard combinations', () => {
  expect(matchShortcut(new KeyboardEvent('keydown', { key: '<', ctrlKey: true, shiftKey: true }), true)).toBe('settings')
  expect(matchShortcut(new KeyboardEvent('keydown', { key: '/', ctrlKey: true, shiftKey: true }), false)).toBe('guide')
})

it('uses newly committed actions immediately and does not close the guide during composition or repeats', () => {
  localStorage.setItem(SHORTCUTS_KEY, 'true')
  const first = vi.fn(), second = vi.fn()
  function Host({ toggle, dispatch = false }: { toggle: () => void; dispatch?: boolean }) {
    useLayoutEffect(() => {
      // A parent layout callback can run before the child's passive effects.
      if (dispatch) window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', ctrlKey: true, shiftKey: true }))
    }, [dispatch])
    return <KeyboardShortcuts actions={{ toggle }} />
  }
  const view = render(<Host toggle={first} />)
  view.rerender(<Host toggle={second} dispatch />)
  expect(first).not.toHaveBeenCalled()
  expect(second).toHaveBeenCalledOnce()
  fireEvent.keyDown(window, { key: '/', ctrlKey: true })
  fireEvent.keyDown(window, { key: 'Escape', isComposing: true })
  fireEvent.keyDown(window, { key: 'Escape', repeat: true })
  expect(screen.getByRole('dialog')).toBeVisible()
})

it('restores the Keys trigger when the previous control was removed or hidden', async () => {
  const view = render(<><button>Origin</button><KeyboardShortcuts actions={{}} /></>)
  screen.getByText('Origin').focus()
  fireEvent.keyDown(window, { key: '/', ctrlKey: true })
  view.rerender(<><button hidden>Origin</button><KeyboardShortcuts actions={{}} /></>)
  await act(async () => fireEvent.keyDown(window, { key: 'Escape' }))
  expect(screen.getByRole('button', { name: 'Keyboard shortcuts' })).toHaveFocus()
})
