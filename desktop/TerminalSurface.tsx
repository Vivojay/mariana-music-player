import { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { WebglAddon } from '@xterm/addon-webgl'
import '@xterm/xterm/css/xterm.css'
import type { MarianaTheme } from './themes'

type Props = { theme: MarianaTheme; fontSize: number; reducedMotion: boolean }
// Terminal output contains ANSI CSI control sequences by design.
// eslint-disable-next-line no-control-regex
const ANSI_ESCAPE = new RegExp('\\u001b\\[[0-?]*[ -/]*[@-~]', 'g')

export function TerminalSurface({ theme, fontSize, reducedMotion }: Props) {
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
    const input = terminal.onData((data) => window.mariana.terminal.write(data))
    const output = window.mariana.terminal.onData((data) => {
      terminal.write(data)
      const text = data.replace(ANSI_ESCAPE, '').replace(/\r/g, '')
      setAccessibleOutput((current) => (current + text).slice(-8_000))
    })
    const onSearch = (event: Event) => search.findNext((event as CustomEvent<string>).detail, { incremental: true })
    window.addEventListener('mariana-search', onSearch)
    requestAnimationFrame(() => { fitTerminal(); terminal.focus() })
    return () => {
      window.removeEventListener('mariana-search', onSearch)
      output()
      input.dispose()
      resize.disconnect()
      terminal.dispose()
    }
  }, [theme, fontSize, reducedMotion])

  return <>
    <div ref={container} className="terminal-surface" aria-label="Mariana command terminal" />
    <pre className="sr-output" aria-label="Terminal output" aria-live="polite">{accessibleOutput}</pre>
  </>
}
