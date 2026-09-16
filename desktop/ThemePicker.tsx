import { useEffect, useRef, useState } from 'react'
import { themes, type ThemeName } from './themes'

type ThemePickerProps = {
  value: ThemeName
  onChange(value: ThemeName): void
}

const themeEntries = Object.entries(themes) as Array<[ThemeName, (typeof themes)[ThemeName]]>

export function ThemePicker({ value, onChange }: ThemePickerProps) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(() => Math.max(0, themeEntries.findIndex(([id]) => id === value)))
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => {
    if (!open) return
    queueMicrotask(() => optionRefs.current[activeIndex]?.focus())
  }, [activeIndex, open])

  useEffect(() => {
    if (!open) return
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [open])

  const closeAndFocus = () => {
    setOpen(false)
    queueMicrotask(() => triggerRef.current?.focus())
  }

  const choose = (themeName: ThemeName) => {
    onChange(themeName)
    closeAndFocus()
  }

  const openMenu = () => {
    setActiveIndex(Math.max(0, themeEntries.findIndex(([id]) => id === value)))
    setOpen(true)
  }

  const move = (nextIndex: number) => {
    const bounded = (nextIndex + themeEntries.length) % themeEntries.length
    setActiveIndex(bounded)
    optionRefs.current[bounded]?.focus()
  }

  return (
    <div className="theme-picker" ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className="theme-picker-trigger"
        aria-label="Terminal theme"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? 'terminal-theme-menu' : undefined}
        onClick={() => {
          if (open) setOpen(false)
          else openMenu()
        }}
        onKeyDown={(event) => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
          event.preventDefault()
          openMenu()
        }}
      >
        <span>{themes[value].name}</span>
        <span aria-hidden="true" className="theme-picker-chevron">⌄</span>
      </button>
      {open && (
        <div id="terminal-theme-menu" className="theme-picker-menu" role="menu" aria-label="Terminal themes">
          {themeEntries.map(([id, theme], index) => (
            <button
              type="button"
              role="menuitemradio"
              aria-checked={id === value}
              className={index === activeIndex ? 'active' : ''}
              key={id}
              ref={(element) => { optionRefs.current[index] = element }}
              onFocus={() => setActiveIndex(index)}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => choose(id)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.preventDefault()
                  closeAndFocus()
                } else if (event.key === 'ArrowDown') {
                  event.preventDefault()
                  move(activeIndex + 1)
                } else if (event.key === 'ArrowUp') {
                  event.preventDefault()
                  move(activeIndex - 1)
                } else if (event.key === 'Home') {
                  event.preventDefault()
                  move(0)
                } else if (event.key === 'End') {
                  event.preventDefault()
                  move(themeEntries.length - 1)
                }
              }}
            >
              <span aria-hidden="true" className="theme-picker-check">{id === value ? '✓' : ''}</span>
              <span>{theme.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
