import type { HomepageItem } from './shared'

/** Search only the cards already supplied by the backend; never a remote API. */
export function homepageSearch(query: string): (item: HomepageItem) => boolean {
  if (query.length > 512) throw new Error('Search must be 512 characters or fewer')
  if ((query.match(/"/g)?.length ?? 0) % 2) throw new Error('Close the quoted search phrase')
  const terms = (query.match(/(?:[^\s"]|"[^"]*")+/g) ?? []).map((term) => term.replaceAll('"', ''))
  const fields = new Set(['title', 'creator', 'programme', 'provider', 'language', 'region', 'category', 'after', 'before'])
  for (const term of terms) {
    if (term.includes(':') && !fields.has(term.split(':')[0].toLowerCase())) throw new Error('Unknown search field')
  }
  return (item) => {
    const values: Record<string, string> = {
      title: item.title, creator: item.source, provider: item.source,
      programme: item.catalogue?.kind === 'programme' ? item.title : '',
      language: item.catalogue?.language ?? '', region: item.catalogue?.region ?? '',
      category: item.catalogue?.category ?? '',
    }
    const all = `${Object.values(values).join(' ')} ${item.summary ?? ''}`.toLocaleLowerCase()
    return terms.every((term) => {
      const colon = term.indexOf(':')
      if (colon < 0) return all.includes(term.toLocaleLowerCase())
      const field = term.slice(0, colon).toLowerCase()
      const value = term.slice(colon + 1).toLocaleLowerCase()
      if (field === 'after' || field === 'before') {
        const date = item.published_at ? Date.parse(item.published_at) : Number.NaN
        const bound = Date.parse(value)
        return Number.isFinite(date) && Number.isFinite(bound) && (field === 'after' ? date >= bound : date <= bound)
      }
      return Boolean(values[field]) && values[field].toLocaleLowerCase().includes(value)
    })
  }
}
