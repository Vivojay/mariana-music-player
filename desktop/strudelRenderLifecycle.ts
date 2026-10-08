import type { DesktopControlResult } from './shared.js'
import type { StrudelPreviewInput } from './strudelProjects.js'

export const STRUDEL_RENDER_TIMEOUT_MS = 90_000

export type StrudelRenderTask<Owner> = {
  readonly requestId: string
  readonly generation: number
  readonly input: StrudelPreviewInput
  owner: Owner | null
  phase: 'loading' | 'rendering' | 'preparing' | 'committing'
}

/** One bounded render lease, including load, with ownership-safe cancellation. */
export class StrudelRenderLifecycle<Owner> {
  private generation = 0
  private active: {
    task: StrudelRenderTask<Owner>
    timer: ReturnType<typeof setTimeout> | null
    resolve: (result: DesktopControlResult) => void
  } | null = null

  constructor(private readonly retire: (owner: Owner) => void) {}

  begin(requestId: string, input: StrudelPreviewInput) {
    if (this.active) return null
    const task: StrudelRenderTask<Owner> = {
      requestId, generation: ++this.generation,
      input: Object.freeze({ ...input }), owner: null, phase: 'loading',
    }
    const result = new Promise<DesktopControlResult>((resolve) => {
      const timer = setTimeout(() => {
        if (!this.isCurrent(task)) return
        this.finish(task, { ok: false, error: 'Pattern rendering timed out' })
        if (task.owner) this.retire(task.owner)
      }, STRUDEL_RENDER_TIMEOUT_MS)
      this.active = { task, timer, resolve }
    })
    return { task, result }
  }

  isCurrent(task: StrudelRenderTask<Owner>) {
    return this.active?.task === task && task.generation === this.generation
  }

  bind(task: StrudelRenderTask<Owner>, owner: Owner): boolean {
    if (!this.isCurrent(task) || task.phase !== 'loading' || task.owner) return false
    task.owner = owner
    return true
  }

  loaded(task: StrudelRenderTask<Owner>): boolean {
    if (!this.isCurrent(task) || task.phase !== 'loading' || !task.owner) return false
    task.phase = 'rendering'
    return true
  }

  claimReply(requestId: string, owner: Owner): StrudelRenderTask<Owner> | null {
    const task = this.active?.task
    if (!task || task.requestId !== requestId || task.owner !== owner || task.phase !== 'rendering') return null
    task.phase = 'preparing'
    return task
  }

  beginCommit(task: StrudelRenderTask<Owner>): boolean {
    if (!this.isCurrent(task) || task.phase !== 'preparing') return false
    // Rendering/preparation is finished. The existing backend control request
    // has its own bounded timeout; do not time out a dispatched playback action.
    if (this.active?.timer) clearTimeout(this.active.timer)
    if (this.active) this.active.timer = null
    task.phase = 'committing'
    return true
  }

  finish(task: StrudelRenderTask<Owner>, result: DesktopControlResult): boolean {
    if (!this.isCurrent(task) || !this.active) return false
    const current = this.active
    this.active = null
    if (current.timer) clearTimeout(current.timer)
    current.resolve(result)
    return true
  }

  ownerClosed(owner: Owner): void {
    const task = this.active?.task
    if (task?.owner === owner && task.phase !== 'committing') {
      this.finish(task, { ok: false, error: 'Pattern renderer stopped unexpectedly' })
    }
  }

  interrupt(): void {
    const task = this.active?.task
    if (!task) return
    this.finish(task, { ok: false, error: 'Pattern rendering was interrupted' })
    if (task.owner) this.retire(task.owner)
  }
}
