import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThemePicker } from './ThemePicker'
import type { ThemeName } from './themes'

function ThemePickerHarness({ onChange }: { onChange(value: ThemeName): void }) {
  const [value, setValue] = useState<ThemeName>('gruvbox')
  return (
    <ThemePicker
      value={value}
      onChange={(next) => {
        setValue(next)
        onChange(next)
      }}
    />
  )
}

describe('ThemePicker', () => {
  afterEach(cleanup)

  it('renders a CSS-controlled menu and applies pointer selection immediately', async () => {
    const onChange = vi.fn()
    const { container } = render(<ThemePickerHarness onChange={onChange} />)
    const trigger = screen.getByRole('button', { name: 'Terminal theme' })

    expect(trigger).toHaveTextContent('Gruvbox Dark')
    fireEvent.click(trigger)
    const aurora = screen.getByRole('menuitemradio', { name: 'Mariana Aurora' })
    const gruvbox = screen.getByRole('menuitemradio', { name: 'Gruvbox Dark' })
    expect(gruvbox).toHaveAttribute('aria-checked', 'true')
    expect(container.querySelector('select')).not.toBeInTheDocument()

    fireEvent.mouseEnter(aurora)
    expect(aurora).toHaveClass('active')
    fireEvent.click(aurora)

    expect(onChange).toHaveBeenCalledWith('aurora')
    expect(trigger).toHaveTextContent('Mariana Aurora')
    expect(screen.queryByRole('menu', { name: 'Terminal themes' })).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('supports deterministic arrow navigation and Escape dismissal', async () => {
    render(<ThemePickerHarness onChange={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: 'Terminal theme' })
    fireEvent.click(trigger)
    const gruvbox = screen.getByRole('menuitemradio', { name: 'Gruvbox Dark' })
    await waitFor(() => expect(gruvbox).toHaveFocus())

    fireEvent.keyDown(gruvbox, { key: 'ArrowDown' })
    expect(screen.getByRole('menuitemradio', { name: 'Mariana Aurora' })).toHaveFocus()
    fireEvent.keyDown(screen.getByRole('menuitemradio', { name: 'Mariana Aurora' }), { key: 'ArrowUp' })
    expect(screen.getByRole('menuitemradio', { name: 'Gruvbox Dark' })).toHaveFocus()
    fireEvent.keyDown(screen.getByRole('menuitemradio', { name: 'Gruvbox Dark' }), { key: 'Escape' })

    expect(screen.queryByRole('menu', { name: 'Terminal themes' })).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })
})
