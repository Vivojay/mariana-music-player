import '@strudel/repl'
import { renderPatternAudio } from '@strudel/webaudio'

type Pattern = Parameters<typeof renderPatternAudio>[0]

type StrudelEditorElement = HTMLElement & {
  code: string
  editor: {
    prebaked: Promise<unknown>
    repl: {
      evaluate(code: string, autostart?: boolean, hush?: boolean): Promise<Pattern | undefined>
      scheduler: { cps: number }
    }
    clear(): void
  } | null
}

function safeError(value: unknown): string {
  const text = value instanceof Error ? value.message : String(value)
  return Array.from(text, (character) => {
    const code = character.charCodeAt(0)
    return code < 32 || code === 127 ? ' ' : character
  }).join('').replace(/\s+/g, ' ').trim().slice(0, 240)
    || 'Pattern rendering failed'
}

async function waitForEditor(element: StrudelEditorElement): Promise<NonNullable<StrudelEditorElement['editor']>> {
  const deadline = performance.now() + 10_000
  while (!element.editor) {
    if (performance.now() > deadline) throw new Error('Pattern engine did not become ready')
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
  await element.editor.prebaked
  return element.editor
}

async function render(request: { requestId: string; code: string; previewSeconds: number }): Promise<void> {
  if (!/^[0-9a-f]{32}$/.test(request.requestId)
    || typeof request.code !== 'string'
    || new TextEncoder().encode(request.code).byteLength > 64 * 1024
    || !Number.isInteger(request.previewSeconds)
    || request.previewSeconds < 1
    || request.previewSeconds > 60) {
    throw new Error('Pattern render request is invalid')
  }
  const element = document.createElement('strudel-editor') as StrudelEditorElement
  element.style.display = 'none'
  element.code = request.code
  element.setAttribute('code', request.code)
  document.body.appendChild(element)
  let rendered: Blob | null = null
  const originalCreateObjectUrl = URL.createObjectURL.bind(URL)
  const originalClick = HTMLAnchorElement.prototype.click
  try {
    const editor = await waitForEditor(element)
    const pattern = await editor.repl.evaluate(request.code, false, true)
    if (!pattern) throw new Error('Pattern could not be evaluated')
    const cps = Number(editor.repl.scheduler.cps)
    if (!Number.isFinite(cps) || cps <= 0 || cps > 20) throw new Error('Pattern tempo is outside the supported range')
    URL.createObjectURL = (value: Blob | MediaSource) => {
      if (value instanceof Blob) rendered = value
      return originalCreateObjectUrl(value)
    }
    HTMLAnchorElement.prototype.click = function noDownload() {}
    await renderPatternAudio(pattern, cps, 0, request.previewSeconds * cps, 48_000, 128, false, 'mariana-pattern')
    if (!rendered) throw new Error('Pattern renderer produced no audio')
    const bytes = await (rendered as Blob).arrayBuffer()
    if (bytes.byteLength < 44 || bytes.byteLength > 16 * 1024 * 1024) {
      throw new Error('Rendered pattern is empty or oversized')
    }
    window.strudelHost.complete(request.requestId, bytes)
  } finally {
    URL.createObjectURL = originalCreateObjectUrl
    HTMLAnchorElement.prototype.click = originalClick
    element.editor?.clear()
    element.remove()
  }
}

let active = false
window.strudelHost.onRender((request) => {
  if (active) {
    window.strudelHost.fail(request.requestId, 'Another pattern preview is already rendering')
    return
  }
  active = true
  void render(request).catch((error) => {
    window.strudelHost.fail(request.requestId, safeError(error))
  }).finally(() => {
    active = false
  })
})
