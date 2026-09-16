import { useState, type ReactNode } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { isFocusAvailable, useModalFocusTrap } from './modalFocus'

afterEach(() => {
  cleanup()
  document.body.removeAttribute('tabindex')
})

function Dialog({ children, active = true, close, name = 'Fixture' }: {
  children?: ReactNode; active?: boolean; close?: () => void; name?: string
}) {
  const { dialogRef, containTabFocus } = useModalFocusTrap(active, { onOutsidePointer: close })
  return <section ref={dialogRef} tabIndex={-1} role="dialog" aria-label={name} aria-modal={active || undefined}
    inert={!active} onKeyDown={containTabFocus}>{children}</section>
}

it('wraps only through available sequential controls, including details summaries', () => {
  render(<Dialog>
    <button>First</button><input aria-label="Negative" tabIndex={-1} />
    <button disabled>Disabled</button><fieldset disabled><button>Fieldset disabled</button></fieldset>
    <div hidden><button>Hidden ancestor</button></div>
    <div inert><button>Inert ancestor</button></div>
    <div aria-hidden="true"><button>Hidden semantics</button></div>
    <div style={{ display: 'none' }}><button>Hidden style</button></div>
    <button style={{ visibility: 'hidden' }}>Invisible</button>
    <details><summary>Details</summary><button>Closed content</button></details>
  </Dialog>)
  const first = screen.getByText('First')
  const summary = screen.getByText('Details')
  expect(first).toHaveFocus()
  fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
  expect(summary).toHaveFocus()
  fireEvent.keyDown(summary, { key: 'Tab' })
  expect(first).toHaveFocus()
  for (const label of ['Disabled', 'Fieldset disabled', 'Hidden ancestor', 'Inert ancestor', 'Hidden semantics', 'Hidden style', 'Invisible', 'Closed content']) {
    expect(isFocusAvailable(screen.getByText(label))).toBe(false)
  }
  expect(isFocusAvailable(screen.getByLabelText('Negative'))).toBe(true) // Programmatic focus remains valid.
})

it('updates boundaries when details or enabled controls change', () => {
  const view = render(<Dialog><button>First</button><details><summary>Details</summary><button>Inside</button></details></Dialog>)
  const first = screen.getByText('First')
  first.focus()
  fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
  expect(screen.getByText('Details')).toHaveFocus()
  view.rerender(<Dialog><button>First</button><details open><summary>Details</summary><button>Inside</button></details></Dialog>)
  first.focus()
  fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
  expect(screen.getByText('Inside')).toHaveFocus()
  view.rerender(<Dialog><button>First</button><details open><summary>Details</summary><button disabled>Inside</button></details></Dialog>)
  document.body.tabIndex = -1
  document.body.focus()
  expect(first).toHaveFocus() // A newly disabled previous destination is not reused.
})

it('contains an empty dialog and releases containment when inactive or unmounted', () => {
  const view = render(<><button>Outside</button><Dialog /></>)
  const dialog = screen.getByRole('dialog')
  expect(dialog).toHaveFocus()
  fireEvent.keyDown(dialog, { key: 'Tab' })
  expect(dialog).toHaveFocus()
  view.rerender(<><button>Outside</button><Dialog active={false} /></>)
  screen.getByText('Outside').focus()
  expect(screen.getByText('Outside')).toHaveFocus()
  view.unmount()
})

it('lets only the foreground modal contain focus or dismiss on outside input', () => {
  const parentClose = vi.fn()
  function Nested() {
    const [child, setChild] = useState(false)
    return <><button>Outside</button><Dialog name="Parent" close={parentClose}>
      <button onClick={() => setChild(true)}>Open child</button>
    </Dialog>{child && <Dialog name="Child" close={() => setChild(false)}>
      <button onClick={() => setChild(false)}>Close child</button>
    </Dialog>}</>
  }
  render(<Nested />)
  fireEvent.click(screen.getByText('Open child'))
  expect(screen.getByText('Close child')).toHaveFocus()
  screen.getByText('Outside').focus()
  expect(screen.getByText('Close child')).toHaveFocus()
  fireEvent.pointerDown(screen.getByText('Close child'), { button: 0, pointerType: 'mouse' })
  expect(parentClose).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Close child'))
  screen.getByText('Outside').focus()
  expect(screen.getByText('Open child')).toHaveFocus()
})

it('does not capture already handled, composing, or modified Tab events', () => {
  render(<Dialog><button>Only</button></Dialog>)
  const button = screen.getByText('Only')
  for (const extra of [{ isComposing: true }, { ctrlKey: true }, { metaKey: true }, { altKey: true }]) {
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true, ...extra })
    fireEvent(button, event)
    expect(event.defaultPrevented).toBe(false)
  }
})
