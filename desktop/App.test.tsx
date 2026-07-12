import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./TerminalSurface', () => ({ TerminalSurface: () => <div data-testid="terminal" /> }))

const write = vi.fn()
const check = vi.fn(async () => undefined)
let backendEvent: ((event: { event: string; payload: Record<string, unknown>; timestamp: number }) => void) | undefined

beforeEach(() => {
  write.mockClear()
  check.mockClear()
  backendEvent = undefined
  Object.defineProperty(window, 'mariana', {
    configurable: true,
    value: {
      terminal: { write, resize: vi.fn(), restart: vi.fn(), onData: () => () => {}, onExit: () => () => {} },
      backend: {
        snapshot: async () => ({ ready: true, playbackState: 'idle', sleepActive: false }),
        onEvent: (callback: typeof backendEvent) => { backendEvent = callback; return () => {} },
      },
      updates: { check, install: vi.fn(), onState: () => () => {} },
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
})
