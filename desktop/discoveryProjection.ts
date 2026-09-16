import type { ArtworkStatus, DiscoveryCandidate, DiscoverySelection, DiscoveryTrack, HomepageItem, HomepageProjection, HomepageSection } from './shared.js'

const PRIVATE_TEXT = /(?:https?:\/\/|[a-z]:[\\/]|\\\\|(?:^|\s)~?\/[a-z0-9._~-]+(?:[\\/][^\s]*)?|\b(?:authorization|bearer|cookie|credential|password|private[_ -]?id|resolver)\b)/i
const ARTWORK_KEY = /^[a-f0-9]{64}\.(?:jpg|png|webp)$/
const PUBLIC_MEDIA_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const HOMEPAGE_STATES = new Set(['offline', 'loading', 'ready', 'stale', 'partial', 'error'])
const ARTWORK_STATES = new Set(['idle', 'loading', 'ready', 'unavailable', 'error', 'disabled'])
const ARTWORK_SOURCES = new Set(['embedded', 'adjacent', 'cache', 'provider'])
const ARTWORK_MIMES = new Set(['image/jpeg', 'image/png', 'image/webp'])
// Exact destinations only: adding a site does not grant arbitrary links on it.
const OFFICIAL_DESTINATIONS = new Set([
  'https://somafm.com/groovesalad/',
  'https://somafm.com/secretagent/',
  'https://www.wfmu.org/audiostream.shtml',
  'https://www.wbur.org/podcasts/circleround',
  'https://www.deutschlandfunk.de/kulturfragen-100.html',
  'https://www.grammy.com/news',
  'https://sxsw.com/',
  'https://pitchfork.com/',
  'https://playbill.com/',
  'https://www.bfi.org.uk/sight-and-sound',
  'https://indianexpress.com/section/entertainment/',
  'https://www.comic-con.org/',
  'https://www.billboard.com/charts/',
  'https://www.abc.net.au/triplej/programs/like-a-version',
  'https://www.officialcharts.com/charts/',
  'https://www.ifpi.org/our-industry/global-charts/',
  'https://boilerroom.tv/',
  'https://www.bookclub.radio/',
  'https://www.kexp.org/podcasts/live-on-kexp/',
  'https://www.nts.live/',
  'https://colorsxstudios.com/',
  'https://www.cercle.io/',
  'https://linktr.ee/elevatormusiclive',
  'https://www.bravotv.com/vanderpump-rules',
  'https://www.bravotv.com/',
  'https://www.hayu.com/',
])

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function exactKeys(value: Record<string, unknown>, allowed: Set<string>): boolean {
  return Object.keys(value).every((key) => allowed.has(key))
}

function safeText(
  value: unknown,
  maximum: number,
  { optional = false }: { optional?: boolean } = {},
): string | null | undefined {
  if (value === null && optional) return null
  if (typeof value !== 'string') return undefined
  const text = value.replace(/\s+/g, ' ').trim()
  if (!text || text.length > maximum || PRIVATE_TEXT.test(text)) return undefined
  if (Array.from(text).some((character) => {
    const code = character.charCodeAt(0)
    return code < 32 || code === 127
  })) return undefined
  return text
}

function safeLink(value: unknown): string | null | undefined {
  if (value === null) return null
  if (typeof value !== 'string' || value.length > 2_048) return undefined
  try {
    const url = new URL(value)
    const officialDestination = OFFICIAL_DESTINATIONS.has(url.toString())
    const bandcampArticle = url.hostname === 'daily.bandcamp.com' && url.pathname.startsWith('/')
    const musicbrainzRelease = url.hostname === 'musicbrainz.org'
      && /^\/release\/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(url.pathname)
    if (url.protocol !== 'https:' || (!bandcampArticle && !musicbrainzRelease && !officialDestination)
      || (url.port && url.port !== '443') || url.username || url.password) return undefined
    url.search = ''
    url.hash = ''
    return url.toString()
  } catch {
    return undefined
  }
}

function projectHomepageItem(value: unknown): HomepageItem | null {
  const item = record(value)
  if (!item || !exactKeys(item, new Set([
    'id', 'title', 'summary', 'source', 'published_at', 'link', 'image_key', 'image_mime', 'catalogue',
  ]))) return null
  const id = safeText(item.id, 128)
  const title = safeText(item.title, 240)
  const summary = safeText(item.summary, 500, { optional: true })
  const source = safeText(item.source, 80)
  const publishedAt = safeText(item.published_at, 64, { optional: true })
  const link = safeLink(item.link)
  const imageKey = item.image_key
  const imageMime = item.image_mime
  let catalogue: HomepageItem['catalogue']
  if (item.catalogue !== undefined) {
    const metadata = record(item.catalogue)
    const keys = ['language', 'region', 'category', 'kind', 'health', 'validated_at']
    if (!metadata || !exactKeys(metadata, new Set(keys)) || keys.some((key) => !safeText(metadata[key], 100))
      || !['programme', 'station'].includes(String(metadata.kind)) || !String(id).startsWith('catalogue:')) return null
    catalogue = metadata as HomepageItem['catalogue']
  }
  if (typeof id !== 'string' || typeof title !== 'string' || typeof source !== 'string' || summary === undefined
      || publishedAt === undefined || link === undefined) return null
  if (imageKey !== null && (typeof imageKey !== 'string' || !ARTWORK_KEY.test(imageKey))) return null
  if (imageMime !== null && (typeof imageMime !== 'string' || !ARTWORK_MIMES.has(imageMime))) return null
  if ((imageKey === null) !== (imageMime === null)) return null
  if (typeof imageKey === 'string' && typeof imageMime === 'string') {
    const expectedMime = imageKey.endsWith('.jpg')
      ? 'image/jpeg'
      : imageKey.endsWith('.png')
        ? 'image/png'
        : 'image/webp'
    if (imageMime !== expectedMime) return null
  }
  return {
    id,
    title,
    summary,
    source,
    published_at: publishedAt,
    link,
    image_key: imageKey as HomepageItem['image_key'],
    image_mime: imageMime as HomepageItem['image_mime'],
    ...(catalogue ? { catalogue } : {}),
  }
}

