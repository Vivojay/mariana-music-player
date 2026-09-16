import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { WebglAddon } from '@xterm/addon-webgl'
import '@xterm/xterm/css/xterm.css'
import type { MarianaTheme } from './themes'

type Props = {
  theme: MarianaTheme
  fontSize: number
  reducedMotion: boolean
  tabId?: number
  interactive?: boolean
  onActivateFocus?: () => boolean
}
type SearchRequest = { query: string; direction?: 'incremental' | 'next' | 'previous'; tabId?: number }
// Terminal output contains ANSI CSI control sequences by design.
// eslint-disable-next-line no-control-regex
const ANSI_ESCAPE = new RegExp('\\u001b\\[[0-?]*[ -/]*[@-~]', 'g')

export function TerminalSurface({ theme, fontSize, reducedMotion, tabId = 1, interactive = true, onActivateFocus }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<Terminal | null>(null)
  const interactiveRef = useRef(interactive)
  const activationFocusRef = useRef(onActivateFocus)
  const [accessibleOutput, setAccessibleOutput] = useState('')

  useLayoutEffect(() => { activationFocusRef.current = onActivateFocus }, [onActivateFocus])

  const focusTerminal = useCallback((terminal: Terminal) => {
    if (!interactiveRef.current || terminalRef.current !== terminal || activationFocusRef.current?.()) return
    const focused = document.activeElement
    // An overlay may have just returned focus to its trigger. Keep that
    // deliberate destination instead of stealing it on the next frame.
    if (focused instanceof HTMLElement && focused !== document.body && !container.current?.contains(focused)) return
    terminal.focus()
  }, [])

  useLayoutEffect(() => {
    interactiveRef.current = interactive
    const terminal = terminalRef.current
    if (!terminal) return
    if (interactive) {
      const frame = requestAnimationFrame(() => focusTerminal(terminal))
      return () => cancelAnimationFrame(frame)
    }
    const helper = container.current?.querySelector<HTMLElement>('.xterm-helper-textarea')
    helper?.blur()
  }, [interactive, focusTerminal])

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
    terminalRef.current = terminal
    const fit = new FitAddon()
    const search = new SearchAddon()
    terminal.loadAddon(fit)
    terminal.loadAddon(search)
    terminal.loadAddon(new WebLinksAddon((_event, uri) => void window.mariana.openExternal(uri)))
    terminal.open(container.current)
    terminal.attachCustomKeyEventHandler((event) => {
      const isCopy = event.type === 'keydown'
        && (event.ctrlKey || event.metaKey)
        && event.key.toLowerCase() === 'c'
      if (!isCopy || !terminal.hasSelection()) return true
      const selection = terminal.getSelection()
      if (selection) void window.mariana.clipboard.writeText(selection)
      return false
    })
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
    // Font/DPI remeasurement can change xterm's screen after the container was
    // fitted. Observe that surface too so the row count converges to its bounds.
    const screen = container.current.querySelector('.xterm-screen')
    if (screen) resize.observe(screen)
    let pendingInput = ''
    const input = terminal.onData((data) => {
      if (!interactiveRef.current) return
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
    const initialFrame = requestAnimationFrame(() => {
      if (terminalRef.current !== terminal) return
      fitTerminal()
      focusTerminal(terminal)
    })
    return () => {
      cancelAnimationFrame(initialFrame)
      window.removeEventListener('mariana-search', onSearch)
      output()
      input.dispose()
      resize.disconnect()
      terminal.dispose()
      if (terminalRef.current === terminal) terminalRef.current = null
    }
  }, [theme, fontSize, reducedMotion, tabId, focusTerminal])

  return <>
    <div ref={container} className="terminal-surface" aria-label="Mariana command terminal" />
    <pre className="sr-output" aria-label="Terminal output" aria-live="polite">{accessibleOutput}</pre>
  </>
}
