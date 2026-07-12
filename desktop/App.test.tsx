import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./TerminalSurface', () => ({ TerminalSurface: () => <div data-testid="terminal" /> }))

const write = vi.fn()
const check = vi.fn(async () => undefined)
const install = vi.fn(async () => undefined)
const restart = vi.fn(async () => undefined)
let backendEvent: ((event: { event: string; payload: Record<string, unknown>; timestamp: number }) => void) | undefined
let updateEvent: ((event: { state: string; version?: string; safeToInstall?: boolean; percent?: number }) => void) | undefined
let exitEvent: ((code: number) => void) | undefined

beforeEach(() => {
  localStorage.clear()
  write.mockClear()
  check.mockClear()
  install.mockClear()
  restart.mockClear()
  backendEvent = undefined
  updateEvent = undefined
  exitEvent = undefined
  Object.defineProperty(window, 'mariana', {
    configurable: true,
    value: {
      terminal: { write, resize: vi.fn(), restart, onData: () => () => {}, onExit: (callback: typeof exitEvent) => { exitEvent = callback; return () => {} } },
      backend: {
        snapshot: async () => ({ ready: true, playbackState: 'idle', sleepActive: false }),
        onEvent: (callback: typeof backendEvent) => { backendEvent = callback; return () => {} },
      },
      updates: { check, install, onState: (callback: typeof updateEvent) => { updateEvent = callback; return () => {} } },
      openExternal: vi.fn(),
      platform: 'win32',
    },
  })
})

afterEach(cleanup)

describe('Mariana desktop shell', () => {
  it('renders the PTY surface and all visual presets', () => {
    render(<App />)
    expect(screen.getByTestId('terminal')).toBeInTheDocument()
    const options = screen.getByLabelText('Terminal theme').querySelectorAll('option')
    expect([...options].map((option) => option.textContent)).toEqual([
      'Mariana Aurora', 'Windows Terminal Acrylic', 'Kitty / Catppuccin', 'Gruvbox Dark',
    ])
  })

  it('routes sleep controls through the real CLI command path', () => {
    render(<App />)
    fireEvent.click(screen.getByText('◷ Sleep'))
    fireEvent.click(screen.getByText('15 min'))
    expect(write).toHaveBeenCalledWith('sleep 15m pause\r')
  })

  it('supports a custom stop timer and manual update checks', () => {
    render(<App />)
    fireEvent.click(screen.getByText('◷ Sleep'))
    fireEvent.change(screen.getByLabelText('Custom timer duration'), { target: { value: '1h30m' } })
    fireEvent.change(screen.getByLabelText('Timer action'), { target: { value: 'stop' } })
    fireEvent.click(screen.getByText('Start'))
    expect(write).toHaveBeenCalledWith('sleep 1h30m stop\r')
    fireEvent.click(screen.getByText('Update: idle'))
    expect(check).toHaveBeenCalledOnce()
  })

  it('renders structured loudness and broadcast state without issuing fake commands', () => {
    render(<App />)
    act(() => {
      backendEvent?.({ event: 'loudness', payload: { replaygain_db: -4.25, live_leveling: false }, timestamp: 1 })
      backendEvent?.({ event: 'broadcast', payload: { state: 'live', codec: 'opus', reconnects: 2 }, timestamp: 2 })
    })
    expect(screen.getByText(/-4\.3 dB/)).toBeInTheDocument()
    expect(screen.getByText(/live · opus · ↻2/)).toBeInTheDocument()
    expect(write).not.toHaveBeenCalled()
  })

  it('validates persisted appearance settings and routes search and restart controls', () => {
    localStorage.setItem('mariana.theme', 'not-a-theme')
    localStorage.setItem('mariana.fontSize', 'not-a-number')
    const searches: string[] = []
    window.addEventListener('mariana-search', (event) => searches.push((event as CustomEvent<string>).detail), { once: true })
    render(<App />)
    expect(screen.getByLabelText('Terminal theme')).toHaveValue('aurora')
    fireEvent.change(screen.getByLabelText('Search terminal'), { target: { value: 'decoder' } })
    fireEvent.click(screen.getByTitle('Restart Mariana session'))
    expect(searches).toEqual(['decoder'])
    expect(restart).toHaveBeenCalledOnce()
  })

  it('reflects backend lifecycle, timer countdown, and safe updater states', () => {
    render(<App />)
    act(() => {
      backendEvent?.({ event: 'sleep', payload: { active: true, remaining_seconds: 61 }, timestamp: 1 })
      updateEvent?.({ state: 'downloading', percent: 49.6 })
    })
    expect(screen.getByRole('button', { name: /00:01:01/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Updating 50%' })).toBeInTheDocument()

    act(() => updateEvent?.({ state: 'downloaded', version: '0.7.1', safeToInstall: false }))
    expect(screen.getByRole('button', { name: 'Update ready when idle' })).toBeDisabled()
    act(() => updateEvent?.({ state: 'downloaded', version: '0.7.1', safeToInstall: true }))
    fireEvent.click(screen.getByRole('button', { name: 'Install 0.7.1' }))
    expect(install).toHaveBeenCalledOnce()

    act(() => backendEvent?.({ event: 'fatal-error', payload: {}, timestamp: 2 }))
    expect(document.querySelector('.backend-dot.error')).toBeInTheDocument()
    act(() => exitEvent?.(1))
    expect(document.querySelector('.backend-dot.stopped')).toBeInTheDocument()
  })

  it('supports keyboard timer toggle and cancellation through the PTY', () => {
    render(<App />)
    fireEvent.keyDown(window, { key: 'P', ctrlKey: true, shiftKey: true })
    expect(screen.getByLabelText('Sleep timer')).toBeVisible()
    fireEvent.click(screen.getByText('Cancel active timer'))
    expect(write).toHaveBeenCalledWith('sleep cancel\r')
  })
})
