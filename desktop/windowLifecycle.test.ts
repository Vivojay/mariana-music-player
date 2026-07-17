import { describe, expect, it, vi } from 'vitest'
import {
  createTrayActions,
  ensureSingleTray,
  handleWindowClose,
  normalizeCloseButtonBehavior,
  type WindowPort,
} from './windowLifecycle'

function windowPort() {
  return {
    focus: vi.fn<() => void>(),
    hide: vi.fn<() => void>(),
    isMinimized: (): boolean => false,
    restore: vi.fn<() => void>(),
    show: vi.fn<() => void>(),
  } satisfies WindowPort
}

describe('desktop window lifecycle', () => {
  it('defaults invalid preferences to tray and preserves explicit quit', () => {
    expect(normalizeCloseButtonBehavior(undefined)).toBe('tray')
    expect(normalizeCloseButtonBehavior('unexpected')).toBe('tray')
    expect(normalizeCloseButtonBehavior('quit')).toBe('quit')
  })

  it('hides an ordinary close to an available tray', () => {
    const event = { preventDefault: vi.fn() }
    const window = windowPort()

    expect(handleWindowClose(event, window, 'tray', true, false)).toBe('hidden')
    expect(event.preventDefault).toHaveBeenCalledOnce()
    expect(window.hide).toHaveBeenCalledOnce()
  })

  it.each([
    ['quit preference', 'quit' as const, true, false],
    ['tray unavailable', 'tray' as const, false, false],
    ['explicit quit in progress', 'tray' as const, true, true],
  ])('allows normal close for %s', (_label, behavior, trayAvailable, quitting) => {
    const event = { preventDefault: vi.fn() }
    const window = windowPort()

    expect(handleWindowClose(event, window, behavior, trayAvailable, quitting)).toBe('closed')
    expect(event.preventDefault).not.toHaveBeenCalled()
    expect(window.hide).not.toHaveBeenCalled()
  })

  it('routes tray show, hide, and quit through window and app authorities', () => {
    const window = windowPort()
    window.isMinimized = () => true
    const quit = vi.fn()
    const actions = createTrayActions(() => window, quit)

    actions.show()
    actions.hide()
    actions.quit()

    expect(window.restore).toHaveBeenCalledOnce()
    expect(window.show).toHaveBeenCalledOnce()
    expect(window.focus).toHaveBeenCalledOnce()
    expect(window.hide).toHaveBeenCalledOnce()
    expect(quit).toHaveBeenCalledOnce()
  })

  it('creates only one tray instance', () => {
    const create = vi.fn(() => ({ id: 'tray' }))
    const first = ensureSingleTray(null, create)
    const second = ensureSingleTray(first, create)

    expect(second).toBe(first)
    expect(create).toHaveBeenCalledOnce()
  })
})
