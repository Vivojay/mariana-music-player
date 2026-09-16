import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AppTitlebar } from './AppTitlebar'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('positions workspace overlays using measured header height and observes responsive wrapping', () => {
  let resize: () => void = () => {}
  const observe = vi.fn()
  const disconnect = vi.fn()
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { resize = callback }
    observe = observe
    disconnect = disconnect
  })
  let height = 88
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => ({ height }) as DOMRect)
  const { container, unmount } = render(<main className="app"><AppTitlebar><button>Home</button></AppTitlebar></main>)
  const app = container.querySelector<HTMLElement>('.app')!
  expect(app.style.getPropertyValue('--titlebar-height')).toBe('88px')
  expect(observe).toHaveBeenCalledWith(container.querySelector('.titlebar'))
  height = 124
  act(resize)
  expect(app.style.getPropertyValue('--titlebar-height')).toBe('124px')
  expect(screen.getByRole('button', { name: 'Home' })).toBeVisible()
  unmount()
  expect(disconnect).toHaveBeenCalledOnce()
  expect(app.style.getPropertyValue('--titlebar-height')).toBe('')
})

it('keeps the CSS fallback for unmeasurable layouts and works without ResizeObserver', () => {
  vi.stubGlobal('ResizeObserver', undefined)
  let height = 0
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => ({ height }) as DOMRect)
  const { container } = render(<main className="app"><AppTitlebar>Tools</AppTitlebar></main>)
  const app = container.querySelector<HTMLElement>('.app')!
  expect(app.style.getPropertyValue('--titlebar-height')).toBe('')
  height = 96
  act(() => window.dispatchEvent(new Event('resize')))
  expect(app.style.getPropertyValue('--titlebar-height')).toBe('96px')
})
