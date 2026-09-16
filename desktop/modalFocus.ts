import {
  useEffect,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from 'react'

const FOCUSABLE = `:is(${[
  'a[href]',
  'button',
  'input',
  'select',
  'textarea',
  '[tabindex]',
  'details > summary:first-of-type',
].join(',')})`

/** Rendered and usable, including ancestors; aria-hidden alone does not stop Tab. */
export function isFocusAvailable(element: HTMLElement): boolean {
  if (!element.isConnected || element.matches(':disabled, input[type="hidden"]')
    || element.closest('[hidden], [inert], [aria-hidden="true"]')) return false
  const style = getComputedStyle(element)
  if (style.visibility === 'hidden' || style.visibility === 'collapse') return false
  for (let ancestor: HTMLElement | null = element; ancestor; ancestor = ancestor.parentElement) {
    if (getComputedStyle(ancestor).display === 'none') return false
    if (ancestor instanceof HTMLDetailsElement && !ancestor.open && ancestor !== element
      && !ancestor.querySelector(':scope > summary')?.contains(element)) return false
  }
  return true
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter((element) => element.tabIndex >= 0 && isFocusAvailable(element))
    .sort((left, right) => (left.tabIndex || Number.MAX_SAFE_INTEGER) - (right.tabIndex || Number.MAX_SAFE_INTEGER))
}

// Only the most recently activated modal contains focus. Parent modals remain
// mounted during nested inspection but must not fight a foreground dialog.
const modalLayers: HTMLElement[] = []
function foregroundModal(): HTMLElement | undefined {
  return [...modalLayers].reverse().find((element) => isFocusAvailable(element))
}

type OutsidePointerOptions = {
  onOutsidePointer?: () => void
  ignoredRefs?: ReadonlyArray<RefObject<HTMLElement | null>>
  canDismiss?: () => boolean
}

function useOutsidePointerForRef(
  active: boolean,
  surfaceRef: RefObject<HTMLElement | null>,
  { onOutsidePointer, ignoredRefs = [], canDismiss }: OutsidePointerOptions,
) {
  const dismissRef = useRef(onOutsidePointer)
  const ignoredRefsRef = useRef(ignoredRefs)
  const canDismissRef = useRef(canDismiss)

  useEffect(() => {
    dismissRef.current = onOutsidePointer
    ignoredRefsRef.current = ignoredRefs
    canDismissRef.current = canDismiss
  }, [onOutsidePointer, ignoredRefs, canDismiss])

  useEffect(() => {
    if (!active || !dismissRef.current) return undefined
    const dismissOutside = (event: PointerEvent) => {
      if (canDismissRef.current && !canDismissRef.current()) return
      if (event.isPrimary === false || (event.pointerType === 'mouse' && event.button !== 0)) return
      const target = event.target
      if (!(target instanceof Node) || surfaceRef.current?.contains(target)) return
      if (ignoredRefsRef.current.some((reference) => reference.current?.contains(target))) return
      dismissRef.current?.()
    }
    document.addEventListener('pointerdown', dismissOutside, true)
    return () => document.removeEventListener('pointerdown', dismissOutside, true)
  }, [active, surfaceRef])
}

/** Dismiss an anchored popover when the primary pointer is pressed outside it. */
export function useOutsidePointerDismiss<T extends HTMLElement>(
  active: boolean,
  onOutsidePointer: () => void,
  ignoredRefs: ReadonlyArray<RefObject<HTMLElement | null>> = [],
) {
  const surfaceRef = useRef<T | null>(null)
  useOutsidePointerForRef(active, surfaceRef, { onOutsidePointer, ignoredRefs })
  return surfaceRef
}

/** Keep keyboard and programmatic focus inside the active renderer-owned modal. */
export function useModalFocusTrap(active: boolean, options: OutsidePointerOptions = {}) {
  const dialogRef = useRef<HTMLElement | null>(null)
  const lastFocusedRef = useRef<HTMLElement | null>(null)
  useOutsidePointerForRef(active, dialogRef, { ...options, canDismiss: () => foregroundModal() === dialogRef.current })

  useEffect(() => {
    if (!active) return undefined
    const dialog = dialogRef.current
    if (!dialog) return undefined
    modalLayers.push(dialog)
    const destination = () => lastFocusedRef.current && dialog.contains(lastFocusedRef.current)
      && isFocusAvailable(lastFocusedRef.current) ? lastFocusedRef.current : focusableElements(dialog)[0] || dialog
    if (document.activeElement instanceof HTMLElement && dialog.contains(document.activeElement)) {
      lastFocusedRef.current = document.activeElement
    } else {
      destination().focus()
    }
    const containFocus = (event: FocusEvent) => {
      if (foregroundModal() !== dialog) return
      if (event.target instanceof Node && dialog.contains(event.target)) {
        if (event.target instanceof HTMLElement) lastFocusedRef.current = event.target
        return
      }
      destination().focus()
    }
    document.addEventListener('focusin', containFocus)
    return () => {
      document.removeEventListener('focusin', containFocus)
      const index = modalLayers.lastIndexOf(dialog)
      if (index !== -1) modalLayers.splice(index, 1)
    }
  }, [active])

  const containTabFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!active || event.key !== 'Tab' || event.defaultPrevented || event.nativeEvent.isComposing
      || event.ctrlKey || event.metaKey || event.altKey) return
    const dialog = dialogRef.current
    if (!dialog || foregroundModal() !== dialog) return
    const focusable = focusableElements(dialog)
    if (!focusable.length) {
      event.preventDefault()
      dialog.focus()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
      event.preventDefault()
      first.focus()
    }
  }

  return { dialogRef, containTabFocus }
}
