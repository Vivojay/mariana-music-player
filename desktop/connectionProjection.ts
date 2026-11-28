import type { DesktopControlResult } from './shared.js'

export interface AccountRow {
  id: string
  name: string
  hint: string
  verified: string
  linked: boolean
  available: boolean
  pending: boolean
}
export interface AccountReply extends DesktopControlResult {
  rows?: AccountRow[]
  message?: string
}
export function projectAccounts(payload: Record<string, unknown>): AccountReply {
  const rows: AccountRow[] = []
  if (Array.isArray(payload.services)) {
    for (const item of payload.services) {
      if (!item || typeof item !== 'object' || typeof item.id !== 'string' || !/^[a-z]{2,20}$/.test(item.id)) continue
      if (typeof item.name !== 'string' || typeof item.hint !== 'string') continue
      rows.push({ id:item.id, name:item.name.slice(0,80), hint:item.hint.slice(0,80),
        verified:typeof item.identity?.name === 'string' ? item.identity.name.slice(0,200) : '',
        linked:Boolean(item.link), available:item.available === true, pending:item.pending === true })
    }
  }
  return {ok:true, rows, message:typeof payload.message === 'string' ? payload.message.slice(0,6000) : ''}
}
