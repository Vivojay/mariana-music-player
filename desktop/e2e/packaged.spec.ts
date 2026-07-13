import { _electron as electron, expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { mkdir, mkdtemp, readFile, readdir, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

const executable = process.env.MARIANA_PACKAGED_EXE
const expectedVersion = JSON.parse(await readFile(path.resolve('package.json'), 'utf8')).version as string

test.describe.configure({ timeout: 120_000 })

async function isolatedState(name: string) {
  return mkdtemp(path.join(os.tmpdir(), `mariana-${name}-`))
}

async function launchWithSetup(userData: string) {
  const inheritedPath = process.env.PATH ?? process.env.Path ?? ''
  const mediaToolPath = process.env.MARIANA_TEST_FFMPEG_BIN
  return electron.launch({
    executablePath: executable,
    args: [`--user-data-dir=${userData}`],
    env: {
      ...process.env,
      PATH: mediaToolPath ? `${mediaToolPath}${path.delimiter}${inheritedPath}` : inheritedPath,
      MARIANA_E2E: '1',
      MARIANA_E2E_FIRST_BOOT: '1',
      MARIANA_E2E_DATA_DIR: userData,
    },
  })
}

async function writeCommand(page: Page, value: string) {
  await page.evaluate((text) => window.mariana.terminal.write(`${text}\r`), value)
}

async function advancePastToolSetup(page: Page) {
  const terminal = page.getByLabel('Terminal output')
  await expect.poll(async () => terminal.textContent(), { timeout: 45_000 }).toMatch(
    /Automatically download verified recommended tools|Do you have any locally stored\/downloaded music files?/,
  )
  if ((await terminal.textContent())?.includes('Automatically download verified recommended tools')) {
    // Packaged setup behavior is tested without contacting release providers.
    // The verified automatic-download path has deterministic Python coverage.
    await writeCommand(page, '3')
  }
  await expect(terminal).toContainText('Do you have any locally stored/downloaded music files?', { timeout: 45_000 })
}

async function completeSetup(page: Page) {
  const terminal = page.getByLabel('Terminal output')
  await advancePastToolSetup(page)
  await writeCommand(page, 'n')
  await expect(terminal).toContainText('signature collection of 25 sample songs', { timeout: 10_000 })
  await writeCommand(page, 'n')
  await expect(terminal).toContainText('Would you like to run Mariana Player now?', { timeout: 10_000 })
  await writeCommand(page, 'y')
  await expect(terminal).toContainText('Mariana Player', { timeout: 30_000 })
  await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 45_000 })
}

test('packaged Electron app launches its bundled CLI backend', async () => {
  test.skip(!executable, 'set MARIANA_PACKAGED_EXE after npm run pack')
  const application = await electron.launch({
    executablePath: executable,
    args: [`--user-data-dir=${path.resolve('temp', 'packaged-electron-state')}`],
    env: { ...process.env, MARIANA_E2E: '1' },
  })
  try {
    const page = await application.firstWindow()
    page.on('console', (message) => console.log(`[packaged:${message.type()}] ${message.text()}`))
    page.on('pageerror', (error) => console.error(`[packaged:error] ${error.message}`))
    await expect(page).toHaveTitle('Mariana')
    await expect(page.getByLabel('Mariana command terminal')).toBeVisible()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 45_000 })
    await page.evaluate(() => window.mariana.terminal.write('sleep status\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Sleep timer is inactive', { timeout: 10_000 })
  } finally {
    await application.close()
  }
})

test('packaged YouTube downloads stay in the current PTY session', async () => {
  test.skip(!executable, 'set MARIANA_PACKAGED_EXE after npm run pack')
  const userData = await isolatedState('download-session')
  const inheritedPath = process.env.PATH ?? process.env.Path ?? ''
  const mediaToolPath = process.env.MARIANA_TEST_FFMPEG_BIN
  const application = await electron.launch({
    executablePath: executable,
    args: [`--user-data-dir=${userData}`],
    env: {
      ...process.env,
      PATH: mediaToolPath ? `${mediaToolPath}${path.delimiter}${inheritedPath}` : inheritedPath,
      MARIANA_E2E: '1',
      MARIANA_E2E_DATA_DIR: userData,
    },
  })
  try {
    const page = await application.firstWindow()
    const terminal = page.getByLabel('Terminal output')
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 45_000 })
    await expect(terminal).toContainText(`v ${expectedVersion}`)
    await writeCommand(page, 'youtube auth status')
    await expect(terminal).toContainText('YouTube browser profile: not configured')
    await writeCommand(page, 'youtube auth set firefox')
    await expect(terminal).toContainText('YouTube browser profile set to firefox')
    await writeCommand(page, 'youtube auth clear')
    await expect(terminal).toContainText('YouTube browser authentication cleared')
    await writeCommand(page, 'clear')
    await expect(terminal).not.toContainText('Loaded 1/31', { timeout: 10_000 })
    await writeCommand(page, 'download-ya https://www.youtube.com/watch?v=abc12345678')
    await expect(terminal).toContainText('confirm AUDIO download', { timeout: 10_000 })
    await writeCommand(page, 'y')
    await expect(terminal).toContainText('YouTube audio download started in this Mariana session.', {
      timeout: 10_000,
    })
    await page.waitForTimeout(2_000)
    await expect(terminal).not.toContainText('Loaded 1/31')
    await expect(page.locator('.backend-dot.ready')).toBeVisible()
  } finally {
    await application.close()
  }
})

