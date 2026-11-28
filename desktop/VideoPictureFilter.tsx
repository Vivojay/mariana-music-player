import { createElement, useId, type ReactElement } from 'react'
import type { PictureFilter } from './localVideo'
import presetsJSON from '../mariana/video_filters.json'
import '../web/player/video-filters.js'

type FilterSpec = { label: string; kind: string; matrix?: number[]; low?: number[]; high?: number[] }
type FilterElement = { tag: string; attributes: Record<string, string>; children?: FilterElement[] }
const browserFilters = (globalThis as typeof globalThis & {
  MarianaVideo: { directive(spec: FilterSpec, threshold: number): { space: 'linearRGB' | 'sRGB'; elements: FilterElement[] } }
}).MarianaVideo

export const picturePresets = presetsJSON as Record<string, FilterSpec>
export const originalPicture: PictureFilter = { preset: 'off', threshold: 50 }

function filterElement(description: FilterElement, key: number): ReactElement {
  return createElement(description.tag, { ...description.attributes, key }, description.children?.map(filterElement))
}

export function usePictureFilter(selection = originalPicture) {
  const id = `mariana-picture-${useId().replace(/[^\w-]/g, '')}`
  const spec = Object.prototype.hasOwnProperty.call(picturePresets, selection.preset) ? picturePresets[selection.preset] : undefined
  if (!spec || spec.kind === 'identity') return { url: undefined, definition: null }
  const filter = browserFilters.directive(spec, selection.threshold)
  return {
    url: `url(#${id})`,
    definition: <svg aria-hidden="true" width="0" height="0" style={{ position: 'absolute', pointerEvents: 'none' }}>
      <defs><filter id={id} colorInterpolationFilters={filter.space}>{filter.elements.map(filterElement)}</filter></defs>
    </svg>,
  }
}
