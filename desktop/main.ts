import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, nativeImage, protocol, shell, Tray } from 'electron'
import electronUpdater from 'electron-updater'
import { createHash, randomBytes } from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import * as pty from 'node-pty'
import { projectCommandCatalog, validateCommandCatalogOptions } from './commandCatalog.js'
import { projectEqualizer, validEqualizerIntent, type EqualizerState } from './equalizer.js'
import { acceptPlaybackStatusEvent } from './playbackProjection.js'
import { validateSeekIntent } from './playbackSeek.js'
import { projectLocalVideo, type LocalVideoStatus } from './localVideo.js'
import { projectHostVideoResource, serveLocalVideo, serveSourceVideo, type HostVideoResource } from './localVideoProtocol.js'
import { hasCurrentVideo, miniWindowGeometry } from './miniVideoLayout.js'
import { projectFocusRecovery, type FocusRecovery } from './focusRecovery.js'
import { projectPlaybackHotspots } from './playbackHotspots.js'
import {
  durableArtworkStatus,
  durableHomepageProjection,
  projectArtworkStatus,
  projectDiscoverySelection,
  projectHomepage,
  validArtworkCacheKey,
  validSelectionHandle,
} from './discoveryProjection.js'
import { shouldDeliverMiniSnapshot } from './miniPlayerUpdates.js'
import {
  durableStrudelProjection,
  projectStrudelProjection,
  strudelRenderedFilesToPrune,
  validStrudelPreviewInput,
  validStrudelSaveInput,
  type StrudelPreviewInput,
  type StrudelProjection,
} from './strudelProjects.js'
import { StrudelRenderLifecycle, type StrudelRenderTask } from './strudelRenderLifecycle.js'
import type {
  BackendEvent,
  CommandCatalogOptions,
  CommandCatalogResult,
  ArtworkDataResult,
  ArtworkStatus,
  DesktopControlResult,
  MiniPlayerSnapshot,
  PlaybackHotspots,
  HomepageProjection,
  DiscoverySelection,
  PlaybackStatus,
  UpdateState,
} from './shared.js'
import {
  createTrayActions,
  ensureSingleWindow,
  ensureSingleTray,
  handleAuxiliaryWindowClose,
  handleWindowClose,
  normalizeCloseButtonBehavior,
  showWindow,
  type CloseButtonBehavior,
} from './windowLifecycle.js'

const { autoUpdater } = electronUpdater

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(__dirname, '..')
const isDevelopment = !app.isPackaged
const usesViteRenderer = isDevelopment && process.env.MARIANA_E2E_USE_DIST !== '1'
protocol.registerSchemesAsPrivileged([
  { scheme: 'mariana-video', privileges: { standard: true, secure: true, stream: true } },
])
if (process.env.MARIANA_E2E === '1') {
  app.setPath(
    'userData',
    process.env.MARIANA_E2E_DATA_DIR || path.join(app.getPath('temp'), `mariana-e2e-${process.pid}`),
  )
}
const controlToken = randomBytes(32).toString('hex')
const controlEndpoint = process.platform === 'win32'
  ? `\\\\.\\pipe\\mariana-${process.pid}-${randomBytes(8).toString('hex')}`
  : path.join(app.getPath('temp'), `mariana-${process.pid}-${randomBytes(8).toString('hex')}.sock`)

let mainWindow: BrowserWindow | null = null
let miniPlayerWindow: BrowserWindow | null = null
let videoWindow: BrowserWindow | null = null
let strudelRenderWindow: BrowserWindow | null = null
let strudelRenderLoad: Promise<void> | null = null
let strudelProjection: StrudelProjection | null = null
let focusRecovery: FocusRecovery | null = null
let playbackHotspots: PlaybackHotspots | null = null
let hotspotRefreshTimer: NodeJS.Timeout | null = null
let homepageProjection: HomepageProjection | null = null
let discoverySelection: DiscoverySelection | null = null
let artworkStatus: ArtworkStatus | null = null
let terminalProcess: pty.IPty | null = null
let controlServer: net.Server | null = null
let controlSocket: net.Socket | null = null
let tray: Tray | null = null
let trayAvailable = false
let closeButtonBehavior: CloseButtonBehavior = 'tray'
let desktopNotice: string | null = null
let terminalHistory = ''
let terminalControlTail = ''
let quitting = false
let playbackState = 'idle'
let playbackStatus: PlaybackStatus | null = null
let playbackEventTimestamp: number | null = null
let localVideoStatus: LocalVideoStatus | null = null
let hostVideoResource: HostVideoResource | null = null
let localVideoTimestamp: number | null = null
let miniVideoMode = false
let equalizerProjection: EqualizerState | null = null
let sleepActive = false
let backendReady = false
let backendShutdownAcknowledged = false
let backendExitClosesView = true
let backendSafeOverride: boolean | null = null
let backendDiagnostic: string | null = null
let updateState: UpdateState = { state: app.isPackaged ? 'idle' : 'disabled' }
let updatePreparationTimer: NodeJS.Timeout | null = null
let backendStartupTimer: NodeJS.Timeout | null = null
const pendingControlRequests = new Map<string, {
  resolve: (result: DesktopControlResult) => void
  timer: NodeJS.Timeout
  safeError: string
  interrupted: string
}>()
const strudelRenders = new StrudelRenderLifecycle<BrowserWindow>(discardStrudelRenderWindow)
const pendingCommandCatalogRequests = new Map<string, {
  resolve: (result: CommandCatalogResult) => void
  timer: NodeJS.Timeout
}>()

type ControlRequestMessages = {
  timeout: string
  send: string
  safeError: string
  interrupted: string
}

const favoriteControlMessages: ControlRequestMessages = {
  timeout: 'Mariana backend did not confirm the favourite update',
  send: 'Could not send the favourite update',
  safeError: 'Favourite update failed',
  interrupted: 'Mariana backend interrupted the favourite update',
}

const playbackControlMessages: ControlRequestMessages = {
  timeout: 'Mariana backend did not confirm the playback control',
  send: 'Could not send the playback control',
  safeError: 'Playback control failed',
  interrupted: 'Mariana backend interrupted the playback control',
}

const seekControlMessages: ControlRequestMessages = {
  timeout: 'Mariana backend did not confirm the seek',
  send: 'Could not send the seek',
  safeError: 'Seek failed',
  interrupted: 'Mariana backend interrupted the seek',
}

const homepageControlMessages: ControlRequestMessages = {
  timeout: 'Mariana backend did not confirm the homepage update',
  send: 'Could not send the homepage update',
  safeError: 'Homepage update failed',
  interrupted: 'Mariana backend interrupted the homepage update',
}

const artworkControlMessages: ControlRequestMessages = {
  timeout: 'Mariana backend did not confirm the artwork update',
  send: 'Could not send the artwork update',
  safeError: 'Artwork update failed',
  interrupted: 'Mariana backend interrupted the artwork update',
}

const safeToInstall = () => (
  backendSafeOverride ?? (['idle', 'paused', 'failed'].includes(playbackState) && !sleepActive)
)

const send = <T>(channel: string, value: T) => {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, value)
}

const miniPlayerSnapshot = (): MiniPlayerSnapshot => ({
  ready: backendReady,
  diagnostic: backendDiagnostic,
  playback: playbackStatus,
  video: hasCurrentVideo(backendReady, playbackStatus?.media_id, localVideoStatus) ? localVideoStatus : null,
  videoTimestamp: localVideoTimestamp,
})

const sendMiniPlayerSnapshot = (event?: string) => {
  if (miniPlayerWindow && !miniPlayerWindow.isDestroyed()
    && shouldDeliverMiniSnapshot(miniPlayerWindow.isVisible(), miniPlayerWindow.isMinimized(), event)) {
    const videoMode = hasCurrentVideo(backendReady, playbackStatus?.media_id, localVideoStatus)
    if (videoMode !== miniVideoMode) {
      miniVideoMode = videoMode
      const geometry = miniWindowGeometry(videoMode)
      miniPlayerWindow.setResizable(true)
      if (videoMode) miniPlayerWindow.setMaximumSize(geometry.maxWidth, geometry.maxHeight)
      miniPlayerWindow.setMinimumSize(geometry.minWidth, geometry.minHeight)
      if (!videoMode) miniPlayerWindow.setMaximumSize(geometry.maxWidth, geometry.maxHeight)
      miniPlayerWindow.setSize(geometry.width, geometry.height)
      miniPlayerWindow.setResizable(geometry.resizable)
    }
    miniPlayerWindow.webContents.send('mini:snapshot-updated', miniPlayerSnapshot())
  }
}