function projectHomepageSection(value: unknown): HomepageSection | null {
  const section = record(value)
  if (!section || !exactKeys(section, new Set(['key', 'title', 'items']))) return null
  const key = safeText(section.key, 64)
  const title = safeText(section.title, 100)
  if (typeof key !== 'string' || typeof title !== 'string' || !Array.isArray(section.items) || section.items.length > 30) return null
  const items = section.items.map(projectHomepageItem)
  if (items.some((item) => item === null)) return null
  return { key, title, items: items as HomepageItem[] }
}

export function projectHomepage(value: unknown): HomepageProjection | null {
  const source = record(value)
  const allowed = new Set([
    'schema_version', 'show_on_startup', 'online_enabled', 'state', 'refreshed_at',
    'safe_message', 'sections', 'open_requested',
  ])
  if (!source || !exactKeys(source, allowed) || source.schema_version !== 2) return null
  if (typeof source.show_on_startup !== 'boolean' || typeof source.online_enabled !== 'boolean') return null
  if (typeof source.state !== 'string' || !HOMEPAGE_STATES.has(source.state)) return null
  if (source.refreshed_at !== null && (
    typeof source.refreshed_at !== 'number'
    || !Number.isFinite(source.refreshed_at)
    || source.refreshed_at < 0
    || source.refreshed_at > 4_102_444_800
  )) return null
  const message = safeText(source.safe_message, 240, { optional: true })
  if (message === undefined || !Array.isArray(source.sections) || source.sections.length > 12) return null
  const sections = source.sections.map(projectHomepageSection)
  if (sections.some((section) => section === null)) return null
  const projectedSections = sections as HomepageSection[]
  if (new Set(projectedSections.map((section) => section.key)).size !== projectedSections.length) return null
  const itemIds = projectedSections.flatMap((section) => section.items.map((item) => item.id))
  if (new Set(itemIds).size !== itemIds.length) return null
  if (source.open_requested !== undefined && typeof source.open_requested !== 'boolean') return null
  return {
    schema_version: 2,
    show_on_startup: source.show_on_startup,
    online_enabled: source.online_enabled,
    state: source.state as HomepageProjection['state'],
    refreshed_at: source.refreshed_at,
    safe_message: message,
    sections: projectedSections,
    ...(source.open_requested === undefined ? {} : { open_requested: source.open_requested }),
  }
}

export function projectArtworkStatus(value: unknown): ArtworkStatus | null {
  const source = record(value)
  const allowed = new Set([
    'schema_version', 'media_id', 'state', 'available', 'automatic_online', 'cache_key',
    'mime_type', 'source', 'unavailable_reason', 'show_requested',
  ])
  if (!source || !exactKeys(source, allowed) || source.schema_version !== 1) return null
  if (source.media_id !== null && (typeof source.media_id !== 'string' || !PUBLIC_MEDIA_ID.test(source.media_id))) return null
  if (typeof source.state !== 'string' || !ARTWORK_STATES.has(source.state)) return null
  if (typeof source.available !== 'boolean' || typeof source.automatic_online !== 'boolean') return null
  if (source.cache_key !== null && (typeof source.cache_key !== 'string' || !ARTWORK_KEY.test(source.cache_key))) return null
  if (source.mime_type !== null && (typeof source.mime_type !== 'string' || !ARTWORK_MIMES.has(source.mime_type))) return null
  if (source.source !== null && (typeof source.source !== 'string' || !ARTWORK_SOURCES.has(source.source))) return null
  const reason = safeText(source.unavailable_reason, 200, { optional: true })
  if (reason === undefined || (source.show_requested !== undefined && typeof source.show_requested !== 'boolean')) return null
  if (source.available && (!source.cache_key || !source.mime_type || !source.source || !source.media_id)) return null
  if (!source.available && (source.cache_key !== null || source.mime_type !== null || source.source !== null)) return null
  if (source.available !== (source.state === 'ready')) return null
  if (source.cache_key && source.mime_type) {
    const expectedMime = source.cache_key.endsWith('.jpg')
      ? 'image/jpeg'
      : source.cache_key.endsWith('.png')
        ? 'image/png'
        : 'image/webp'
    if (source.mime_type !== expectedMime) return null
  }
  return {
    schema_version: 1,
    media_id: source.media_id,
    state: source.state as ArtworkStatus['state'],
    available: source.available,
    automatic_online: source.automatic_online,
    cache_key: source.cache_key,
    mime_type: source.mime_type as ArtworkStatus['mime_type'],
    source: source.source as ArtworkStatus['source'],
    unavailable_reason: reason,
    ...(source.show_requested === undefined ? {} : { show_requested: source.show_requested }),
  }
}

