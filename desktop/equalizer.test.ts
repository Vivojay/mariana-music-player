import { describe, expect, it } from 'vitest'
import { EQ_FREQUENCIES, projectEqualizer, validEqualizerIntent, type EqualizerState } from './equalizer'

export function equalizerState(changes: Partial<EqualizerState> = {}): EqualizerState {
  return {
    enabled: false, bands: Array(10).fill(0), preamp: 0, revision: 0, sample_rate: 48000,
    frequencies: [...EQ_FREQUENCIES], available_bands: Array(10).fill(true),
    response: Array.from({ length: 128 }, (_, index) => [20 * 1000 ** (index / 127), 0]),
    recommended_preamp: 0, peak: 0, overload_blocks: 0, fault: false, warning: null,
    presets: [{ name: 'Flat', factory: true }, { name: 'Evening', factory: false }], ...changes,
  }
}

describe('equalizer boundary', () => {
  it('projects only bounded display fields', () => {
    expect(projectEqualizer({ ...equalizerState(), private_path: 'hidden' })).toEqual(equalizerState())
    for (const changes of [{ bands: [1] }, { preamp: Infinity }, { revision: -1 }, { response: [] }, { presets: [{ name: '../bad', factory: false }] }]) {
      expect(projectEqualizer({ ...equalizerState(), ...changes })).toBeNull()
    }
  })
  it('rejects non-finite, unknown and expanded controls', () => {
    expect(validEqualizerIntent({ operation: 'band', revision: 1, frequency: 1000, gain: -12 })).toBe(true)
    for (const intent of [
      { operation: 'band', revision: 1, frequency: 1000, gain: NaN },
      { operation: 'band', revision: 1, frequency: 1001, gain: 1 },
      { operation: 'preamp', revision: 1, gain: -37 },
      { operation: 'reset', revision: 1, command: 'anything' },
      { operation: 'enabled', revision: 1, enabled: 1 },
      { operation: 'preset-save', revision: 1, name: '../file' },
    ]) expect(validEqualizerIntent(intent)).toBe(false)
  })
})