const trayActions = createTrayActions(
  () => mainWindow,
  () => {
    quitting = true
    app.quit()
  },
)

function setDesktopNotice(message: string | null) {
  desktopNotice = message
  if (message) {
    send('backend:event', {
      event: 'desktop-notice',
      payload: { message },
      timestamp: Date.now() / 1000,
    } satisfies BackendEvent)
  }
}

function ensureTray(): boolean {
  if (tray) return true
  try {
    const iconPath = isDevelopment
      ? path.join(repositoryRoot, 'res', 'welcome_banner.png')
      : path.join(process.resourcesPath, 'tray-icon.png')
    const source = nativeImage.createFromPath(iconPath)
    if (source.isEmpty()) throw new Error('tray icon unavailable')
    const size = process.platform === 'darwin' ? 18 : process.platform === 'win32' ? 16 : 22
    tray = ensureSingleTray(tray, () => new Tray(source.resize({ width: size, height: size })))
    tray.setToolTip('Mariana')
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: 'Show Mariana', click: trayActions.show },
      { label: 'Hide Mariana', click: trayActions.hide },
      { type: 'separator' },
      { label: 'Quit', click: trayActions.quit },
    ]))
    tray.on('double-click', trayActions.show)
    trayAvailable = true
    setDesktopNotice(null)
    return true
  } catch {
    trayAvailable = false
    setDesktopNotice('System tray is unavailable; the close button will quit Mariana')
    return false
  }
}

const setUpdateState = (next: UpdateState) => {
  updateState = { ...next, safeToInstall: safeToInstall() }
  send('updates:state', updateState)
}

function validateSender(event: Electron.IpcMainEvent | Electron.IpcMainInvokeEvent): boolean {
  return Boolean(mainWindow && event.sender === mainWindow.webContents)
}

function validateMiniPlayerSender(event: Electron.IpcMainInvokeEvent): boolean {
  return Boolean(
    (miniPlayerWindow && event.sender === miniPlayerWindow.webContents)
    || (videoWindow && event.sender === videoWindow.webContents),
  )
}

function validControlMediaId(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= 256
    && !Array.from(value).some((character) => {
      const code = character.charCodeAt(0)
      return code < 32 || code === 127
    })
}

function safeControlError(value: unknown, fallback = favoriteControlMessages.safeError): string {
  const text = typeof value === 'string'
    ? Array.from(value, (character) => {
        const code = character.charCodeAt(0)
        return code < 32 || code === 127 ? ' ' : character
      }).join('').replace(/\s+/g, ' ').trim()
    : ''
  if (!text || /(?:https?:\/\/|[a-z]:[\\/]|\\\\|\b(?:cookie|token|secret|authorization)\b)/i.test(text)) {
    return fallback
  }
  return text.slice(0, 160)
}

function finishPendingControlRequests() {
  for (const { resolve, timer, interrupted } of pendingControlRequests.values()) {
    clearTimeout(timer)
    resolve({ ok: false, error: interrupted })
  }
  pendingControlRequests.clear()
  for (const { resolve, timer } of pendingCommandCatalogRequests.values()) {
    clearTimeout(timer)
    resolve({ ok: false, error: 'Mariana backend interrupted the command catalog request' })
  }
  pendingCommandCatalogRequests.clear()
  strudelRenders.interrupt()
}

function requestCommandCatalog(options: CommandCatalogOptions): Promise<CommandCatalogResult> {
  const socket = controlSocket
  if (!backendReady || !socket || socket.destroyed || !socket.writable) {
    return Promise.resolve({ ok: false, error: 'Mariana backend is unavailable' })
  }
  const requestId = randomBytes(16).toString('hex')
  const payload = {
    ...(options.includeCompatibility === undefined
      ? {}
      : { include_compatibility: options.includeCompatibility }),
    ...(options.typedPrefix === undefined ? {} : { typed_prefix: options.typedPrefix }),
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pendingCommandCatalogRequests.delete(requestId)
      resolve({ ok: false, error: 'Mariana backend did not return the command catalog' })
    }, 3_000)
    pendingCommandCatalogRequests.set(requestId, { resolve, timer })
    socket.write(`${JSON.stringify({
      token: controlToken,
      request_id: requestId,
      action: 'autocomplete.catalog',
      payload,
    })}\n`, (error) => {
      if (!error) return
      const pending = pendingCommandCatalogRequests.get(requestId)
      if (!pending) return
      clearTimeout(pending.timer)
      pendingCommandCatalogRequests.delete(requestId)
      pending.resolve({ ok: false, error: 'Could not request the command catalog' })
    })
  })
}

function requestBackendControl(
  action: string,
  payload: Record<string, unknown>,
  messages = favoriteControlMessages,
): Promise<DesktopControlResult> {
  const socket = controlSocket
  if (!backendReady || !socket || socket.destroyed || !socket.writable) {
    return Promise.resolve({ ok: false, error: 'Mariana backend is unavailable' })
  }
  const requestId = randomBytes(16).toString('hex')
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pendingControlRequests.delete(requestId)
      resolve({ ok: false, error: messages.timeout })
    }, 3_000)
    pendingControlRequests.set(requestId, {
      resolve,
      timer,
      safeError: messages.safeError,
      interrupted: messages.interrupted,
    })
    socket.write(`${JSON.stringify({ token: controlToken, request_id: requestId, action, payload })}\n`, (error) => {
      if (!error) return
      const pending = pendingControlRequests.get(requestId)
      if (!pending) return
      clearTimeout(pending.timer)
      pendingControlRequests.delete(requestId)
      pending.resolve({ ok: false, error: messages.send })
    })
  })
}

function scheduleHotspotRefresh(mediaId: string | null | undefined) {
  if (hotspotRefreshTimer) clearTimeout(hotspotRefreshTimer)
  hotspotRefreshTimer = null
  if (!mediaId) return
  hotspotRefreshTimer = setTimeout(() => {
    hotspotRefreshTimer = null
    if (playbackStatus?.media_id !== mediaId) return
    void requestBackendControl(
      'playback.hotspots',
      { media_id: mediaId },
      playbackControlMessages,
    )
  }, 350)
}