test('packaged live YouTube audio download completes in the current session', async () => {
  const liveUrl = process.env.MARIANA_LIVE_DOWNLOAD_URL
  const expectedResult = process.env.MARIANA_LIVE_EXPECT_AUTH_CHALLENGE === '1' ? 'auth-required' : 'completed'
  test.skip(!executable || !liveUrl, 'set the packaged executable and an explicit live download URL')
  test.setTimeout(300_000)
  const userData = await isolatedState('live-download')
  const runtime = path.join(userData, 'runtime')
  const downloads = path.join(userData, 'Music')
  await mkdir(path.join(runtime, 'settings'), { recursive: true })
  await mkdir(downloads, { recursive: true })
  const defaults = await readFile(path.resolve('settings', 'settings.yml.default'), 'utf8')
  const browserProfile = process.env.MARIANA_LIVE_BROWSER_PROFILE
  const configured = browserProfile
    ? defaults.replace('browser profile:', `browser profile: ${JSON.stringify(browserProfile)}`)
    : defaults
  await writeFile(
    path.join(runtime, 'settings', 'settings.yml'),
    configured.replace('downloads folder: ~/Music', `downloads folder: ${downloads.replaceAll('\\', '/')}`),
    'utf8',
  )
  const inheritedPath = process.env.PATH ?? process.env.Path ?? ''
  const mediaToolPath = process.env.MARIANA_TEST_FFMPEG_BIN
  const application = await electron.launch({
    executablePath: executable,
    env: {
      ...process.env,
      PATH: mediaToolPath ? `${mediaToolPath}${path.delimiter}${inheritedPath}` : inheritedPath,
      MARIANA_E2E: '1',
      MARIANA_E2E_DATA_DIR: userData,
    },
  })
  try {
    const page = await application.firstWindow()
    const terminal = page.getByLabel('Terminal output')
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 45_000 })
    await writeCommand(page, 'clear')
    await expect(terminal).not.toContainText('Loaded 1/31', { timeout: 10_000 })
    await writeCommand(page, `download-ya ${liveUrl}`)
    await expect(terminal).toContainText('confirm AUDIO download', { timeout: 20_000 })
    await writeCommand(page, 'y')
    await expect
      .poll(
        async () => {
          const output = (await terminal.textContent()) ?? ''
          if (output.includes('YouTube audio download completed.')) return 'completed'
          if (output.includes('YouTube requires a signed-in browser session')) return 'auth-required'
          if (output.includes('Secure YouTube connection failed') || output.includes('YouTube download failed')) return 'failed'
          return 'pending'
        },
        { timeout: 180_000 },
      )
      .toBe(expectedResult)
    await expect(terminal).not.toContainText('Loaded 1/31')
    if (expectedResult === 'completed') {
      const files = await readdir(path.join(downloads, 'MarianaPlayer'))
      expect(files.some((file) => file.toLowerCase().endsWith('.mp3'))).toBe(true)
    }
  } finally {
    await application.close()
  }
})

test('first boot completes once and does not return on relaunch', async () => {
  test.skip(!executable, 'set MARIANA_PACKAGED_EXE after npm run pack')
  const userData = await isolatedState('setup-once')
  const first = await launchWithSetup(userData)
  try {
    await completeSetup(await first.firstWindow())
  } finally {
    await first.close()
  }

  const second = await launchWithSetup(userData)
  try {
    const page = await second.firstWindow()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 45_000 })
    await writeCommand(page, 'setup status')
    const terminal = page.getByLabel('Terminal output')
    await expect(terminal).toContainText('Setup: complete', { timeout: 10_000 })
    await expect(terminal).not.toContainText('Do you have any locally stored/downloaded music files?')
  } finally {
    await second.close()
  }
})

test('interrupted first boot resumes instead of silently restarting', async () => {
  test.skip(!executable, 'set MARIANA_PACKAGED_EXE after npm run pack')
  const userData = await isolatedState('setup-interrupted')
  const first = await launchWithSetup(userData)
  try {
    await advancePastToolSetup(await first.firstWindow())
  } finally {
    await first.close()
  }

  const second = await launchWithSetup(userData)
  try {
    const page = await second.firstWindow()
    const terminal = page.getByLabel('Terminal output')
    await expect(terminal).toContainText('Previous setup did not complete', { timeout: 45_000 })
    await writeCommand(page, 'r')
    await completeSetup(page)
  } finally {
    await second.close()
  }
})

test('corrupt first-boot state offers repair and completes safely', async () => {
  test.skip(!executable, 'set MARIANA_PACKAGED_EXE after npm run pack')
  const userData = await isolatedState('setup-corrupt')
  const first = await launchWithSetup(userData)
  try {
    await advancePastToolSetup(await first.firstWindow())
  } finally {
    await first.close()
  }
  await writeFile(path.join(userData, 'runtime', 'setup-state.json'), '{corrupt', 'utf8')

  const second = await launchWithSetup(userData)
  try {
    const page = await second.firstWindow()
    const terminal = page.getByLabel('Terminal output')
    await expect(terminal).toContainText('Setup state is corrupt', { timeout: 45_000 })
    await writeCommand(page, 'y')
    await completeSetup(page)
  } finally {
    await second.close()
  }
})
