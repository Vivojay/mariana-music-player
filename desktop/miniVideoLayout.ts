import type { LocalVideoStatus } from './localVideo.js'

export function hasCurrentVideo(ready: boolean, mediaId: string | null | undefined, video: LocalVideoStatus | null | undefined): boolean {
  return Boolean(ready && mediaId && video?.media_id === mediaId && video.state !== 'off')
}

export function miniWindowGeometry(video: boolean) {
  return video
    ? { width: 480, height: 400, minWidth: 340, minHeight: 300, maxWidth: 1920, maxHeight: 1080, resizable: true }
    : { width: 400, height: 172, minWidth: 340, minHeight: 150, maxWidth: 600, maxHeight: 240, resizable: false }
}