function handleBackendEvent(event: BackendEvent) {
  let forwardedEvent = event
  if (event.event === 'playback') {
    const accepted = acceptPlaybackStatusEvent(
      event.payload,
      event.timestamp,
      playbackEventTimestamp,
    )
    if (!accepted) return
    const previousMediaId = playbackStatus?.media_id
    const previousState = playbackStatus?.state
    playbackEventTimestamp = accepted.timestamp
    playbackState = accepted.status.state
    playbackStatus = accepted.status
    if (accepted.status.media_id !== previousMediaId) {
      playbackHotspots = null
      scheduleHotspotRefresh(accepted.status.media_id)
    } else if (accepted.status.media_id && accepted.status.state !== previousState) {
      scheduleHotspotRefresh(accepted.status.media_id)
    }
    forwardedEvent = { ...event, payload: accepted.status }
  }
  if (event.event === 'hotspots') {
    const projected = projectPlaybackHotspots(event.payload)
    if (!projected || projected.media_id !== playbackStatus?.media_id) return
    playbackHotspots = projected
    forwardedEvent = { ...event, payload: projected }
  }
  if (event.event === 'homepage') {
    const projected = projectHomepage(event.payload)
    if (!projected) return
    homepageProjection = durableHomepageProjection(projected)
    forwardedEvent = { ...event, payload: projected }
  }
  if (event.event === 'discovery') {
    const projected = projectDiscoverySelection(event.payload)
    if (!projected || projected.revision <= (discoverySelection?.revision ?? 0)) return
    discoverySelection = projected
    forwardedEvent = { ...event, payload: projected }
  }
  if (event.event === 'artwork') {
    const projected = projectArtworkStatus(event.payload)
    if (!projected) return
    artworkStatus = durableArtworkStatus(projected)
    forwardedEvent = { ...event, payload: projected }
  }
  if (event.event === 'video') {
    const projected = projectLocalVideo(event.payload)
    if (!projected || (localVideoStatus && projected.revision < localVideoStatus.revision)) return
    const timestamp = event.timestamp * 1000
    if (!Number.isFinite(timestamp) || Date.now() - timestamp > 1000 || timestamp - Date.now() > 100
      || (localVideoTimestamp !== null && timestamp < localVideoTimestamp)) return
    localVideoStatus = projected
    hostVideoResource = projectHostVideoResource(event.payload, projected)
    localVideoTimestamp = timestamp
    forwardedEvent = { ...event, payload: projected }
  }
  if (event.event === 'video-window') {
    const open = (event.payload as { open?: unknown } | null)?.open === true
    void ensureVideoWindow().then((window) => {
      if (window.isDestroyed()) return
      if (open) showWindow(window)
      else window.hide()
    })
    return
  }
  if (event.event === 'focus-recovery') {
    const projected = projectFocusRecovery(event.payload)
    if (!projected) return
    focusRecovery = projected
    forwardedEvent = { ...event, payload: projected }
  }
  if (event.event === 'equalizer') {
    const projected = projectEqualizer(event.payload)
    if (!projected || (equalizerProjection && projected.revision < equalizerProjection.revision)) return
    equalizerProjection = projected
    forwardedEvent = { ...event, payload: projected }
  }
  if (event.event === 'strudel') {
    const projected = projectStrudelProjection(event.payload)
    if (!projected) return
    strudelProjection = durableStrudelProjection(projected)
    forwardedEvent = { ...event, payload: projected }
  }
  if (event.event === 'strudel-render-requested') {
    const projectId = event.payload.project_id
    const project = typeof projectId === 'string'
      ? strudelProjection?.projects.find((candidate) => candidate.project_id === projectId)
      : undefined
    if (!project) return
    void startStrudelRender(project).then((result) => {
      if (!result.ok) setDesktopNotice(result.error || 'Pattern preview could not be rendered')
    })
  }
  if (event.event === 'sleep') sleepActive = Boolean(event.payload.active)
  if (event.event === 'update-safe') backendSafeOverride = Boolean(event.payload.safe)
  if (event.event === 'ready') {
    backendReady = true
    backendDiagnostic = null
    if (backendStartupTimer) clearTimeout(backendStartupTimer)
    backendStartupTimer = null
    fs.writeFileSync(path.join(app.getPath('userData'), 'healthy.json'), JSON.stringify({
      version: app.getVersion(), timestamp: Date.now(),
    }))
    closeButtonBehavior = normalizeCloseButtonBehavior(event.payload.close_button_behavior)
  }
  if (event.event === 'desktop-preferences') {
    closeButtonBehavior = normalizeCloseButtonBehavior(event.payload.close_button_behavior)
  }
  if (event.event === 'fatal-error' || event.event === 'shutdown-ack') backendReady = false
  if (event.event === 'fatal-error') trayActions.show()
  if (event.event === 'shutdown-ack') backendShutdownAcknowledged = true
  if (event.event === 'control-result') {
    const requestId = event.payload.request_id
    if (typeof requestId === 'string') {
      const catalogPending = pendingCommandCatalogRequests.get(requestId)
      if (catalogPending) {
        clearTimeout(catalogPending.timer)
        pendingCommandCatalogRequests.delete(requestId)
        const catalog = event.payload.ok === true
          ? projectCommandCatalog(event.payload.catalog)
          : null
        catalogPending.resolve(catalog ? { ok: true, catalog } : {
          ok: false,
          error: safeControlError(event.payload.error, 'Command catalog is unavailable'),
        })
      } else {
        const pending = pendingControlRequests.get(requestId)
        if (pending) {
          clearTimeout(pending.timer)
          pendingControlRequests.delete(requestId)
          const ok = event.payload.ok === true
          pending.resolve(ok ? { ok: true } : {
            ok: false,
            error: safeControlError(event.payload.error, pending.safeError),
          })
        }
      }
    }
  }
  if (event.event === 'update-prepared' && updateState.state === 'downloaded') {
    if (updatePreparationTimer) clearTimeout(updatePreparationTimer)
    quitting = true
    backendExitClosesView = false
    terminalProcess?.write('exit y\r')
    setTimeout(() => autoUpdater.quitAndInstall(false, true), 1200)
  }
  if (event.event !== 'control-result') send('backend:event', forwardedEvent)
  sendMiniPlayerSnapshot(event.event)
  if (updateState.state === 'downloaded') setUpdateState(updateState)
}

async function createControlServer(): Promise<void> {
  if (process.platform !== 'win32') fs.rmSync(controlEndpoint, { force: true })
  controlServer = net.createServer((socket) => {
    let pending = ''
    socket.setEncoding('utf8')
    socket.on('data', (chunk) => {
      pending += chunk
      const lines = pending.split('\n')
      pending = lines.pop() ?? ''
      for (const line of lines) {
        try {
          const message = JSON.parse(line) as (BackendEvent & { token?: string }) | {
            token?: string
            channel?: string
          }
          if (message.token !== controlToken) continue
          if ('channel' in message && message.channel === 'requests') {
            if (controlSocket && controlSocket !== socket) controlSocket.destroy()
            controlSocket = socket
            continue
          }
          if ('event' in message && typeof message.event === 'string') {
            handleBackendEvent(message)
          }
        } catch {
          // Ignore malformed local control messages without affecting the PTY.
        }
      }
    })
    socket.on('close', () => {
      if (controlSocket !== socket) return
      controlSocket = null
      finishPendingControlRequests()
    })
  })
  await new Promise<void>((resolve, reject) => {
    controlServer?.once('error', reject)
    controlServer?.listen(controlEndpoint, () => resolve())
  })
}

function backendCommand(): { executable: string; args: string[]; cwd: string; resources: string } {
  if (isDevelopment) {
    const virtualenvPython = process.platform === 'win32'
      ? path.join(repositoryRoot, '.venv', 'Scripts', 'python.exe')
      : path.join(repositoryRoot, '.venv', 'bin', 'python')
    const runnerRoot = process.env.pythonLocation || process.env.Python_ROOT_DIR
    const runnerPython = runnerRoot
      ? (process.platform === 'win32'
          ? path.join(runnerRoot, 'python.exe')
          : path.join(runnerRoot, 'bin', 'python'))
      : ''
    const executable = process.env.MARIANA_PYTHON
      || [virtualenvPython, runnerPython].find((candidate) => candidate && fs.existsSync(candidate))
      || 'python'
    return { executable, args: ['main.py'], cwd: repositoryRoot, resources: repositoryRoot }
  }
  const backend = path.join(process.resourcesPath, 'backend')
  const executable = path.join(backend, process.platform === 'win32' ? 'mariana-cli.exe' : 'mariana-cli')
  return { executable, args: [], cwd: backend, resources: backend }
}

