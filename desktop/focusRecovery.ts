export type FocusRecovery = { required: boolean }

// Backend diagnostics and state paths do not belong in the renderer projection.
export function projectFocusRecovery(value: unknown): FocusRecovery | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const required = (value as Record<string, unknown>).required
  return typeof required === 'boolean' ? { required } : null
}
