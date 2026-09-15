import { useCallback, useEffect, useRef, useState, type FocusEvent } from 'react'

export const VIDEO_CONTROLS_IDLE_MS = 10_000

export function useVideoControlsVisibility(pinned = false) {
  const [visible, setVisible] = useState(true)
  const timer = useRef<number | null>(null)
  const focused = useRef(false)

  const clearTimer = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
  }, [])
  const arm = useCallback(() => {
    clearTimer()
    setVisible(true)
    if (!pinned && !focused.current) {
      timer.current = window.setTimeout(() => { timer.current = null; setVisible(false) }, VIDEO_CONTROLS_IDLE_MS)
    }
  }, [clearTimer, pinned])

  useEffect(() => {
    const kickoff = window.setTimeout(arm, 0)
    return () => { window.clearTimeout(kickoff); clearTimer() }
  }, [arm, clearTimer, pinned])

  return {
    visible: visible || pinned,
    onPointerEnter: arm,
    onPointerMove: arm,
    onPointerDown: () => {
      // Pointer activation commonly leaves a button focused. That focus must not
      // pin video controls indefinitely after pointer movement stops; keyboard
      // focus remains pinned through the focus/key handlers below.
      focused.current = false
      arm()
    },
    onPointerLeave: () => {
      if (!focused.current && !pinned) { clearTimer(); setVisible(false) }
    },
    onFocusCapture: (event: FocusEvent<HTMLElement>) => {
      const target = event.target
      const keyboardFocus = target instanceof HTMLElement && target.matches(':focus-visible')
      focused.current = keyboardFocus
      if (keyboardFocus) {
        clearTimer()
        setVisible(true)
      } else {
        arm()
      }
    },
    onKeyDownCapture: () => {
      focused.current = true
      clearTimer()
      setVisible(true)
    },
    onBlurCapture: (event: FocusEvent<HTMLElement>) => {
      if (event.currentTarget.contains(event.relatedTarget as Node | null)) return
      focused.current = false
      arm()
    },
  }
}