function startTerminal() {
  terminalProcess?.kill()
  controlSocket?.destroy()
  controlSocket = null
  backendReady = false
  backendDiagnostic = null
  if (backendStartupTimer) clearTimeout(backendStartupTimer)
  send('backend:event', { event: 'starting', payload: {}, timestamp: Date.now() / 1000 } satisfies BackendEvent)
  finishPendingControlRequests()
  playbackState = 'idle'
  playbackStatus = null
  playbackEventTimestamp = null
  localVideoStatus = null
  localVideoTimestamp = null
  equalizerProjection = null
  sendMiniPlayerSnapshot()
  backendShutdownAcknowledged = false
  backendExitClosesView = true
  const command = backendCommand()
  const spawnedProcess = pty.spawn(command.executable, command.args, {
    name: 'xterm-256color',
    cols: 120,
    rows: 34,
    cwd: command.cwd,
    env: {
      ...process.env,
      TERM: 'xterm-256color',
      COLORTERM: 'truecolor',
      MARIANA_DESKTOP: '1',
      MARIANA_RESOURCE_DIR: command.resources,
      MARIANA_DATA_DIR: path.join(app.getPath('userData'), 'runtime'),
      MARIANA_CONTROL_ENDPOINT: controlEndpoint,
      MARIANA_CONTROL_TOKEN: controlToken,
    },
  })
  terminalProcess = spawnedProcess
  backendStartupTimer = setTimeout(() => {
    if (terminalProcess !== spawnedProcess || backendReady) return
    backendDiagnostic = 'Backend control channel did not become ready'
    handleBackendEvent({
      event: 'fatal-error',
      payload: { message: backendDiagnostic },
      timestamp: Date.now() / 1000,
    })
  }, 30_000)
  spawnedProcess.onData((data) => {
    const controlWindow = terminalControlTail + data
    const clearIndex = Math.max(controlWindow.lastIndexOf('\u001b[2J'), controlWindow.lastIndexOf('\u001b[3J'))
    terminalHistory = clearIndex >= 0
      ? controlWindow.slice(clearIndex)
      : (terminalHistory + data).slice(-1_000_000)
    terminalControlTail = controlWindow.slice(-4)
    if (mainWindow && !mainWindow.webContents.isLoading()) send('terminal:data', data)
  })
  spawnedProcess.onExit(({ exitCode }) => {
    if (terminalProcess !== spawnedProcess) return
    terminalProcess = null
    if (backendStartupTimer) clearTimeout(backendStartupTimer)
    backendStartupTimer = null
    send('terminal:exit', {
      code: exitCode,
      intentional: backendShutdownAcknowledged && backendExitClosesView,
    })
  })
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 760,
    minHeight: 520,
    backgroundColor: '#080b16',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'hidden',
    titleBarOverlay: process.platform === 'darwin' ? false : {
      color: '#080b16', symbolColor: '#d9e2ff', height: 44,
    },
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  })
  if (process.env.MARIANA_E2E === '1') {
    mainWindow.webContents.on('console-message', (_event, level, message) => {
      console.log(`[renderer:${level}] ${message}`)
    })
    mainWindow.webContents.on('did-fail-load', (_event, code, description, url) => {
      console.error(`[renderer:load-failed] ${code} ${description} ${url}`)
    })
  }
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const allowed = usesViteRenderer
      ? new URL(url).origin === 'http://127.0.0.1:5173'
      : url.startsWith('file:') && fileURLToPath(url).startsWith(path.join(__dirname, '..', 'dist'))
    if (!allowed) event.preventDefault()
  })
  mainWindow.webContents.on('did-finish-load', () => {
    setUpdateState(updateState)
    if (desktopNotice) setDesktopNotice(desktopNotice)
  })
  if (usesViteRenderer) await mainWindow.loadURL('http://127.0.0.1:5173')
  else await mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  mainWindow.on('close', (event) => {
    if (!mainWindow) return
    handleWindowClose(event, mainWindow, closeButtonBehavior, trayAvailable, quitting)
  })
  mainWindow.on('closed', () => {
    mainWindow = null
    if (!quitting) trayActions.quit()
  })
}

function configureRestrictedNavigation(window: BrowserWindow) {
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('will-navigate', (event, url) => {
    const allowed = usesViteRenderer
      ? new URL(url).origin === 'http://127.0.0.1:5173'
      : url.startsWith('file:') && fileURLToPath(url).startsWith(path.join(__dirname, '..', 'dist'))
    if (!allowed) event.preventDefault()
  })
}

function validRenderedWave(value: unknown): Buffer | null {
  let bytes: Buffer
  if (value instanceof ArrayBuffer) bytes = Buffer.from(value)
  else if (ArrayBuffer.isView(value)) bytes = Buffer.from(value.buffer, value.byteOffset, value.byteLength)
  else return null
  if (bytes.length < 44 || bytes.length > 16 * 1024 * 1024) return null
  if (bytes.toString('ascii', 0, 4) !== 'RIFF'
    || bytes.toString('ascii', 8, 12) !== 'WAVE'
    || bytes.toString('ascii', 12, 16) !== 'fmt ') return null
  return bytes
}

function discardStrudelRenderWindow(window: BrowserWindow): void {
  if (strudelRenderWindow === window) {
    strudelRenderWindow = null
    strudelRenderLoad = null
  }
  try { if (!window.isDestroyed()) window.destroy() } catch { /* Closing is nonfatal. */ }
}

