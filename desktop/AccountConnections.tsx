import { useEffect, useState } from 'react'
import type { AccountReply, AccountRow } from './connectionProjection'

export function AccountConnections({ close }: {close: () => void}) {
  const [rows,setRows] = useState<AccountRow[]>([])
  const [id,setId] = useState('spotify')
  const [handle,setHandle] = useState('')
  const [info,setInfo] = useState('')
  const [listener, setListener] = useState('')
  const [profileInfo, setProfileInfo] = useState('')
  const [busy,setBusy] = useState(false)
  const row = rows.find(item=>item.id === id)
  function accept(result?: AccountReply) {
    if (result?.rows) setRows(result.rows)
    setInfo(result?.message || result?.error || '')
  }
  useEffect(()=>{
    let active = true
    window.mariana.backend.accounts?.(['list']).then(result=>{if (active) accept(result)}).catch(()=>{if (active) setInfo('Could not load connections.')})
    return ()=>{active = false}
  },[])
  async function run(op: string, ...args: string[]) {
    setBusy(true)
    try { accept(await window.mariana.backend.accounts?.(op==='list'?['list']:[op,id,...args])) }
    catch { setInfo('The account service is unavailable.') }
    finally { setBusy(false) }
  }
  async function profile(op: 'list' | 'create' | 'use') {
    setBusy(true)
    try {
      const args = op === 'list' ? ['profile', op] : ['profile', op, listener.trim()]
      const reply = await window.mariana.backend.accounts?.(args)
      setProfileInfo(reply?.message || reply?.error || 'The profile service is unavailable.')
    } catch { setProfileInfo('Could not reach the player backend.') }
    finally { setBusy(false) }
  }
  return <aside className="timer-popover account-popover" aria-label="Connections">
    <div className="popover-heading"><strong>Connections</strong><button onClick={close} aria-label="Close connections">×</button></div>
    <details onToggle={event => { if (event.currentTarget.open) void profile('list') }}>
      <summary>Listener profiles</summary>
      <pre aria-live="polite">{profileInfo}</pre>
      <label>Listener name <input maxLength={40} value={listener} onChange={event => setListener(event.target.value)}/></label>
      <div className="account-buttons">
        <button disabled={busy || !listener.trim()} onClick={() => void profile('create')}>Create</button>
        <button disabled={busy || !listener.trim()} onClick={() => void profile('use')}>Use on next launch</button>
        <button disabled={busy} onClick={() => void profile('list')}>List profiles</button>
      </div>
    </details>
    <label>Music and social accounts <select value={id} onChange={event=>{setId(event.target.value);setHandle('');setInfo('')}}>
      {rows.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    {row && <><p>{row.verified ? 'Signed in as ' + row.verified : row.pending ? 'Waiting for your browser' : row.available ? 'Browser sign-in available' : 'Public profile links available'}</p>
      <div className="account-buttons">
        {!row.pending && !row.verified && row.available && <button disabled={busy} onClick={()=>void run('connect')}>Connect {row.name}</button>}
        {row.pending && <><button disabled={busy} onClick={()=>void run(id==='lastfm'?'finish':'list')}>{id==='lastfm'?'Finish sign-in':'Check sign-in'}</button><button disabled={busy} onClick={()=>void run('cancel')}>Cancel</button></>}
        {row.verified && <><button disabled={busy} onClick={()=>void run('verify')}>Verify</button><button disabled={busy} onClick={()=>void run('disconnect')}>Disconnect</button></>}
        {(row.verified && ['youtube','spotify','lastfm'].includes(id) || row.linked && id==='listenbrainz') && <button disabled={busy} onClick={()=>void run('activity')}>{id==='lastfm'||id==='listenbrainz'?'Recent listens':'My playlists'}</button>}
      </div>
      <label>{row.hint}<input maxLength={80} value={handle} onChange={event=>setHandle(event.target.value)}/></label>
      <div className="account-buttons"><button disabled={busy || !handle.trim()} onClick={()=>void run('link',handle)}>Save profile link</button>
        <button disabled={busy} onClick={()=>void run('open')}>{row.linked?'Open saved profile':'Open '+row.name}</button>
        {row.linked && <button disabled={busy} onClick={()=>void run('unlink')}>Remove link</button>}</div></>}
    <p role="status">{info}</p>
  </aside>
}
