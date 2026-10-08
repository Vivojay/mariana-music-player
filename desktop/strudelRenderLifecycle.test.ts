import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { STRUDEL_RENDER_TIMEOUT_MS, StrudelRenderLifecycle } from './strudelRenderLifecycle'

const project = { project_id: 'a'.repeat(32), revision: 1, name: 'Evening', code: 'note("c3")', preview_seconds: 1 }

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('bounded pattern render lifecycle', () => {
  it('reserves before loading and bounds a never-resolving load', async () => {
    const retire = vi.fn()
    const lifecycle = new StrudelRenderLifecycle<object>(retire)
    const first = lifecycle.begin('one', project)!
    const owner = {}
    expect(lifecycle.begin('two', project)).toBeNull()
    expect(lifecycle.bind(first.task, owner)).toBe(true)
    await vi.advanceTimersByTimeAsync(STRUDEL_RENDER_TIMEOUT_MS - 1)
    expect(lifecycle.isCurrent(first.task)).toBe(true)
    await vi.advanceTimersByTimeAsync(1)
    expect(await first.result).toEqual({ ok: false, error: 'Pattern rendering timed out' })
    expect(retire).toHaveBeenCalledExactlyOnceWith(owner)
    expect(lifecycle.loaded(first.task)).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('retires a hung render and lets a fresh generation complete', async () => {
    const retire = vi.fn()
    const lifecycle = new StrudelRenderLifecycle<object>(retire)
    const oldOwner = {}
    const first = lifecycle.begin('one', project)!
    lifecycle.bind(first.task, oldOwner)
    lifecycle.loaded(first.task)
    await vi.advanceTimersByTimeAsync(STRUDEL_RENDER_TIMEOUT_MS)
    expect((await first.result).ok).toBe(false)
    const next = lifecycle.begin('two', project)!
    const nextOwner = {}
    lifecycle.bind(next.task, nextOwner)
    lifecycle.loaded(next.task)
    expect(next.task.generation).toBeGreaterThan(first.task.generation)
    expect(lifecycle.claimReply('one', oldOwner)).toBeNull()
    expect(lifecycle.claimReply('two', oldOwner)).toBeNull()
    lifecycle.ownerClosed(oldOwner)
    expect(lifecycle.isCurrent(next.task)).toBe(true)
    expect(lifecycle.claimReply('two', nextOwner)).toBe(next.task)
    expect(lifecycle.beginCommit(next.task)).toBe(true)
    expect(lifecycle.finish(next.task, { ok: true })).toBe(true)
    expect(await next.result).toEqual({ ok: true })
    expect(retire).toHaveBeenCalledExactlyOnceWith(oldOwner)
  })

  it('claims replies once and rejects duplicates throughout preparation and commit', async () => {
    const lifecycle = new StrudelRenderLifecycle<object>(vi.fn())
    const { task, result } = lifecycle.begin('one', project)!
    const owner = {}
    lifecycle.bind(task, owner)
    expect(lifecycle.claimReply('one', owner)).toBeNull()
    expect(lifecycle.beginCommit(task)).toBe(false)
    lifecycle.loaded(task)
    expect(lifecycle.claimReply('one', owner)).toBe(task)
    expect(lifecycle.claimReply('one', owner)).toBeNull()
    lifecycle.beginCommit(task)
    expect(lifecycle.claimReply('one', owner)).toBeNull()
    lifecycle.finish(task, { ok: true })
    expect(lifecycle.finish(task, { ok: false })).toBe(false)
    expect(await result).toEqual({ ok: true })
  })

  it('invalidates asynchronous preparation when the deadline expires', async () => {
    const retire = vi.fn()
    const lifecycle = new StrudelRenderLifecycle<object>(retire)
    const { task, result } = lifecycle.begin('one', project)!
    const owner = {}
    lifecycle.bind(task, owner)
    lifecycle.loaded(task)
    lifecycle.claimReply('one', owner)
    await vi.advanceTimersByTimeAsync(STRUDEL_RENDER_TIMEOUT_MS)
    expect((await result).ok).toBe(false)
    expect(lifecycle.isCurrent(task)).toBe(false)
    expect(lifecycle.beginCommit(task)).toBe(false)
    expect(retire).toHaveBeenCalledExactlyOnceWith(owner)
  })

  it('hands a committed playback request to its existing backend timeout', async () => {
    const retire = vi.fn()
    const lifecycle = new StrudelRenderLifecycle<object>(retire)
    const { task, result } = lifecycle.begin('one', project)!
    const owner = {}
    lifecycle.bind(task, owner)
    lifecycle.loaded(task)
    lifecycle.claimReply('one', owner)
    lifecycle.beginCommit(task)
    lifecycle.ownerClosed(owner)
    await vi.advanceTimersByTimeAsync(STRUDEL_RENDER_TIMEOUT_MS * 2)
    expect(lifecycle.isCurrent(task)).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
    expect(retire).not.toHaveBeenCalled()
    lifecycle.finish(task, { ok: false, error: 'Backend control timed out' })
    expect(await result).toEqual({ ok: false, error: 'Backend control timed out' })
  })

  it.each(['loading', 'rendering', 'preparing', 'committing'] as const)(
    'shutdown interrupts %s once and clears timers without affecting a later owner', async (phase) => {
      const retire = vi.fn()
      const lifecycle = new StrudelRenderLifecycle<object>(retire)
      const { task, result } = lifecycle.begin('one', project)!
      const owner = {}
      lifecycle.bind(task, owner)
      if (phase !== 'loading') lifecycle.loaded(task)
      if (phase === 'preparing' || phase === 'committing') lifecycle.claimReply('one', owner)
      if (phase === 'committing') lifecycle.beginCommit(task)
      lifecycle.interrupt()
      lifecycle.interrupt()
      expect(await result).toEqual({ ok: false, error: 'Pattern rendering was interrupted' })
      expect(retire).toHaveBeenCalledExactlyOnceWith(owner)
      expect(vi.getTimerCount()).toBe(0)
      expect(lifecycle.claimReply('one', owner)).toBeNull()
      const next = lifecycle.begin('two', project)!
      lifecycle.ownerClosed(owner)
      expect(lifecycle.isCurrent(next.task)).toBe(true)
      lifecycle.finish(next.task, { ok: true })
    },
  )

  it('binds an immutable project snapshot and cannot rebind its owner', async () => {
    const lifecycle = new StrudelRenderLifecycle<object>(vi.fn())
    const input = { ...project }
    const { task, result } = lifecycle.begin('one', input)!
    input.code = 'changed'
    expect(task.input.code).toBe(project.code)
    expect(Object.isFrozen(task.input)).toBe(true)
    expect(lifecycle.loaded(task)).toBe(false)
    expect(lifecycle.bind(task, {})).toBe(true)
    expect(lifecycle.bind(task, {})).toBe(false)
    lifecycle.ownerClosed(task.owner!)
    expect(await result).toEqual({ ok: false, error: 'Pattern renderer stopped unexpectedly' })
    expect(vi.getTimerCount()).toBe(0)
  })
})
