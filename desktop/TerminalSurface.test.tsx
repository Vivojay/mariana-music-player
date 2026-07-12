import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { themes } from './themes'
import { TerminalSurface } from './TerminalSurface'

const state = vi.hoisted(() => ({
  input: undefined as ((value: string) => void) | undefined,
  output: undefined as ((value: string) => void) | undefined,
  search: vi.fn(),
  write: vi.fn(),
  dispose: vi.fn(),
  resize: vi.fn(),
  terminalWrite: vi.fn(),
}))

vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    cols = 100
    rows = 30
    loadAddon() {}
    open() {}
    focus() {}
    write = state.terminalWrite
    dispose = state.dispose
    onData(callback: (value: string) => void) {
      state.input = callback
      return { dispose: vi.fn() }
    }
  },
}))
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }))
vi.mock('@xterm/addon-search', () => ({ SearchAddon: class { findNext = state.search } }))
vi.mock('@xterm/addon-web-links', () => ({ WebLinksAddon: class {} }))
vi.mock('@xterm/addon-webgl', () => ({ WebglAddon: class { onContextLoss() {} dispose() {} } }))

beforeEach(() => {
  Object.assign(state, { input: undefined, output: undefined })
  state.search.mockClear()
  state.write.mockClear()
  state.dispose.mockClear()
  state.resize.mockClear()
  state.terminalWrite.mockClear()
  Object.defineProperty(window, 'mariana', {
    configurable: true,
    value: {
      terminal: {
        write: state.write,
        resize: state.resize,
        restart: vi.fn(),
        onData: (callback: (value: string) => void) => { state.output = callback; return vi.fn() },
        onExit: () => vi.fn(),
      },
      openExternal: vi.fn(),
    },
  })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
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
  act(() => window.dispatchEvent(new CustomEvent('mariana-search', { detail: 'Error' })))
  expect(state.search).toHaveBeenCalledWith('Error', { incremental: true })
  expect(state.resize).toHaveBeenCalledWith(100, 30)
  cleanup()
  expect(state.dispose).toHaveBeenCalled()
})
