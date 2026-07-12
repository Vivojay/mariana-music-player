import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./TerminalSurface', () => ({ TerminalSurface: () => <div data-testid="terminal" /> }))

const write = vi.fn()
const check = vi.fn(async () => undefined)

beforeEach(() => {
  write.mockClear()
  check.mockClear()
  Object.defineProperty(window, 'mariana', {
    configurable: true,
    value: {
      terminal: { write, resize: vi.fn(), restart: vi.fn(), onData: () => () => {}, onExit: () => () => {} },
      backend: { snapshot: async () => ({ ready: true, playbackState: 'idle', sleepActive: false }), onEvent: () => () => {} },
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
})
