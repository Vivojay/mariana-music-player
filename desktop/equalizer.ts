export const EQ_FREQUENCIES = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000] as const
export type EqualizerChange =
  | { operation: 'enabled'; enabled: boolean }
  | { operation: 'band'; frequency: number; gain: number }
  | { operation: 'preamp'; gain: number }
  | { operation: 'reset' }
  | { operation: 'preset-apply' | 'preset-save' | 'preset-delete'; name: string }
export type EqualizerIntent = EqualizerChange & { revision: number }
export type EqualizerState = {
  enabled: boolean; bands: number[]; preamp: number; revision: number; sample_rate: number
  frequencies: number[]; available_bands: boolean[]; response: [number, number][]
  recommended_preamp: number; peak: number; overload_blocks: number; fault: boolean
  warning: string | null; presets: { name: string; factory: boolean }[]
}
export type EqualizerResult = { ok: true; state: EqualizerState } | { ok: false; error: string }
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const number = (value: unknown, low: number, high: number): value is number => typeof value === 'number' && Number.isFinite(value) && value >= low && value <= high
const name = (value: unknown): value is string => typeof value === 'string' && /^[\p{L}\p{N}_][\p{L}\p{N}_ .()-]{0,47}$/u.test(value) && value.trim() === value

export function validEqualizerIntent(value: unknown): value is EqualizerIntent {
  if (!object(value) || !Number.isSafeInteger(value.revision) || (value.revision as number) < 0) return false
  const keys = Object.keys(value).sort().join(',')
  switch (value.operation) {
    case 'enabled': return keys === 'enabled,operation,revision' && typeof value.enabled === 'boolean'
    case 'band': return keys === 'frequency,gain,operation,revision' && EQ_FREQUENCIES.some((hz) => hz === value.frequency) && number(value.gain, -12, 12)
    case 'preamp': return keys === 'gain,operation,revision' && number(value.gain, -36, 12)
    case 'reset': return keys === 'operation,revision'
    case 'preset-apply': case 'preset-save': case 'preset-delete': return keys === 'name,operation,revision' && name(value.name)
    default: return false
  }
}

export function projectEqualizer(value: unknown): EqualizerState | null {
  if (!object(value) || typeof value.enabled !== 'boolean' || typeof value.fault !== 'boolean'
    || !number(value.preamp, -36, 12) || !number(value.recommended_preamp, -36, 0)
    || !Number.isSafeInteger(value.revision) || (value.revision as number) < 0
    || !number(value.sample_rate, 8000, 192000) || !number(value.peak, 0, 1e12)
    || !Number.isSafeInteger(value.overload_blocks) || (value.overload_blocks as number) < 0
    || !Array.isArray(value.bands) || value.bands.length !== 10 || !value.bands.every((db) => number(db, -12, 12))
    || !Array.isArray(value.frequencies) || !EQ_FREQUENCIES.every((hz, index) => value.frequencies instanceof Array && value.frequencies[index] === hz)
    || !Array.isArray(value.available_bands) || value.available_bands.length !== 10 || !value.available_bands.every((item) => typeof item === 'boolean')
    || !Array.isArray(value.response) || value.response.length !== 128
    || !value.response.every((point, index, all) => Array.isArray(point) && point.length === 2 && number(point[0], 20, 86400) && number(point[1], -200, 200) && (!index || point[0] > all[index - 1][0]))
    || !Array.isArray(value.presets) || value.presets.length > 36
    || !value.presets.every((item) => object(item) && name(item.name) && typeof item.factory === 'boolean')) return null
  return {
    enabled: value.enabled, bands: [...value.bands], preamp: value.preamp, revision: value.revision as number,
    sample_rate: value.sample_rate, frequencies: [...EQ_FREQUENCIES], available_bands: [...value.available_bands],
    response: value.response.map(([hz, db]) => [hz, db]), recommended_preamp: value.recommended_preamp,
    peak: value.peak, overload_blocks: value.overload_blocks as number, fault: value.fault,
    // Never forward arbitrary backend diagnostic text into a public surface.
    warning: value.warning ? 'Saved EQ settings were invalid; playback is bypassed.' : null,
    presets: value.presets.map((item) => ({ name: item.name, factory: item.factory })),
  }
}
