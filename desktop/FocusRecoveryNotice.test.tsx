import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FocusRecoveryNotice } from './FocusRecoveryNotice'
import { projectFocusRecovery } from './focusRecovery'

afterEach(cleanup)

describe('Focus recovery', () => {
  it('allows no arbitrary backend diagnostics or paths into the projection', () => {
    expect(projectFocusRecovery({ required: true, path: 'private', message: 'private' })).toEqual({ required: true })
    for (const value of [null, [], {}, { required: 'true' }, { required: 1 }]) expect(projectFocusRecovery(value)).toBeNull()
  })
  it('requires explicit recheck and keeps safe recovery guidance after rejection', async () => {
    const retry = vi.fn(async () => ({ ok: false, error: 'private path' }))
    render(<FocusRecoveryNotice retry={retry} />)
    expect(retry).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Playback locked')
    fireEvent.click(screen.getByRole('button', { name: 'Recheck restored active state' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Playback stays locked'))
    expect(retry).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('alert')).not.toHaveTextContent('private path')
    expect(screen.getByRole('alert')).toHaveTextContent('Normal passcode and phone verification still apply')
  })
  it('coalesces clicks while the recheck is pending and handles transport failure', async () => {
    let reject!: (error: Error) => void
    const retry = vi.fn(() => new Promise<{ ok: boolean }>((_resolve, decline) => { reject = decline }))
    render(<FocusRecoveryNotice retry={retry} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByRole('button')).toBeDisabled()
    fireEvent.click(screen.getByRole('button'))
    expect(retry).toHaveBeenCalledTimes(1)
    reject(new Error('private transport error'))
    await waitFor(() => expect(screen.getByRole('button')).toBeEnabled())
    expect(screen.getByRole('alert')).toHaveTextContent('Playback stays locked')
    expect(screen.getByRole('alert')).not.toHaveTextContent('private transport error')
  })
})
