import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { themes } from './themes'
import { TerminalSurface } from './TerminalSurface'

const state = vi.hoisted(() => ({
  input: undefined as ((value: string) => void) | undefined,
  output: undefined as ((value: string) => void) | undefined,
  search: vi.fn(),
  searchPrevious: vi.fn(),
  clearSearch: vi.fn(),
  write: vi.fn(),
  clear: vi.fn(),
  dispose: vi.fn(),
  resize: vi.fn(),
  terminalWrite: vi.fn(),
  fit: vi.fn(),
  observe: vi.fn(),
  disconnect: vi.fn(),
  resized: undefined as ResizeObserverCallback | undefined,
  keyHandler: undefined as ((event: KeyboardEvent) => boolean) | undefined,
  selection: '',
}))

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    cols = 100
    rows = 30
    loadAddon() {}
    open(container: HTMLElement) {
      const screen = document.createElement('div')
      screen.className = 'xterm-screen'
      container.appendChild(screen)
    }
    focus() {}
    clear = state.clear
    write = state.terminalWrite
    dispose = state.dispose
    attachCustomKeyEventHandler(callback: (event: KeyboardEvent) => boolean) {
      state.keyHandler = callback
    }
    hasSelection() { return Boolean(state.selection) }
    getSelection() { return state.selection }
    onData(callback: (value: string) => void) {
      state.input = callback
      return { dispose: vi.fn() }
    }
  },
}))
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit = state.fit } }))
vi.mock('@xterm/addon-search', () => ({ SearchAddon: class {
  findNext = state.search
  findPrevious = state.searchPrevious
  clearDecorations = state.clearSearch
} }))
vi.mock('@xterm/addon-web-links', () => ({ WebLinksAddon: class {} }))
vi.mock('@xterm/addon-webgl', () => ({ WebglAddon: class { onContextLoss() {} dispose() {} } }))

beforeEach(() => {
  Object.assign(state, { input: undefined, output: undefined, keyHandler: undefined, selection: '' })
  state.search.mockClear()
  state.searchPrevious.mockClear()
  state.clearSearch.mockClear()
  state.write.mockClear()
  state.clear.mockClear()
  state.dispose.mockClear()
  state.resize.mockClear()
  state.terminalWrite.mockClear()
  state.fit.mockClear()
  state.observe.mockClear()
  state.disconnect.mockClear()
  Object.defineProperty(window, 'mariana', {
    configurable: true,
    value: {
      terminal: {
        write: state.write,
        resize: state.resize,
        restart: vi.fn(),
        history: async () => '',
        onData: (callback: (value: string) => void) => { state.output = callback; return vi.fn() },
        onExit: () => vi.fn(),
      },
      clipboard: { writeText: vi.fn() },
      openExternal: vi.fn(),
    },
  })
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { state.resized = callback }
    observe = state.observe
    disconnect = state.disconnect
  })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
})

it('copies selected terminal text while preserving Ctrl+C interrupts without a selection', () => {
  render(<TerminalSurface theme={themes.aurora} fontSize={14} reducedMotion={false} />)
  const clipboard = window.mariana.clipboard.writeText as ReturnType<typeof vi.fn>
  state.selection = 'selected output'
  expect(state.keyHandler?.(new KeyboardEvent('keydown', { key: 'c', ctrlKey: true }))).toBe(false)
  expect(clipboard).toHaveBeenCalledWith('selected output')

  state.selection = ''
  expect(state.keyHandler?.(new KeyboardEvent('keydown', { key: 'c', ctrlKey: true }))).toBe(true)
  expect(clipboard).toHaveBeenCalledTimes(1)
})

it('refits when xterm screen metrics change without a container resize', () => {
  const view = render(<TerminalSurface theme={themes.aurora} fontSize={14} reducedMotion={false} />)
  const surface = screen.getByLabelText('Mariana command terminal')
  const terminalScreen = surface.querySelector('.xterm-screen')
  expect(state.observe).toHaveBeenCalledWith(surface)
  expect(state.observe).toHaveBeenCalledWith(terminalScreen)
  state.fit.mockClear()
  state.resize.mockClear()
  act(() => state.resized?.([{ target: terminalScreen } as ResizeObserverEntry], {} as ResizeObserver))
  expect(state.fit).toHaveBeenCalledOnce()
  expect(state.resize).toHaveBeenCalledExactlyOnceWith(100, 30)
  expect(state.write).not.toHaveBeenCalled()
  view.unmount()
  expect(state.disconnect).toHaveBeenCalledOnce()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('bridges PTY input/output, strips ANSI for accessibility, searches, and disposes', () => {
  render(<TerminalSurface theme={themes.aurora} fontSize={14} reducedMotion={false} />)
  act(() => state.input?.('help\r'))
  expect(state.write).toHaveBeenCalledWith('help\r')
  act(() => state.output?.('\u001b[31mError\u001b[0m\r\n'))
  expect(screen.getByLabelText('Terminal output')).toHaveTextContent('Error')
  expect(screen.getByLabelText('Terminal output').textContent).not.toContain('\u001b')
  act(() => state.output?.('\u001b[2'))
  act(() => state.output?.('J\u001b[3'))
  act(() => state.output?.('J\u001b[HClean\r\n'))
  expect(screen.getByLabelText('Terminal output')).toHaveTextContent('Clean')
  expect(screen.getByLabelText('Terminal output')).not.toHaveTextContent('Error')
  act(() => state.output?.('Old output\r\n'))
  act(() => state.input?.('clear\r'))
  expect(state.clear).toHaveBeenCalledOnce()
  expect(screen.getByLabelText('Terminal output')).not.toHaveTextContent('Old output')
  expect(state.write).toHaveBeenCalledWith('clear\r')
  act(() => window.dispatchEvent(new CustomEvent('mariana-search', { detail: 'Error' })))
  expect(state.search).toHaveBeenCalledWith('Error', { incremental: true })
  act(() => window.dispatchEvent(new CustomEvent('mariana-search', {
    detail: { query: 'Error', direction: 'previous', tabId: 1 },
  })))
  expect(state.searchPrevious).toHaveBeenCalledWith('Error', { incremental: false })
  act(() => window.dispatchEvent(new CustomEvent('mariana-search', { detail: { query: '', tabId: 1 } })))
  expect(state.clearSearch).toHaveBeenCalledOnce()
  expect(state.resize).toHaveBeenCalledWith(100, 30)
  cleanup()
  expect(state.dispose).toHaveBeenCalled()
})
