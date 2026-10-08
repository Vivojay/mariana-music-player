import { describe, expect, it } from 'vitest'
import { activeDownload, formatTransfer, projectDesktopDownloads } from './downloadProjection'

const valid = {
  job_id: 'a'.repeat(32), media_id: 'media-1', state: 'running', format: 'mp4', progress: 0.25,
  downloaded_bytes: 250, total_bytes: 1000, speed_bytes_per_second: 1_500_000,
  eta_seconds: 5, error: null,
}

describe('desktop download projection', () => {
  it('allows only bounded display metrics and finds matching active work', () => {
    const jobs = projectDesktopDownloads({ jobs: [valid] })
    expect(jobs).toEqual([valid])
    expect(activeDownload(jobs!, 'media-1', 'mp4')).toEqual(valid)
    expect(activeDownload(jobs!, 'media-1', 'mp3')).toBeNull()
    expect(formatTransfer(jobs![0])).toBe('25% · 1.5 MB/s')
  })

  it.each([
    { ...valid, job_id: '../private' },
    { ...valid, media_id: 'https://private.test/media' },
    { ...valid, progress: 2 },
    { ...valid, speed_bytes_per_second: Number.POSITIVE_INFINITY },
    { ...valid, error: 'C:\\Users\\Name\\private.mp4' },
  ])('rejects malformed, private, or over-broad rows %#', (row) => {
    expect(projectDesktopDownloads({ jobs: [row] })).toBeNull()
  })

  it('handles empty and preparing states safely', () => {
    expect(projectDesktopDownloads({ jobs: [] })).toEqual([])
    const preparing = { ...valid, progress: null, speed_bytes_per_second: null }
    expect(formatTransfer(projectDesktopDownloads({ jobs: [preparing] })![0])).toBe('Preparing')
  })

  it('drops unknown backend fields rather than projecting private internals', () => {
    const jobs = projectDesktopDownloads({ jobs: [{ ...valid, path: 'C:\\private.mp4', url: 'https://private.test' }] })
    expect(jobs).toEqual([valid])
    expect(jobs![0]).not.toHaveProperty('path')
    expect(jobs![0]).not.toHaveProperty('url')
  })
})
