/** Desktop interaction preference, independent of backend command-seek policy. */
export const SNAP_CHAPTERS_KEY = 'mariana.seek.snapChapters'

export function readChapterSnapping(): boolean {
  try {
    return localStorage.getItem(SNAP_CHAPTERS_KEY) === 'true'
  } catch {
    return false
  }
}

export function saveChapterSnapping(enabled: boolean): boolean {
  try {
    localStorage.setItem(SNAP_CHAPTERS_KEY, String(enabled))
    return true
  } catch {
    return false
  }
}
