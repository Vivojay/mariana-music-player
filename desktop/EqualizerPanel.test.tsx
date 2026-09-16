import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EqualizerPanel } from './EqualizerPanel'
import { equalizerState } from './equalizer.test'
import type { EqualizerIntent, EqualizerResult } from './equalizer'
import type { BackendEvent } from './shared'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function setup() {
  let state = equalizerState()
  let listener: ((event: BackendEvent) => void) | undefined
  const write = vi.fn()
  const configure = vi.fn(async (intent: EqualizerIntent): Promise<EqualizerResult> => {
    state = { ...state, revision: state.revision + 1 }
    if (intent.operation === 'band') state.bands = state.bands.map((value, index) => state.frequencies[index] === intent.frequency ? intent.gain : value)
    if (intent.operation === 'enabled') state.enabled = intent.enabled
    return { ok: true, state }
  })
  vi.stubGlobal('mariana', { terminal: { write }, backend: {
    equalizerStatus: vi.fn(async () => ({ ok: true, state })), equalizerConfigure: configure,
    onEvent: (callback: (event: BackendEvent) => void) => { listener = callback; return vi.fn() },
  } })
  const close = vi.fn()
  render(<EqualizerPanel onClose={close} />)
  return { configure, write, close,
    restart: () => act(() => listener?.({ event: 'starting', timestamp: 1, payload: {} })),
    emit: (revision: number) => act(() => listener?.({ event: 'equalizer', timestamp: 1, payload: equalizerState({ revision, preamp: -8 }) })) }
}

describe('equalizer panel', () => {
  it('dismisses on a primary pointer press outside, but not from inside the dialog', async () => {
    const { close } = setup()
    const dialog = await screen.findByRole('dialog', { name: 'Equalizer' })

    fireEvent.pointerDown(dialog, { pointerType: 'mouse', button: 0, isPrimary: true })
    expect(close).not.toHaveBeenCalled()
    fireEvent.pointerDown(document.body, { pointerType: 'mouse', button: 2, isPrimary: true })
    expect(close).not.toHaveBeenCalled()
    fireEvent.pointerDown(document.body, { pointerType: 'mouse', button: 0, isPrimary: true })
    expect(close).toHaveBeenCalledOnce()
  })

  it('shows accessible controls and uses only typed backend updates', async () => {
    const { configure, write, close, emit } = setup()
    await screen.findByRole('slider', { name: '1000 Hz gain' })
    expect(screen.getAllByRole('slider')).toHaveLength(11)
    expect(screen.getByRole('img', { name: /Implemented EQ frequency response/ })).toBeVisible()
    fireEvent.change(screen.getByRole('slider', { name: '1000 Hz gain' }), { target: { value: '3.5' } })
    await waitFor(() => expect(configure).toHaveBeenCalledWith({ operation: 'band', frequency: 1000, gain: 3.5, revision: 0 }))
    await act(async () => {})
    emit(5)
    expect(screen.getByRole('slider', { name: 'EQ preamp' })).toHaveValue('-8')
    emit(1)
    expect(screen.getByRole('slider', { name: 'EQ preamp' })).toHaveValue('-8')
    expect(write).not.toHaveBeenCalled()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(close).toHaveBeenCalledOnce()
  })

  it('coalesces pending slider values and submits the final value using the new revision', async () => {
    const { configure, write } = setup()
    await screen.findByRole('slider', { name: '31 Hz gain' })
    let finish: ((value: EqualizerResult) => void) | undefined
    configure.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const slider = screen.getByRole('slider', { name: '31 Hz gain' })
    fireEvent.change(slider, { target: { value: '1' } })
    fireEvent.change(slider, { target: { value: '2' } })
    fireEvent.change(slider, { target: { value: '3' } })
    expect(configure).toHaveBeenCalledTimes(1)
    await act(async () => finish?.({ ok: true, state: equalizerState({ revision: 1 }) }))
    expect(configure).toHaveBeenCalledTimes(2)
    expect(configure.mock.calls[1][0]).toEqual({ operation: 'band', frequency: 31, gain: 3, revision: 1 })
    expect(write).not.toHaveBeenCalled()
  })

  it('recovers after backend restart and protects factory presets', async () => {
    const { emit, restart, configure } = setup()
    await screen.findByRole('slider', { name: '31 Hz gain' })
    emit(8)
    restart()
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    emit(0)
    expect(screen.getAllByRole('slider')).toHaveLength(11)
    expect(screen.getByRole('button', { name: 'Delete user preset' })).toBeDisabled()
    fireEvent.change(screen.getByRole('combobox', { name: 'Equalizer preset' }), { target: { value: 'Evening' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => expect(configure).toHaveBeenCalledWith({ operation: 'preset-apply', name: 'Evening', revision: 0 }))
  })

  it('reports rejected writes and keeps closing accessible', async () => {
    const { configure, close, write } = setup()
    await screen.findByRole('slider', { name: '31 Hz gain' })
    configure.mockResolvedValueOnce({ ok: false, error: 'Equalizer changed; refresh and try again' })
    fireEvent.click(screen.getByRole('button', { name: 'Reset to flat' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Equalizer changed')
    fireEvent.click(screen.getByRole('button', { name: 'Close equalizer' }))
    expect(close).toHaveBeenCalledOnce()
    expect(write).not.toHaveBeenCalled()
  })
})
