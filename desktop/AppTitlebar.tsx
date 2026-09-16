import { useLayoutEffect, useRef, type ReactNode } from 'react'

/** Keep workspace overlays below the actual, possibly wrapped application header. */
export function AppTitlebar({ children }: { children: ReactNode }) {
  const headerRef = useRef<HTMLElement>(null)

  useLayoutEffect(() => {
    const header = headerRef.current
    const app = header?.closest<HTMLElement>('.app')
    if (!header || !app) return
    const measure = () => {
      const height = header.getBoundingClientRect().height
      if (height > 0) app.style.setProperty('--titlebar-height', `${height}px`)
    }
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(header)
    window.addEventListener('resize', measure)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', measure)
      app.style.removeProperty('--titlebar-height')
    }
  }, [])

  return <header className="titlebar" ref={headerRef}>{children}</header>
}
