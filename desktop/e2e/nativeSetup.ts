import { createIsolatedRuntime } from './isolatedRuntime'

export default async function setup() {
  const runtime = await createIsolatedRuntime()
  process.env.MARIANA_E2E_APP_DIR = runtime.directory
  process.env.MARIANA_PYTHON = runtime.python
  return runtime.cleanup
}