function ensureStrudelRenderWindow(): { window: BrowserWindow; ready: Promise<void> } {
  if (strudelRenderWindow && !strudelRenderWindow.isDestroyed()) {
    return { window: strudelRenderWindow, ready: strudelRenderLoad ?? Promise.resolve() }
  }
  const window = new BrowserWindow({
    show: false,
    width: 320,
    height: 240,
    webPreferences: {
      preload: path.join(__dirname, 'strudelPreload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false,
    },
  })
  strudelRenderWindow = window
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.once('render-process-gone', () => discardStrudelRenderWindow(window))
  window.webContents.on('will-navigate', (event, url) => {
    const allowed = usesViteRenderer
      ? url === 'http://127.0.0.1:5173/strudel.html'
      : url.startsWith('file:') && fileURLToPath(url) === path.join(__dirname, '..', 'dist', 'strudel.html')
    if (!allowed) event.preventDefault()
  })
  window.on('closed', () => {
    if (strudelRenderWindow === window) {
      strudelRenderWindow = null
      strudelRenderLoad = null
    }
    strudelRenders.ownerClosed(window)
  })
  const load = usesViteRenderer
    ? window.loadURL('http://127.0.0.1:5173/strudel.html')
    : window.loadFile(path.join(__dirname, '..', 'dist', 'strudel.html'))
  strudelRenderLoad = load
  const ready = load.catch((error: unknown) => {
    discardStrudelRenderWindow(window)
    throw error
  }).finally(() => {
    if (strudelRenderLoad === load) strudelRenderLoad = null
  })
  return { window, ready }
}

function currentStrudelProject(input: StrudelPreviewInput): StrudelPreviewInput | null {
  const current = strudelProjection?.projects.find((project) => project.project_id === input.project_id)
  if (!current
    || current.revision !== input.revision
    || current.name !== input.name
    || current.code !== input.code
    || current.preview_seconds !== input.preview_seconds) return null
  return current
}

async function startStrudelRender(input: StrudelPreviewInput): Promise<DesktopControlResult> {
  if (quitting || !validStrudelPreviewInput(input) || !currentStrudelProject(input)) {
    return { ok: false, error: 'Save the current project revision before rendering' }
  }
  const lease = strudelRenders.begin(randomBytes(16).toString('hex'), input)
  if (!lease) return { ok: false, error: 'Another pattern preview is already rendering' }
  const { task } = lease
  try {
    const { window, ready } = ensureStrudelRenderWindow()
    strudelRenders.bind(task, window)
    // Do not await a potentially hung load before returning the bounded result.
    void ready.then(() => {
      if (!strudelRenders.loaded(task)) return
      if (!currentStrudelProject(task.input)) {
        strudelRenders.finish(task, { ok: false, error: 'Save the current project revision before rendering' })
        return
      }
      window.webContents.send('strudel:render', {
        requestId: task.requestId, code: task.input.code, previewSeconds: task.input.preview_seconds,
      })
    }).catch(() => {
      strudelRenders.finish(task, { ok: false, error: 'Pattern renderer is unavailable' })
      discardStrudelRenderWindow(window)
    })
  } catch {
    strudelRenders.finish(task, { ok: false, error: 'Pattern renderer is unavailable' })
  }
  return lease.result
}

async function finishStrudelRender(pending: StrudelRenderTask<BrowserWindow>, value: unknown): Promise<void> {
  if (!strudelRenders.isCurrent(pending)) return
  const bytes = validRenderedWave(value)
  if (!bytes) {
    strudelRenders.finish(pending, { ok: false, error: 'Pattern renderer returned invalid audio' })
    return
  }
  try {
    const digest = createHash('sha256').update(bytes).digest('hex')
    const directory = path.join(app.getPath('userData'), 'runtime', 'temp', 'strudel')
    const artifactName = `${pending.input.project_id}-${digest}.wav`
    const destination = path.join(directory, artifactName)
    await fs.promises.mkdir(directory, { recursive: true })
    if (!strudelRenders.isCurrent(pending)) return
    if (!fs.existsSync(destination)) {
      const temporary = path.join(directory, `.${artifactName}.${randomBytes(8).toString('hex')}.tmp`)
      try {
        await fs.promises.writeFile(temporary, bytes, { flag: 'wx' })
        if (!strudelRenders.isCurrent(pending)) return
        await fs.promises.rename(temporary, destination)
      } finally {
        await fs.promises.rm(temporary, { force: true })
      }
    }
    if (!strudelRenders.isCurrent(pending)) return
    const renderedEntries = await Promise.all((await fs.promises.readdir(directory, { withFileTypes: true }))
      .filter((entry) => entry.isFile())
      .map(async (entry) => {
        try {
          const stat = await fs.promises.stat(path.join(directory, entry.name))
          return { name: entry.name, size: stat.size, mtimeMs: stat.mtimeMs }
        } catch {
          return null
        }
      }))
    if (!strudelRenders.isCurrent(pending)) return
    const filesToPrune = strudelRenderedFilesToPrune(
      renderedEntries.filter((entry): entry is NonNullable<typeof entry> => entry !== null),
      artifactName,
    )
    await Promise.all(filesToPrune.map(async (name) => {
      if (!strudelRenders.isCurrent(pending)) return
      try {
        await fs.promises.rm(path.join(directory, name), { force: true })
      } catch {
        // A preview already opened by the backend may still be locked on Windows.
      }
    }))
    if (!strudelRenders.isCurrent(pending)) return
    if (!currentStrudelProject(pending.input)) {
      strudelRenders.finish(pending, { ok: false, error: 'Save the current project revision before rendering' })
      return
    }
    if (!strudelRenders.beginCommit(pending)) return
    const result = await requestBackendControl('strudel.preview', {
      project_id: pending.input.project_id,
      revision: pending.input.revision,
      artifact_name: artifactName,
    }, playbackControlMessages)
    strudelRenders.finish(pending, result)
  } catch {
    strudelRenders.finish(pending, { ok: false, error: 'Rendered pattern could not be prepared for playback' })
  }
}

async function ensureMiniPlayerWindow(): Promise<BrowserWindow> {
  let created = false
  const window = ensureSingleWindow(miniPlayerWindow, () => {
    created = true
    miniVideoMode = hasCurrentVideo(backendReady, playbackStatus?.media_id, localVideoStatus)
    return new BrowserWindow({
      ...miniWindowGeometry(miniVideoMode),
      show: false,
      frame: false,
      skipTaskbar: false,
      alwaysOnTop: false,
      backgroundColor: '#15151d',
      title: 'Mariana Mini-player',
      webPreferences: {
        preload: path.join(__dirname, 'miniPreload.cjs'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    })
  })
  miniPlayerWindow = window
  if (!created) return window

  configureRestrictedNavigation(window)
  window.on('close', (event) => {
    handleAuxiliaryWindowClose(event, window, quitting)
  })
  window.on('closed', () => {
    if (miniPlayerWindow === window) miniPlayerWindow = null
  })
  if (usesViteRenderer) await window.loadURL('http://127.0.0.1:5173/?surface=mini')
  else await window.loadFile(path.join(__dirname, '..', 'dist', 'index.html'), { query: { surface: 'mini' } })
  return window
}

async function ensureVideoWindow(): Promise<BrowserWindow> {
  let created = false
  const window = ensureSingleWindow(videoWindow, () => {
    created = true
    return new BrowserWindow({
      width: 960,
      height: 600,
      minWidth: 480,
      minHeight: 320,
      show: false,
      title: 'Mariana Video',
      backgroundColor: '#15151d',
      webPreferences: {
        preload: path.join(__dirname, 'miniPreload.cjs'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    })
  })
  videoWindow = window
  if (!created) return window
  configureRestrictedNavigation(window)
  window.on('close', (event) => {
    handleAuxiliaryWindowClose(event, window, quitting)
  })
  window.on('closed', () => {
    if (videoWindow === window) videoWindow = null
  })
  if (usesViteRenderer) await window.loadURL('http://127.0.0.1:5173/?surface=video')
  else await window.loadFile(path.join(__dirname, '..', 'dist', 'index.html'), { query: { surface: 'video' } })
  return window
}

async function showMiniPlayer(): Promise<void> {
  const window = await ensureMiniPlayerWindow()
  if (!window.isDestroyed()) showWindow(window)
}

function readCachedImage(
  cacheArea: 'artwork' | 'homepage',
  cacheKey: string,
  expectedMime: NonNullable<ArtworkStatus['mime_type']>,
  maxBytes: number,
  unavailableMessage: string,
): ArtworkDataResult {
  const mimeByExtension: Record<string, ArtworkStatus['mime_type']> = {
    '.jpg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
  }
  const extension = path.extname(cacheKey)
  const mime = mimeByExtension[extension]
  if (!mime || mime !== expectedMime) return { ok: false, error: unavailableMessage }
  const cacheRoot = path.resolve(app.getPath('userData'), 'runtime', 'cache', cacheArea)
  const candidate = path.resolve(cacheRoot, cacheKey)
  if (path.dirname(candidate) !== cacheRoot) return { ok: false, error: unavailableMessage }
  try {
    const stat = fs.lstatSync(candidate)
    const realCacheRoot = fs.realpathSync(cacheRoot)
    const realPath = fs.realpathSync(candidate)
    if (
      stat.isSymbolicLink()
      || !stat.isFile()
      || path.dirname(realPath) !== realCacheRoot
      || stat.size < 1
      || stat.size > maxBytes
    ) {
      return { ok: false, error: unavailableMessage }
    }
    const content = fs.readFileSync(candidate)
    if (content.length < 1 || content.length > maxBytes) {
      return { ok: false, error: unavailableMessage }
    }
    const signatures: Record<NonNullable<ArtworkStatus['mime_type']>, (value: Buffer) => boolean> = {
      'image/jpeg': (value) => value.length >= 3 && value[0] === 0xff && value[1] === 0xd8 && value[2] === 0xff,
      'image/png': (value) => value.length >= 8 && value.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])),
      'image/webp': (value) => value.length >= 12 && value.toString('ascii', 0, 4) === 'RIFF' && value.toString('ascii', 8, 12) === 'WEBP',
    }
    if (!signatures[mime](content)) return { ok: false, error: unavailableMessage }
    const encoded = content.toString('base64')
    return { ok: true, dataUrl: `data:${mime};base64,${encoded}` }
  } catch {
    return { ok: false, error: unavailableMessage }
  }
}

function readCurrentArtwork(cacheKey: unknown): ArtworkDataResult {
  if (
    !validArtworkCacheKey(cacheKey)
    || !artworkStatus?.available
    || artworkStatus.cache_key !== cacheKey
    || artworkStatus.media_id !== playbackStatus?.media_id
    || !artworkStatus.mime_type
  ) {
    return { ok: false, error: 'Current artwork is unavailable' }
  }
  return readCachedImage(
    'artwork', cacheKey, artworkStatus.mime_type, 8 * 1024 * 1024, 'Current artwork is unavailable',
  )
}

function readHomepageImage(cacheKey: unknown): ArtworkDataResult {
  if (!validArtworkCacheKey(cacheKey)) return { ok: false, error: 'Homepage image is unavailable' }
  const sections = homepageProjection?.sections
  if (!sections) return { ok: false, error: 'Homepage image is unavailable' }
  const item = sections
    .flatMap((section) => section.items)
    .find((candidate) => candidate.image_key === cacheKey)
  if (!item?.image_mime) return { ok: false, error: 'Homepage image is unavailable' }
  return readCachedImage(
    'homepage', cacheKey, item.image_mime, 2 * 1024 * 1024, 'Homepage image is unavailable',
  )
}

function registerIpc() {
  ipcMain.handle('backend:snapshot', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    return {
      ready: backendReady,
      diagnostic: backendDiagnostic,
      desktopNotice,
      closeButtonBehavior,
      playbackState,
      sleepActive,
      playback: playbackStatus,
      strudel: strudelProjection,
      focusRecovery,
      hotspots: playbackHotspots,
      homepage: homepageProjection,
      artwork: artworkStatus,
    }
  })
  ipcMain.handle('backend:command-catalog', async (event, rawOptions: unknown) => {
    if (!validateSender(event)) {
      return { ok: false, error: 'Command catalog request is invalid' } satisfies CommandCatalogResult
    }
    const options = validateCommandCatalogOptions(rawOptions)
    if (options === null) {
      return { ok: false, error: 'Command catalog request is invalid' } satisfies CommandCatalogResult
    }
    return requestCommandCatalog(options)
  })
  ipcMain.handle('backend:favorite-toggle', async (event, mediaId: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId)) {
      return { ok: false, error: 'Favourite target is unavailable' } satisfies DesktopControlResult
    }
    return requestBackendControl('favorite.toggle', { media_id: mediaId })
  })
  ipcMain.handle('backend:rating-set', async (event, mediaId: unknown, rating: unknown) => {
    if (
      !validateSender(event)
      || !validControlMediaId(mediaId)
      || typeof rating !== 'number'
      || !Number.isInteger(rating)
      || rating < 0
      || rating > 5
    ) {
      return { ok: false, error: 'Rating must be a whole number from 0 to 5' } satisfies DesktopControlResult
    }
    return requestBackendControl('rating.set', { media_id: mediaId, rating })
  })
  ipcMain.handle('backend:seek', async (event, mediaId: unknown, targetSeconds: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId)) {
      return { ok: false, error: 'Playback target is unavailable' } satisfies DesktopControlResult
    }
    const validation = validateSeekIntent(playbackStatus, mediaId, targetSeconds, backendReady)
    if (!validation.ok) return validation
    return requestBackendControl(
      'playback.seek',
      { media_id: mediaId, target_seconds: validation.targetSeconds, origin: 'desktop' },
      seekControlMessages,
    )
  })
  ipcMain.handle('backend:homepage-refresh', async (event) => {
    if (!validateSender(event)) return { ok: false, error: 'Homepage request is invalid' }
    return requestBackendControl('homepage.refresh', {}, homepageControlMessages)
  })
  ipcMain.handle('backend:strudel-open', async (event) => {
    if (!validateSender(event)) return { ok: false, error: 'Pattern editor request is invalid' }
    return requestBackendControl('strudel.open', {}, homepageControlMessages)
  })
  ipcMain.handle('backend:strudel-save', async (event, input: unknown) => {
    if (!validateSender(event) || !validStrudelSaveInput(input)) {
      return { ok: false, error: 'Pattern project is invalid' }
    }
    return requestBackendControl('strudel.save', {
      project_id: input.project_id,
      name: input.name,
      code: input.code,
      preview_seconds: input.preview_seconds,
      revision: input.revision,
    }, homepageControlMessages)
  })
  ipcMain.handle('backend:strudel-delete', async (event, projectId: unknown, revision: unknown) => {
    if (!validateSender(event) || typeof projectId !== 'string' || !/^[0-9a-f]{32}$/.test(projectId)
      || !Number.isSafeInteger(revision) || Number(revision) < 1) {
      return { ok: false, error: 'Pattern project deletion request is invalid' }
    }
    return requestBackendControl('strudel.delete', { project_id: projectId, revision }, homepageControlMessages)
  })
  ipcMain.handle('backend:strudel-preview', async (event, input: unknown) => {
    if (!validateSender(event) || !validStrudelPreviewInput(input)) {
      return { ok: false, error: 'Pattern preview request is invalid' }
    }
    return startStrudelRender(input)
  })
  ipcMain.on('strudel:complete', (event, requestId: unknown, bytes: unknown) => {
    if (!strudelRenderWindow || event.sender !== strudelRenderWindow.webContents
      || typeof requestId !== 'string' || !/^[0-9a-f]{32}$/.test(requestId)) return
    const pending = strudelRenders.claimReply(requestId, strudelRenderWindow)
    if (pending) void finishStrudelRender(pending, bytes)
  })
  ipcMain.on('strudel:failed', (event, requestId: unknown, message: unknown) => {
    if (!strudelRenderWindow || event.sender !== strudelRenderWindow.webContents
      || typeof requestId !== 'string' || !/^[0-9a-f]{32}$/.test(requestId)) return
    const pending = strudelRenders.claimReply(requestId, strudelRenderWindow)
    if (!pending) return
    strudelRenders.finish(pending, { ok: false, error: safeControlError(message, 'Pattern rendering failed') })
  })
  ipcMain.handle('backend:focus-recovery-retry', (event) => {
    if (!validateSender(event)) return { ok: false, error: 'Invalid Focus recovery request' }
    return requestBackendControl('focus.recovery.retry', {}, homepageControlMessages)
  })
  ipcMain.handle('backend:lyrics-status', (event) => {
    if (!validateSender(event)) return { ok: false, error: 'Invalid lyrics request' }
    return requestBackendControl('lyrics.status', {}, homepageControlMessages)
  })
  ipcMain.handle('backend:lyrics-hide', (event) => {
    if (!validateSender(event)) return { ok: false, error: 'Invalid lyrics request' }
    return requestBackendControl('lyrics.hide', {}, homepageControlMessages)
  })
  ipcMain.handle('backend:lyrics-request', (event, mediaId: unknown, refresh: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId) || mediaId !== playbackStatus?.media_id
      || typeof refresh !== 'boolean') return { ok: false, error: 'Current media changed; request lyrics again' }
    return requestBackendControl('lyrics.request', { media_id: mediaId, refresh }, homepageControlMessages)
  })
  ipcMain.handle('backend:lyrics-offset', (event, mediaId: unknown, offsetMs: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId) || mediaId !== playbackStatus?.media_id
      || typeof offsetMs !== 'number' || !Number.isInteger(offsetMs) || Math.abs(offsetMs) > 60_000) {
      return { ok: false, error: 'Invalid lyrics timing request' }
    }
    return requestBackendControl('lyrics.offset', { media_id: mediaId, offset_ms: offsetMs }, homepageControlMessages)
  })
  ipcMain.handle('backend:homepage-open', async (event) => {
    if (!validateSender(event)) return { ok: false, error: 'Homepage request is invalid' }
    return requestBackendControl('homepage.open', {}, homepageControlMessages)
  })
  ipcMain.handle('backend:homepage-configure', async (event, setting: unknown, enabled: unknown) => {
    if (!validateSender(event) || !['startup', 'online'].includes(String(setting)) || typeof enabled !== 'boolean') {
      return { ok: false, error: 'Homepage setting is invalid' }
    }
    return requestBackendControl('homepage.configure', { setting, enabled }, homepageControlMessages)
  })
  ipcMain.handle('backend:homepage-image-data', async (event, cacheKey: unknown): Promise<ArtworkDataResult> => {
    if (!validateSender(event)) return { ok: false, error: 'Homepage image request is invalid' }
    return readHomepageImage(cacheKey)
  })
  ipcMain.handle('backend:discovery-begin', async (event, itemId: unknown, requestId: unknown, page: unknown = 0) => {
    const sections = homepageProjection?.sections
    if (!sections) {
      return { ok: false, error: 'Select a current release with online discovery enabled' }
    }
    const item = sections.filter((section) => section.key === 'releases' || section.key.startsWith('catalogue-')).flatMap((section) => section.items)
      .find((entry) => entry.id === itemId)
    if (!validateSender(event) || !validSelectionHandle(requestId) || !item || !homepageProjection?.online_enabled
      || !Number.isSafeInteger(page) || Number(page) < 0 || Number(page) > 7) {
      return { ok: false, error: 'Select a current release with online discovery enabled' }
    }
    return requestBackendControl('discovery.begin', {
      item_id: item.id, request_id: requestId, ...(page ? { page } : {}),
    }, homepageControlMessages)
  })
  ipcMain.handle('backend:discovery-choose', async (event, requestId: unknown, revision: unknown, choiceId: unknown, intent: unknown) => {
    if (!validateSender(event) || !validSelectionHandle(requestId) || !validSelectionHandle(choiceId)
      || !Number.isSafeInteger(revision) || !['versions', 'play', 'queue'].includes(String(intent))
      || requestId !== discoverySelection?.request_id || revision !== discoverySelection?.revision
      || !homepageProjection?.online_enabled) {
      return { ok: false, error: 'Selection changed; find versions again' }
    }
    return requestBackendControl('discovery.choose', {
      request_id: requestId, revision, choice_id: choiceId, intent,
    }, homepageControlMessages)
  })
  ipcMain.handle('backend:discovery-cancel', async (event, requestId: unknown) => {
    if (!validateSender(event) || !validSelectionHandle(requestId)) return { ok: false, error: 'Invalid selection' }
    return requestBackendControl('discovery.cancel', { request_id: requestId }, homepageControlMessages)
  })
  ipcMain.handle('backend:artwork-configure', async (event, enabled: unknown) => {
    if (!validateSender(event) || typeof enabled !== 'boolean') {
      return { ok: false, error: 'Artwork setting is invalid' }
    }
    return requestBackendControl('artwork.configure', { enabled }, artworkControlMessages)
  })
  ipcMain.handle('backend:artwork-show', async (event, mediaId: unknown, fetch: unknown) => {
    if (!validateSender(event) || typeof fetch !== 'boolean') {
      return { ok: false, error: 'Artwork request is invalid' }
    }
    if (!validControlMediaId(mediaId) || mediaId !== playbackStatus?.media_id) {
      return { ok: false, error: 'Current media changed; try again' }
    }
    return requestBackendControl('artwork.show', { media_id: mediaId, fetch }, artworkControlMessages)
  })
  ipcMain.handle('backend:artwork-data', async (event, cacheKey: unknown): Promise<ArtworkDataResult> => {
    if (!validateSender(event)) return { ok: false, error: 'Artwork request is invalid' }
    return readCurrentArtwork(cacheKey)
  })
  ipcMain.handle('backend:crossfade-configure', async (event, seconds: unknown) => {
    if (!validateSender(event) || typeof seconds !== 'number' || !Number.isFinite(seconds)
      || seconds < 0 || seconds > 30) {
      return { ok: false, error: 'Crossfade duration must be from 0 to 30 seconds' }
    }
    return requestBackendControl('playback.crossfade', { seconds }, playbackControlMessages)
  })
  protocol.handle('mariana-video', (request) => localVideoStatus?.transport === 'source' ? serveSourceVideo(
    request, () => ({ status: backendReady ? localVideoStatus : null,
      mediaId: playbackStatus?.media_id ?? null, resource: hostVideoResource }),
  ) : serveLocalVideo(
    request, path.join(app.getPath('userData'), 'runtime', 'cache', 'video'),
    backendReady ? localVideoStatus : null, playbackStatus?.media_id ?? null,
  ))
  ipcMain.handle('backend:video-status', async (event) => {
    if (!validateSender(event)) return { ok: false, error: 'Video request is invalid' }
    return requestBackendControl('video.status', {}, playbackControlMessages)
  })
  const downloadControl = (event: Electron.IpcMainInvokeEvent, mediaId: unknown, format: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId) || !['mp3', 'mp4'].includes(String(format))
      || mediaId !== playbackStatus?.media_id) {
      return Promise.resolve({ ok: false, error: 'Download target is unavailable' })
    }
    return requestBackendControl('download.current', { media_id: mediaId, format }, playbackControlMessages)
  }
  ipcMain.handle('backend:download-current', downloadControl)
  ipcMain.handle('backend:download-status', (event) => {
    if (!validateSender(event)) return { ok: false, error: 'Download request is invalid' }
    return requestBackendControl('download.status', {}, playbackControlMessages)
  })
  ipcMain.handle('backend:video-configure', async (event, mediaId: unknown, mode: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId)
      || mediaId !== playbackStatus?.media_id || !['audio', 'video'].includes(String(mode))) {
      return { ok: false, error: 'Video target is unavailable' }
    }
    return requestBackendControl('video.configure', { media_id: mediaId, mode }, playbackControlMessages)
  })
  const captionConfigure = (
    validSender: boolean, mediaId: unknown, action: unknown, value: unknown,
  ) => {
    const needsValue = ['shift', 'set-offset'].includes(String(action))
    if (!validSender || !validControlMediaId(mediaId) || mediaId !== playbackStatus?.media_id
      || !['on', 'off', 'clear', 'shift', 'set-offset'].includes(String(action))
      || (needsValue ? !Number.isInteger(value) : value !== undefined)) {
      return Promise.resolve({ ok: false, error: 'Caption request is invalid' })
    }
    return requestBackendControl('video.captions', {
      media_id: mediaId, operation: action, ...(needsValue ? { value } : {}),
    }, playbackControlMessages)
  }
  ipcMain.handle('backend:video-caption-file', async (event, mediaId: unknown, replace: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId) || mediaId !== playbackStatus?.media_id
      || typeof replace !== 'boolean') {
      return { ok: false, error: 'Caption request is invalid' }
    }
    const options = {
      title: replace ? 'Replace captions' : 'Load captions',
      properties: ['openFile'] as Array<'openFile'>,
      filters: [{ name: 'Caption files', extensions: ['srt', 'vtt'] }],
    }
    const owner = BrowserWindow.fromWebContents(event.sender)
    const selection = owner ? await dialog.showOpenDialog(owner, options) : await dialog.showOpenDialog(options)
    if (selection.canceled || selection.filePaths.length !== 1) return { ok: true }
    if (mediaId !== playbackStatus?.media_id) return { ok: false, error: 'Current media changed; try again' }
    return requestBackendControl('video.captions', {
      media_id: mediaId, operation: replace ? 'replace' : 'load', path: selection.filePaths[0],
    }, playbackControlMessages)
  })
  ipcMain.handle('backend:video-caption-select', (event, mediaId: unknown, revision: unknown, trackId: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId) || mediaId !== playbackStatus?.media_id
      || !Number.isSafeInteger(revision) || (revision as number) < 0
      || typeof trackId !== 'string' || !/^[a-f0-9]{32}$/.test(trackId)) {
      return { ok: false, error: 'Caption selection is invalid' }
    }
    return requestBackendControl('video.captions', {
      media_id: mediaId, operation: 'select', revision, track_id: trackId,
    }, playbackControlMessages)
  })
  ipcMain.handle('backend:video-caption-languages', (event, mediaId: unknown, languages: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId) || mediaId !== playbackStatus?.media_id
      || !Array.isArray(languages) || languages.length > 5
      || languages.some((item) => typeof item !== 'string' || !/^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$/i.test(item))) {
      return { ok: false, error: 'Caption languages are invalid' }
    }
    return requestBackendControl('video.captions', { media_id: mediaId, operation: 'languages', languages }, playbackControlMessages)
  })
  ipcMain.handle('backend:video-caption-automatic', (event, mediaId: unknown) => {
    if (!validateSender(event) || !validControlMediaId(mediaId) || mediaId !== playbackStatus?.media_id) {
      return { ok: false, error: 'Caption target is unavailable' }
    }
    return requestBackendControl('video.captions', { media_id: mediaId, operation: 'auto' }, playbackControlMessages)
  })
  const audioOffset = (validSender: boolean, mediaId: unknown, value: unknown, relative: unknown) => {
    if (!validSender || !validControlMediaId(mediaId) || mediaId !== playbackStatus?.media_id
      || !Number.isInteger(value) || (value as number) < -5000 || (value as number) > 5000
      || typeof relative !== 'boolean') {
      return Promise.resolve({ ok: false, error: 'Audio synchronization request is invalid' })
    }
    return requestBackendControl('video.audio-offset', {
      media_id: mediaId, value, relative,
    }, playbackControlMessages)
  }
  ipcMain.handle('backend:video-caption-configure', (event, mediaId, action, value) => (
    captionConfigure(validateSender(event), mediaId, action, value)
  ))
  ipcMain.handle('backend:video-audio-offset', (event, mediaId, value, relative) => (
    audioOffset(validateSender(event), mediaId, value, relative)
  ))
  ipcMain.handle('backend:equalizer-status', async (event) => {
    if (!validateSender(event)) return { ok: false, error: 'Equalizer request is invalid' }
    const result = await requestBackendControl('equalizer.status', {}, playbackControlMessages)
    return result.ok && equalizerProjection ? { ok: true, state: equalizerProjection } : { ok: false, error: 'Equalizer is unavailable' }
  })
  ipcMain.handle('backend:equalizer-configure', async (event, intent: unknown) => {
    if (!validateSender(event) || !validEqualizerIntent(intent)) return { ok: false, error: 'Equalizer request is invalid' }
    const result = await requestBackendControl('equalizer.configure', intent, playbackControlMessages)
    return result.ok && equalizerProjection ? { ok: true, state: equalizerProjection } : { ok: false, error: 'Equalizer update was rejected; refresh or choose a new preset name' }
  })
  for (const action of ['play', 'pause', 'previous', 'next'] as const) {
    ipcMain.handle(`backend:${action}`, async (event, mediaId: unknown) => {
      if (!validateSender(event) || !validControlMediaId(mediaId)) {
        return { ok: false, error: 'Playback target is unavailable' } satisfies DesktopControlResult
      }
      return requestBackendControl(
        `playback.${action}`,
        { media_id: mediaId, origin: 'desktop' },
        playbackControlMessages,
      )
    })
  }
  ipcMain.on('terminal:write', (event, data: unknown) => {
    if (validateSender(event) && typeof data === 'string' && data.length <= 1_000_000) terminalProcess?.write(data)
  })
  ipcMain.on('terminal:resize', (event, size: { cols?: unknown; rows?: unknown }) => {
    if (!validateSender(event)) return
    const cols = Number(size?.cols)
    const rows = Number(size?.rows)
    if (Number.isInteger(cols) && Number.isInteger(rows) && cols >= 20 && rows >= 5 && cols <= 500 && rows <= 200) {
      terminalProcess?.resize(cols, rows)
    }
  })
  ipcMain.handle('terminal:restart', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    startTerminal()
  })
  ipcMain.handle('terminal:history', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    return terminalHistory
  })
  ipcMain.handle('clipboard:write-text', async (event, value: unknown) => {
    if (!validateSender(event) || typeof value !== 'string' || value.length > 1_000_000) {
      throw new Error('Invalid clipboard text')
    }
    clipboard.writeText(value)
  })
  ipcMain.handle('app:close', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    trayActions.quit()
  })
  ipcMain.handle('app:show-mini-player', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    await showMiniPlayer()
  })
  ipcMain.handle('mini:snapshot', async (event) => {
    if (!validateMiniPlayerSender(event)) throw new Error('Invalid IPC sender')
    return miniPlayerSnapshot()
  })
  ipcMain.handle('mini:video-status', (event) => {
    if (!validateMiniPlayerSender(event)) return { ok: false, error: 'Video request is invalid' }
    return requestBackendControl('video.status', {}, playbackControlMessages)
  })
  ipcMain.handle('mini:video-caption-configure', (event, mediaId, action, value) => (
    captionConfigure(validateMiniPlayerSender(event), mediaId, action, value)
  ))
  ipcMain.handle('mini:video-audio-offset', (event, mediaId, value, relative) => (
    audioOffset(validateMiniPlayerSender(event), mediaId, value, relative)
  ))
  ipcMain.handle('mini:download-current', (event, mediaId: unknown, format: unknown) => {
    if (!validateMiniPlayerSender(event) || !validControlMediaId(mediaId)
      || mediaId !== playbackStatus?.media_id || !['mp3', 'mp4'].includes(String(format))) {
      return { ok: false, error: 'Download target is unavailable' }
    }
    return requestBackendControl('download.current', { media_id: mediaId, format }, playbackControlMessages)
  })
  ipcMain.handle('mini:download-status', (event) => {
    if (!validateMiniPlayerSender(event)) return { ok: false, error: 'Download request is invalid' }
    return requestBackendControl('download.status', {}, playbackControlMessages)
  })
  const miniPlaybackControl = (
    event: Electron.IpcMainInvokeEvent,
    mediaId: unknown,
    action: 'playback.play' | 'playback.pause' | 'playback.previous' | 'playback.next',
  ) => {
    if (!validateMiniPlayerSender(event) || !validControlMediaId(mediaId)) {
      return Promise.resolve({ ok: false, error: 'Playback target is unavailable' })
    }
    return requestBackendControl(action, { media_id: mediaId, origin: 'mini-player' }, playbackControlMessages)
  }
  ipcMain.handle('mini:play', (event, mediaId) => miniPlaybackControl(event, mediaId, 'playback.play'))
  ipcMain.handle('mini:pause', (event, mediaId) => miniPlaybackControl(event, mediaId, 'playback.pause'))
  ipcMain.handle('mini:previous', (event, mediaId) => miniPlaybackControl(event, mediaId, 'playback.previous'))
  ipcMain.handle('mini:next', (event, mediaId) => miniPlaybackControl(event, mediaId, 'playback.next'))
  ipcMain.handle('mini:show-main', async (event) => {
    if (!validateMiniPlayerSender(event)) throw new Error('Invalid IPC sender')
    trayActions.show()
  })
  ipcMain.handle('mini:hide', async (event) => {
    if (!validateMiniPlayerSender(event)) throw new Error('Invalid IPC sender')
    if (videoWindow && event.sender === videoWindow.webContents) videoWindow.hide()
    else miniPlayerWindow?.hide()
  })
  ipcMain.handle('backend:video-window', async (event, open: unknown) => {
    if (!validateSender(event)) return { ok: false, error: 'Video window request is invalid' }
    const window = await ensureVideoWindow()
    if (open) {
      if (!window.isDestroyed()) showWindow(window)
    } else if (!window.isDestroyed()) {
      window.hide()
    }
    return { ok: true }
  })
  ipcMain.handle('shell:open-external', async (event, value: unknown) => {
    if (!validateSender(event) || typeof value !== 'string') throw new Error('Invalid external URL')
    const url = new URL(value)
    if (!['https:', 'http:'].includes(url.protocol)) throw new Error('Only HTTP(S) links are allowed')
    await shell.openExternal(url.toString())
  })
  ipcMain.handle('updates:check', async (event) => {
    if (!validateSender(event)) throw new Error('Invalid IPC sender')
    if (!app.isPackaged) return
    setUpdateState({ state: 'checking' })
    await autoUpdater.checkForUpdates()
  })
  ipcMain.handle('updates:install', async (event) => {
    if (!validateSender(event) || updateState.state !== 'downloaded' || !safeToInstall()) return false
    terminalProcess?.write('update prepare\r')
    updatePreparationTimer = setTimeout(() => {
      setUpdateState({ state: 'error', message: 'The backend did not confirm its update backup; installation was cancelled.' })
    }, 30_000)
    return true
  })
}

