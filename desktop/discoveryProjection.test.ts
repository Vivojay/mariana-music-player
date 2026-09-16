import { describe, expect, it } from 'vitest'
import {
  durableArtworkStatus,
  durableHomepageProjection,
  projectArtworkStatus,
  projectHomepage,
  validArtworkCacheKey,
} from './discoveryProjection'
import type { HomepageProjection } from './shared'

const homepage = (): HomepageProjection => ({
  schema_version: 2,
  show_on_startup: true,
  online_enabled: false,
  state: 'offline',
  refreshed_at: null,
  safe_message: 'Online discovery is off',
  sections: [{
    key: 'library',
    title: 'Your library',
    items: [{
      id: 'library-summary',
      title: '12 indexed tracks',
      summary: 'Ready offline',
      source: 'Mariana library',
      published_at: null,
      link: null,
      image_key: null,
      image_mime: null,
    }],
  }],
})

describe('discovery projections', () => {
  it('accepts exact official destinations without granting arbitrary links on those sites', () => {
    const value = homepage()
    for (const link of [
      'https://www.billboard.com/charts/',
      'https://www.abc.net.au/triplej/programs/like-a-version',
      'https://www.bookclub.radio/',
      'https://www.kexp.org/podcasts/live-on-kexp/',
      'https://sxsw.com/',
      'https://www.bravotv.com/vanderpump-rules',
      'https://www.bravotv.com/',
      'https://www.hayu.com/',
    ]) {
      value.sections[0].items[0].link = link
      expect(projectHomepage(value)?.sections[0].items[0].link).toBe(link)
    }
    for (const link of [
      'https://www.billboard.com/redirect?target=https://private.invalid',
      'https://www.abc.net.au/triplej/programs/like-a-version?token=private',
      'https://www.bookclub.radio/?token=private',
      'https://sxsw.com/press-images/',
      'https://www.kexp.org/podcasts/live-on-kexp/#tracking',
      'https://www.bookclub.radio.evil.invalid/',
      'https://user:password@www.bookclub.radio/',
      'https://www.bookclub.radio:444/',
    ]) {
      value.sections[0].items[0].link = link
      expect(projectHomepage(value)).toBeNull()
    }
  })

  it('accepts bounded homepage content and strips link fragments', () => {
    const value = homepage()
    value.online_enabled = true
    value.state = 'ready'
    value.sections[0].items[0].link = 'https://daily.bandcamp.com/features/example#tracking'
    expect(projectHomepage(value)).toMatchObject({
      show_on_startup: true,
      online_enabled: true,
      state: 'ready',
      sections: [{ items: [{ link: 'https://daily.bandcamp.com/features/example' }] }],
    })
  })

  it('accepts only internally cached homepage images with matching types', () => {
    const key = `${'b'.repeat(64)}.webp`
    const value = homepage()
    value.sections[0].items[0].image_key = key
    value.sections[0].items[0].image_mime = 'image/webp'
    expect(projectHomepage(value)?.sections[0].items[0]).toMatchObject({
      image_key: key,
      image_mime: 'image/webp',
    })

    value.sections[0].items[0].image_mime = 'image/png'
    expect(projectHomepage(value)).toBeNull()
    const exposed = homepage()
    expect(projectHomepage({
      ...exposed,
      sections: [{
        ...exposed.sections[0],
        items: [{ ...exposed.sections[0].items[0], image_url: 'https://f4.bcbits.com/img/private.jpg' }],
      }],
    })).toBeNull()
  })

  it('allows only canonical Bandcamp Daily article links', () => {
    const tracked = homepage()
    tracked.sections[0].items[0].link = 'https://daily.bandcamp.com/features/example?token=private#tracking'
    expect(projectHomepage(tracked)?.sections[0].items[0].link).toBe(
      'https://daily.bandcamp.com/features/example',
    )
    for (const link of [
      'http://daily.bandcamp.com/features/example',
      'https://example.invalid/features/example',
      'https://daily.bandcamp.com:444/features/example',
      'https://user:password@daily.bandcamp.com/features/example',
    ]) {
      const value = homepage()
      value.sections[0].items[0].link = link
      expect(projectHomepage(value)).toBeNull()
    }
  })

  it('allows only canonical MusicBrainz release links for release cards', () => {
    const value = homepage()
    value.sections[0].items[0].link = 'https://musicbrainz.org/release/1f1db316-8361-4a40-9633-550b259642f5?tracking=drop#fragment'
    expect(projectHomepage(value)?.sections[0].items[0].link).toBe(
      'https://musicbrainz.org/release/1f1db316-8361-4a40-9633-550b259642f5',
    )
    value.sections[0].items[0].link = 'https://musicbrainz.org/artist/1f1db316-8361-4a40-9633-550b259642f5'
    expect(projectHomepage(value)).toBeNull()
  })

  it('rejects unknown, malformed, private, and oversized homepage fields', () => {
    expect(projectHomepage({ ...homepage(), private_path: 'C:\\Music\\secret.flac' })).toBeNull()
    const leaked = homepage()
    leaked.sections[0].items[0].summary = 'Fetched from C:\\private\\feed.json'
    expect(projectHomepage(leaked)).toBeNull()
    const posixLeak = homepage()
    posixLeak.sections[0].items[0].summary = 'Fetched from /mnt/private/feed.json'
    expect(projectHomepage(posixLeak)).toBeNull()
    const serviceLeak = homepage()
    serviceLeak.safe_message = 'Cache failed at /srv/mariana/feed.json'
    expect(projectHomepage(serviceLeak)).toBeNull()
    const invalidLink = homepage()
    invalidLink.sections[0].items[0].link = 'file:///private/feed.xml'
    expect(projectHomepage(invalidLink)).toBeNull()
    expect(projectHomepage({ ...homepage(), sections: Array.from({ length: 13 }, () => homepage().sections[0]) })).toBeNull()
  })

  it('accepts only internally addressable artwork status', () => {
    const key = `${'a'.repeat(64)}.jpg`
    expect(projectArtworkStatus({
      schema_version: 1,
      media_id: 'track-1',
      state: 'ready',
      available: true,
      automatic_online: false,
      cache_key: key,
      mime_type: 'image/jpeg',
      source: 'embedded',
      unavailable_reason: null,
    })).toMatchObject({ cache_key: key, source: 'embedded' })
    expect(validArtworkCacheKey(key)).toBe(true)
    expect(validArtworkCacheKey('../cover.jpg')).toBe(false)
    expect(projectArtworkStatus({
      schema_version: 1,
      media_id: 'track-1',
      state: 'ready',
      available: true,
      automatic_online: false,
      cache_key: key,
      mime_type: 'image/png',
      source: 'embedded',
      unavailable_reason: null,
    })).toBeNull()
  })

  it('rejects artwork paths, URLs, invalid availability, and private diagnostics', () => {
    const base = {
      schema_version: 1,
      media_id: 'track-1',
      state: 'unavailable',
      available: false,
      automatic_online: false,
      cache_key: null,
      mime_type: null,
      source: null,
      unavailable_reason: 'No supported artwork is available',
    }
    expect(projectArtworkStatus({ ...base, cache_key: 'C:\\cover.jpg' })).toBeNull()
    expect(projectArtworkStatus({ ...base, available: true })).toBeNull()
    expect(projectArtworkStatus({ ...base, unavailable_reason: 'Failed at https://signed.invalid/a?token=x' })).toBeNull()
    expect(projectArtworkStatus({ ...base, resolver: 'secret' })).toBeNull()
  })

  it('removes one-shot UI intents from durable snapshot projections', () => {
    expect(durableHomepageProjection({ ...homepage(), open_requested: true })).not.toHaveProperty('open_requested')
    const artwork = projectArtworkStatus({
      schema_version: 1,
      media_id: null,
      state: 'idle',
      available: false,
      automatic_online: false,
      cache_key: null,
      mime_type: null,
      source: null,
      unavailable_reason: null,
      show_requested: true,
    })
    expect(artwork).not.toBeNull()
    expect(durableArtworkStatus(artwork as NonNullable<typeof artwork>)).not.toHaveProperty('show_requested')
  })
})
