export type DesktopDownloadJob = {
  job_id: string
  media_id: string
  state: 'queued' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
  format: 'mp3' | 'mp4'
  progress: number | null
  downloaded_bytes: number | null
  total_bytes: number | null
  speed_bytes_per_second: number | null
  eta_seconds: number | null
  error: string | null
}

const STATES = new Set(['queued', 'running', 'paused', 'completed', 'failed', 'cancelled'])
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const JOB_ID = /^[a-f0-9]{32}$/

function number(value: unknown, maximum: number): number | null | undefined {
  if (value === null) return null
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= maximum
    ? value : undefined
}

export function projectDesktopDownloads(value: unknown): DesktopDownloadJob[] | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const jobs = (value as Record<string, unknown>).jobs
  if (!Array.isArray(jobs) || jobs.length > 20) return null
  const projected: DesktopDownloadJob[] = []
  for (const raw of jobs) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
    const row = raw as Record<string, unknown>
    const progress = number(row.progress, 1)
    const downloaded = number(row.downloaded_bytes, 1e15)
    const total = number(row.total_bytes, 1e15)
    const speed = number(row.speed_bytes_per_second, 1e12)
    const eta = number(row.eta_seconds, 31_536_000)
    const error = row.error === null ? null : typeof row.error === 'string' && row.error.length <= 160
      && !/https?:|[A-Za-z]:[\\/]|\/home\/|\/Users\//.test(row.error) ? row.error : undefined
    if (typeof row.job_id !== 'string' || !JOB_ID.test(row.job_id)
      || typeof row.media_id !== 'string' || !ID.test(row.media_id)
      || !STATES.has(String(row.state)) || !['mp3', 'mp4'].includes(String(row.format))
      || progress === undefined || downloaded === undefined || total === undefined || speed === undefined
      || eta === undefined || error === undefined) return null
    projected.push({ job_id: row.job_id, media_id: row.media_id,
      state: row.state as DesktopDownloadJob['state'], format: row.format as DesktopDownloadJob['format'],
      progress, downloaded_bytes: downloaded, total_bytes: total, speed_bytes_per_second: speed,
      eta_seconds: eta, error })
  }
  return projected
}

export function activeDownload(jobs: DesktopDownloadJob[], mediaId: string | null | undefined, format: 'mp3' | 'mp4') {
  return jobs.find((job) => job.media_id === mediaId && job.format === format
    && ['queued', 'running', 'paused'].includes(job.state)) ?? null
}

export function formatTransfer(job: DesktopDownloadJob): string {
  const percent = job.progress === null ? 'Preparing' : `${Math.round(job.progress * 100)}%`
  const speed = job.speed_bytes_per_second === null ? '' : ` · ${(job.speed_bytes_per_second / 1_000_000).toFixed(1)} MB/s`
  return `${percent}${speed}`
}
