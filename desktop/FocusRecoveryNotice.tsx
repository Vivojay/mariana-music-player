import { useState } from 'react'
import type { DesktopControlResult } from './shared'

export function FocusRecoveryNotice({ retry }: { retry: () => Promise<DesktopControlResult> }) {
  const [pending, setPending] = useState(false)
  const [rejected, setRejected] = useState(false)
  return <section className="focus-recovery-notice" role="alert" aria-label="Focus Mode recovery">
    <strong>Playback locked — Focus Mode needs recovery</strong>
    <p>Saved restrictions could not be verified. The saved file is preserved; no automatic reset or unlock occurred.</p>
    <p>Restore a known-good active <code>focus-state.json</code> backup in the same application data directory,
      then recheck below or use <code>focus recover</code>. Normal passcode and phone verification still apply.</p>
    <button type="button" disabled={pending} onClick={() => {
      setPending(true)
      setRejected(false)
      void retry().then((result) => setRejected(!result.ok), () => setRejected(true))
        .finally(() => setPending(false))
    }}>{pending ? 'Checking saved state…' : 'Recheck restored active state'}</button>
    {rejected && <p>No valid active state could be restored. Playback stays locked. See <code>help focus</code>.</p>}
  </section>
}