function configureUpdates() {
  if (!app.isPackaged) return
  autoUpdater.autoDownload = true
  autoUpdater.allowDowngrade = false
  autoUpdater.channel = 'latest'
  autoUpdater.on('checking-for-update', () => setUpdateState({ state: 'checking' }))
  autoUpdater.on('update-available', (info) => setUpdateState({ state: 'available', version: info.version }))
  autoUpdater.on('update-not-available', () => setUpdateState({ state: 'idle' }))
  autoUpdater.on('download-progress', (progress) => setUpdateState({
    state: 'downloading', percent: progress.percent, version: updateState.version,
  }))
  autoUpdater.on('update-downloaded', (info) => setUpdateState({ state: 'downloaded', version: info.version }))
  autoUpdater.on('error', (error) => setUpdateState({ state: 'error', message: error.message }))
  setTimeout(() => void autoUpdater.checkForUpdates().catch((error) => {
    setUpdateState({ state: 'error', message: String(error) })
  }), 10_000)
  setInterval(() => void autoUpdater.checkForUpdates().catch(() => undefined), 6 * 60 * 60 * 1000)
}

const ownsInstanceLock = process.env.MARIANA_E2E === '1' || app.requestSingleInstanceLock()
if (!ownsInstanceLock) app.quit()
else {
  app.on('second-instance', () => {
    trayActions.show()
  })
  app.whenReady().then(async () => {
    registerIpc()
    await createControlServer()
    await createWindow()
    ensureTray()
    startTerminal()
    configureUpdates()
  })
  app.on('before-quit', () => {
    quitting = true
    if (backendStartupTimer) clearTimeout(backendStartupTimer)
    backendStartupTimer = null
    terminalProcess?.write('exit y\r')
    terminalProcess?.kill()
    controlSocket?.destroy()
    controlSocket = null
    finishPendingControlRequests()
    tray?.destroy()
    tray = null
    trayAvailable = false
    controlServer?.close()
    if (process.platform !== 'win32') fs.rmSync(controlEndpoint, { force: true })
  })
  app.on('window-all-closed', () => {
    if (!quitting) trayActions.quit()
  })
  app.on('activate', trayActions.show)
}