export function durableHomepageProjection(value: HomepageProjection): HomepageProjection {
  const durable = { ...value }
  delete durable.open_requested
  return durable
}

export function durableArtworkStatus(value: ArtworkStatus): ArtworkStatus {
  const durable = { ...value }
  delete durable.show_requested
  return durable
}

export function validArtworkCacheKey(value: unknown): value is string {
  return typeof value === 'string' && ARTWORK_KEY.test(value)
}

export function validSelectionHandle(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{32}$/.test(value)
}

export function projectDiscoverySelection(value: unknown): DiscoverySelection | null {
  const data = record(value)
  if (!data || !exactKeys(data, new Set([
    'schema_version', 'request_id', 'revision', 'item_id', 'state', 'title', 'artist',
    'tracks', 'candidates', 'message', 'page', 'has_more',
  ])) || data.schema_version !== 1 || !validSelectionHandle(data.request_id)) return null
  if (typeof data.revision !== 'number' || !Number.isSafeInteger(data.revision) || data.revision < 1) return null
  if (typeof data.item_id !== 'string' || !/^(release|catalogue):/.test(data.item_id) || !safeText(data.item_id, 128)) return null
  if (data.page !== undefined && (!Number.isSafeInteger(data.page) || Number(data.page) < 0 || Number(data.page) > 7)) return null
  if (data.has_more !== undefined && typeof data.has_more !== 'boolean') return null
  if (typeof data.state !== 'string' || !['loading', 'tracks', 'choices', 'working', 'complete', 'error', 'closed'].includes(data.state)) return null
  const title = safeText(data.title, 240)
  const artist = safeText(data.artist, 160, { optional: true })
  const message = safeText(data.message, 240, { optional: true })
  if (!title || artist === undefined || message === undefined) return null
  if (!Array.isArray(data.tracks) || data.tracks.length > 100 || !Array.isArray(data.candidates) || data.candidates.length > 15) return null
  const projectRow = (raw: unknown, candidate: boolean): DiscoveryTrack | DiscoveryCandidate | null => {
    const row = record(raw)
    if (!row || !exactKeys(row, new Set([
      'id', 'title', 'artist', 'duration', ...(candidate ? ['source', 'match', 'playable', 'published_at', 'explicit'] : ['position']),
    ])) || !validSelectionHandle(row.id)) return null
    const rowTitle = safeText(row.title, 240)
    const rowArtist = safeText(row.artist, 160)
    if (!rowTitle || !rowArtist) return null
    if (row.duration !== null && (typeof row.duration !== 'number' || !Number.isFinite(row.duration)
      || row.duration <= 0 || row.duration > 604800)) return null
    const base = { id: row.id, title: rowTitle, artist: rowArtist, duration: row.duration as number | null }
    if (candidate) {
      if (typeof row.source !== 'string' || !['local', 'youtube', 'podcast', 'radio'].includes(row.source) || typeof row.playable !== 'boolean'
        || typeof row.match !== 'string' || !['recording-id', 'metadata', 'provider-result', 'published-media'].includes(row.match)) return null
      if (row.published_at !== undefined && !safeText(row.published_at, 100)) return null
      if (row.explicit !== undefined && typeof row.explicit !== 'boolean') return null
      return { ...base, source: row.source as DiscoveryCandidate['source'], match: row.match as DiscoveryCandidate['match'], playable: row.playable,
        ...(row.published_at === undefined ? {} : { published_at: row.published_at as string }),
        ...(row.explicit === undefined ? {} : { explicit: row.explicit as boolean }) }
    }
    if (typeof row.position !== 'number' || !Number.isInteger(row.position) || row.position < 1 || row.position > 100) return null
    return { ...base, position: row.position }
  }
  const tracks = data.tracks.map((row) => projectRow(row, false))
  const candidates = data.candidates.map((row) => projectRow(row, true))
  const rows = [...tracks, ...candidates]
  if (rows.some((row) => row === null) || new Set(rows.map((row) => row?.id)).size !== rows.length) return null
  return {
    schema_version: 1, request_id: data.request_id, revision: data.revision, item_id: data.item_id,
    state: data.state as DiscoverySelection['state'], title, artist, message,
    tracks: tracks as DiscoveryTrack[], candidates: candidates as DiscoveryCandidate[],
    ...(data.page === undefined ? {} : { page: data.page as number }),
    ...(data.has_more === undefined ? {} : { has_more: data.has_more as boolean }),
  }
}
