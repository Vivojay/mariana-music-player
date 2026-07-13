import { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { WebglAddon } from '@xterm/addon-webgl'
import '@xterm/xterm/css/xterm.css'
import type { MarianaTheme } from './themes'

type Props = { theme: MarianaTheme; fontSize: number; reducedMotion: boolean; tabId?: number }
type SearchRequest = { query: string; direction?: 'incremental' | 'next' | 'previous'; tabId?: number }
// Terminal output contains ANSI CSI control sequences by design.
// eslint-disable-next-line no-control-regex
const ANSI_ESCAPE = new RegExp('\\u001b\\[[0-?]*[ -/]*[@-~]', 'g')

export function TerminalSurface({ theme, fontSize, reducedMotion, tabId = 1 }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const [accessibleOutput, setAccessibleOutput] = useState('')

  useEffect(() => {
    if (!container.current) return
    const terminal = new Terminal({
      theme: theme.terminal,
      fontFamily: "'Cascadia Code Variable', 'Cascadia Code', ui-monospace, monospace",
      fontSize,
      lineHeight: 1.18,
      letterSpacing: 0,
      cursorBlink: !reducedMotion,
      cursorStyle: 'block',
      scrollback: 20_000,
      smoothScrollDuration: reducedMotion ? 0 : 90,
      allowTransparency: true,
      convertEol: false,
    })
    const fit = new FitAddon()
    const search = new SearchAddon()
    terminal.loadAddon(fit)
    terminal.loadAddon(search)
    terminal.loadAddon(new WebLinksAddon((_event, uri) => void window.mariana.openExternal(uri)))
    terminal.open(container.current)
    void window.mariana.terminal.history().then((history) => {
      if (history) terminal.write(history)
    })
    try {
      const webgl = new WebglAddon()
      webgl.onContextLoss(() => webgl.dispose())
      terminal.loadAddon(webgl)
    } catch {
      // Canvas renderer remains active on unsupported GPUs.
    }
    const fitTerminal = () => {
      fit.fit()
      window.mariana.terminal.resize(terminal.cols, terminal.rows)
    }
    const resize = new ResizeObserver(fitTerminal)
    resize.observe(container.current)
    let pendingInput = ''
    const input = terminal.onData((data) => {
      if (data.startsWith('\u001b')) {
        pendingInput = ''
      } else {
        for (const character of data) {
          if (character === '\r' || character === '\n') {
            if (['clear', 'cls'].includes(pendingInput.trim().toLowerCase())) {
              terminal.clear()
              setAccessibleOutput('')
            }
            pendingInput = ''
          } else if (character === '\u007f') {
            pendingInput = pendingInput.slice(0, -1)
          } else if (character === '\u0003') {
            pendingInput = ''
          } else if (character >= ' ') {
            pendingInput += character
          }
        }
      }
      window.mariana.terminal.write(data)
    })
    let controlSequenceTail = ''
    const output = window.mariana.terminal.onData((data) => {
      terminal.write(data)
      const text = data.replace(ANSI_ESCAPE, '').replace(/\r/g, '')
      const controlWindow = controlSequenceTail + data
      const clearsTerminal = controlWindow.includes('\u001b[2J') || controlWindow.includes('\u001b[3J')
      controlSequenceTail = clearsTerminal ? '' : controlWindow.slice(-4)
      setAccessibleOutput((current) => ((clearsTerminal ? '' : current) + text).slice(-8_000))
    })
    const onSearch = (event: Event) => {
      const raw = (event as CustomEvent<string | SearchRequest>).detail
      const request: SearchRequest = typeof raw === 'string' ? { query: raw } : raw
      if (request.tabId && request.tabId !== tabId) return
      if (!request.query) {
        search.clearDecorations()
        return
      }
      const options = { incremental: request.direction === 'incremental' || !request.direction }
      if (request.direction === 'previous') search.findPrevious(request.query, options)
      else search.findNext(request.query, options)
    }
    window.addEventListener('mariana-search', onSearch)
    requestAnimationFrame(() => { fitTerminal(); terminal.focus() })
    return () => {
      window.removeEventListener('mariana-search', onSearch)
      output()
      input.dispose()
      resize.disconnect()
      terminal.dispose()
    }
  }, [theme, fontSize, reducedMotion, tabId])

  return <>
    <div ref={container} className="terminal-surface" aria-label="Mariana command terminal" />
    <pre className="sr-output" aria-label="Terminal output" aria-live="polite">{accessibleOutput}</pre>
  </>
}
