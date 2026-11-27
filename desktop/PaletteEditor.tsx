import { useState } from 'react'
import { validColor, type MarianaTheme } from './themes'

type Props = { theme: MarianaTheme; onSave(key: string, color: string): void; onReset(): void }

export function PaletteEditor({ theme, onSave, onReset }: Props) {
  const [open, setOpen] = useState(false)
  const [key, setKey] = useState('chrome.accent')
  const [edited, setEdited] = useState<string | null>(null)
  const tokens = Object.fromEntries((['chrome', 'terminal'] as const).flatMap(group =>
    Object.entries(theme[group]).map(([name, value]) => [`${group}.${name}`, String(value)]),
  ))
  const color = edited ?? tokens[key]
  return <div className="palette-editor" onKeyDown={event => {
    if (event.key === 'Escape') {
      setOpen(false)
      event.currentTarget.querySelector('button')?.focus()
    }
  }}>
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>Colors</button>
    {open && <form className="palette-controls" aria-label="Customize theme colors"
      onSubmit={event => { event.preventDefault(); if (validColor.test(color)) onSave(key, color) }}>
      <label>Theme color
        <select value={key} onChange={event => { setKey(event.target.value); setEdited(null) }}>
          {Object.keys(tokens).map(token => <option key={token}>{token}</option>)}
        </select>
      </label>
      <label>Hex color
        <input value={color} maxLength={9} onChange={event => setEdited(event.target.value)}
          pattern="#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?" required />
      </label>
      <input aria-label="Pick color" type="color" value={validColor.test(color) ? color.slice(0, 7) : '#000000'}
        onChange={event => setEdited(event.target.value)} />
      <button disabled={!validColor.test(color)}>Apply color</button>
      <button type="button" onClick={() => { setEdited(null); onReset() }}>Reset this preset</button>
    </form>}
  </div>
}
