import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { STORE_NAME, when } from '../format.js'
import { useLoad } from '../hooks.js'
import { setLanguage, useI18n } from '../i18n/index.jsx'
import { ErrorBox, Loading, PageHeader } from '../components/States.jsx'
import OllamaSection from './OllamaSection.jsx'

// Configurações. O servidor valida tudo de novo; aqui é só pra avisar antes.
const RAM_OPTIONS = [4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256]
const NOTIFY_ORDER = ['telegram', 'stdout', 'none']
// mesmas regras do servidor (app/secrets_store.py)
const TOKEN_RX = /^\d{6,12}:[A-Za-z0-9_-]{30,50}$/
const CHAT_RX = /^(-?\d{1,20}|@[A-Za-z0-9_]{4,32})$/
const LANG_LABEL = { 'pt-BR': 'Português (Brasil)', en: 'English' }
const clone = (v) => JSON.parse(JSON.stringify(v))

/** Mesmas regras do servidor (app/tg/channels.py): @nome, nome, t.me/nome ou t.me/s/nome → nome; senão null. */
export function normalizeHandle(text) {
  if (typeof text !== 'string' || text.length > 200) return null
  let s = text.replace(/^ +| +$/g, '')
  if (s.startsWith('@')) s = s.slice(1)
  else if (/[/:]/.test(s)) {
    let u
    try { u = new URL(/^https?:\/\//.test(s) ? s : `https://${s}`) } catch { return null }
    if (!['t.me', 'telegram.me'].includes(u.host) || u.username || u.password || u.search || u.hash || s.includes('@')) return null
    let parts = u.pathname.replace(/^\/+|\/+$/g, '').split('/')
    if (parts.length === 2 && parts[0] === 's') parts = parts.slice(1)
    if (parts.length !== 1) return null
    s = parts[0]
  }
  return /^[A-Za-z0-9_]{4,32}$/.test(s) ? s : null
}

function Origin({ meta }) {
  const { t } = useI18n()
  if (!meta) return null
  const label = meta.source === 'env' ? t('cfg.origin.env', { vars: meta.env.join(', ') })
    : meta.source === 'banco' ? t('cfg.origin.banco') : t('cfg.origin.default')
  return <span className={`chip origin origin-${meta.source}`}>{label}</span>
}

function Section({ id, title, meta, note, error, msg, busy, onSave, onReset, children, extra }) {
  const { t } = useI18n()
  const locked = meta?.locked
  return (
    <section className="card pad cfg-section" aria-labelledby={`cfg-${id}`}>
      <div className="cfg-head">
        <h2 id={`cfg-${id}`}>{title}</h2>
        <Origin meta={meta} />
      </div>
      {note && <p className="muted small cfg-note">{note}</p>}
      {locked && <p className="small cfg-locked">{t('cfg.lockedNotePrefix')}<code>.env</code>{t('cfg.lockedNoteSuffix')}</p>}
      {meta?.env_error && <p className="small cfg-error" role="alert">{t('cfg.envIgnored', { error: meta.env_error })}</p>}
      <fieldset className="cfg-fields" disabled={locked || busy}>
        <legend className="sr-only">{title}</legend>
        {children}
      </fieldset>
      {error && <p className="small cfg-error" role="alert">{error}</p>}
      <div className="cfg-actions">
        <button type="button" className="btn btn-primary" disabled={locked || busy} onClick={onSave}
          aria-label={t('cfg.saveAria', { title })}>{t('cfg.saveBtn')}</button>
        <button type="button" className="btn btn-ghost" disabled={busy || meta?.source !== 'banco'} onClick={onReset}
          aria-label={t('cfg.resetAria', { title })}>{t('cfg.resetBtn')}</button>
        {msg && <span className={`small ${msg.ok ? 'cfg-ok' : 'cfg-error'}`} role={msg.ok ? 'status' : 'alert'}>{msg.msgKey ? t(msg.msgKey) : msg.text}</span>}
      </div>
      {extra}
    </section>
  )
}

function Feedback({ msg, id }) {
  if (!msg) return null
  return <p id={id} className={`small ${msg.ok ? 'cfg-ok' : 'cfg-error'}`} role={msg.ok ? 'status' : 'alert'}>{msg.text}</p>
}

/** Bot do Telegram. O token fica só no campo (sem estado do React) e o campo é limpo ao salvar. */
function TelegramBox({ target }) {
  const { t } = useI18n()
  const tg = useLoad(() => api.telegram(), [])
  const tokenRef = useRef(null)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(null)
  const [tokenMsg, setTokenMsg] = useState(null)
  const [chatMsg, setChatMsg] = useState(null)
  const [testMsg, setTestMsg] = useState(null)
  const [chats, setChats] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [manual, setManual] = useState('')

  const clearToken = () => { if (tokenRef.current) tokenRef.current.value = '' }

  const saveToken = async (e) => {
    e.preventDefault()
    const value = (tokenRef.current?.value || '').trim()
    if (!TOKEN_RX.test(value)) {
      setTokenMsg({ ok: false, text: t('tgBot.invalidToken') })
      return
    }
    setBusy('token')
    setTokenMsg(null)
    try {
      tg.setData(await api.saveTelegram({ token: value }))
      setEditing(false)
      setTokenMsg({ ok: true, text: t('tgBot.tokenSaved') })
    } catch (err) {
      setTokenMsg({ ok: false, text: err.message })
    } finally {
      clearToken()
      setBusy(null)
    }
  }

  const remove = async () => {
    setBusy('remove')
    try {
      tg.setData(await api.removeTelegram())
      setConfirming(false)
      setChats(null)
      setTokenMsg({ ok: true, text: t('tgBot.tokenRemoved') })
    } catch (err) {
      setTokenMsg({ ok: false, text: err.message })
    } finally {
      setBusy(null)
    }
  }

  const detect = async () => {
    setBusy('detect')
    setChatMsg(null)
    setChats(null)
    try {
      const res = await api.detectChat()
      setChats(res.chats)
      if (!res.chats.length) setChatMsg({ ok: false, text: res.hint || t('tgBot.noChatsHint') })
    } catch (err) {
      setChatMsg({ ok: false, text: err.message })
    } finally {
      setBusy(null)
    }
  }

  const pickChat = async (id, label) => {
    if (!CHAT_RX.test(id)) {
      setChatMsg({ ok: false, text: t('tgBot.invalidChatId') })
      return
    }
    setBusy('chat')
    setChatMsg(null)
    try {
      tg.setData(await api.saveTelegram({ chat_id: id }))
      setChats(null)
      setManual('')
      setChatMsg({ ok: true, text: t('tgBot.chatChosen', { label }) })
    } catch (err) {
      setChatMsg({ ok: false, text: err.message })
    } finally {
      setBusy(null)
    }
  }

  const sendTest = async () => {
    setBusy('test')
    setTestMsg(null)
    try {
      await api.notifyTest('telegram')
      setTestMsg({ ok: true, text: t('tgBot.testSent') })
    } catch (err) {
      setTestMsg({ ok: false, text: err.message })
    } finally {
      setBusy(null)
    }
  }

  const st = tg.data
  const tokenEnv = st?.source === 'env'
  const chatEnv = st?.chat_id?.source === 'env'
  const showForm = st && !tokenEnv && (!st.configured || editing)
  return (
    <div className="tg-box" role="group" aria-labelledby="tg-title">
      <h3 id="tg-title">{t('tgBot.title')}</h3>
      {target !== 'telegram' && (
        <p className="muted small">{t('tgBot.chooseAbove')}</p>
      )}
      <ol className="tg-steps">
        <li>{t('tgBot.step1Prefix')}<b>@BotFather</b>{t('tgBot.step1Mid')}<code>/newbot</code>.</li>
        <li>{t('tgBot.step2')}</li>
        <li>{t('tgBot.step3Prefix')}<code>/start</code>.</li>
        <li>{t('tgBot.step4Prefix')}<b>{t('tgBot.findMyChat')}</b>.</li>
      </ol>
      {tg.loading && !st && <Loading />}
      {tg.error && <ErrorBox error={tg.error} onRetry={tg.reload} />}
      {st?.file_error && <p className="small cfg-error" role="alert">{t('tgBot.fileError', { error: st.file_error })}</p>}
      {st && (
        <>
          <div className="tg-row">
            {tokenEnv && (
              <p className="small cfg-locked">{t('tgBot.tokenEnvPrefix')}<code>PCB_TELEGRAM_TOKEN</code>{t('tgBot.tokenEnvSuffix')}<code>.env</code>.</p>
            )}
            {st.configured && !editing && (
              <p className="tg-state">{t('tgBot.tokenState')}<b>{t('tgBot.configured')}</b>{t('tgBot.endsWith', { hint: st.hint })}</p>
            )}
            {st.configured && !editing && !tokenEnv && (
              <div className="cfg-actions">
                <button type="button" className="btn" onClick={() => { setEditing(true); setTokenMsg(null) }}
                  disabled={!!busy}>{t('tgBot.changeBtn')}</button>
                {confirming ? (
                  <span className="cfg-confirm">
                    <button type="button" className="btn btn-danger" onClick={remove} disabled={!!busy}
                      aria-label={t('tgBot.confirmRemoveAria')}>{t('tgBot.removeBtn')}</button>
                    <button type="button" className="btn btn-ghost" onClick={() => setConfirming(false)}>{t('tgBot.cancelBtn')}</button>
                  </span>
                ) : (
                  <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)} disabled={!!busy}
                    aria-label={t('tgBot.removeAria')}>{t('tgBot.removeBtn')}</button>
                )}
              </div>
            )}
            {showForm && (
              <form className="cfg-add" onSubmit={saveToken} noValidate>
                <label htmlFor="tg-token">{t('tgBot.tokenLabel')}</label>
                <div className="cfg-add-row">
                  <input id="tg-token" ref={tokenRef} className="search cfg-input" type="password" autoComplete="off"
                    spellCheck="false" autoCapitalize="off" autoCorrect="off" maxLength={80} placeholder={t('tgBot.tokenPlaceholder')}
                    aria-describedby={tokenMsg ? 'tg-token-msg' : undefined} onChange={() => setTokenMsg(null)} />
                  <button type="submit" className="btn btn-primary" disabled={busy === 'token'}>
                    {busy === 'token' ? t('tgBot.savingBtn') : t('cfg.saveBtn')}
                  </button>
                  {editing && (
                    <button type="button" className="btn btn-ghost" onClick={() => { clearToken(); setEditing(false) }}>{t('tgBot.cancelBtn')}</button>
                  )}
                </div>
              </form>
            )}
            <Feedback msg={tokenMsg} id="tg-token-msg" />
          </div>

          <div className="tg-row">
            <p className="tg-state">
              {t('tgBot.chatState')}{st.chat_id.configured ? <><b>{t('tgBot.configured')}</b>{t('tgBot.endsWith', { hint: st.chat_id.hint })}</> : <b>{t('tgBot.chatNotChosen')}</b>}
            </p>
            {chatEnv && (
              <p className="small cfg-locked">{t('tgBot.chatEnvPrefix')}<code>PCB_TELEGRAM_CHAT_ID</code>).</p>
            )}
            {!chatEnv && (
              <div className="cfg-actions">
                <button type="button" className="btn btn-primary" onClick={detect} disabled={!st.configured || !!busy}>
                  {busy === 'detect' ? t('tgBot.searchingBtn') : t('tgBot.findMyChat')}
                </button>
              </div>
            )}
            {chats && chats.length > 0 && (
              <ul className="tg-chats" aria-label={t('tgBot.chatsListAria')}>
                {chats.map((c) => (
                  <li key={c.id} className="cfg-channel">
                    <div className="cfg-channel-info"><b>{c.nome}</b><span className="muted small">{t(`cfg.chatKind.${c.tipo}`) || c.tipo}</span></div>
                    <button type="button" className="btn btn-sm" onClick={() => pickChat(c.id, c.nome)} disabled={!!busy}
                      aria-label={t('tgBot.useChatAria', { name: c.nome })}>{t('tgBot.useThisBtn')}</button>
                  </li>
                ))}
              </ul>
            )}
            <Feedback msg={chatMsg} />
            {!chatEnv && (
              <details className="tg-manual">
                <summary>{t('tgBot.manualChatSummary')}</summary>
                <form className="cfg-add-row" onSubmit={(e) => { e.preventDefault(); pickChat(manual.trim(), manual.trim()) }} noValidate>
                  <label htmlFor="tg-chat" className="sr-only">{t('tgBot.chatIdLabel')}</label>
                  <input id="tg-chat" className="search cfg-input" type="text" inputMode="text" autoComplete="off"
                    spellCheck="false" maxLength={40} placeholder={t('tgBot.chatIdPlaceholder')} value={manual}
                    onChange={(e) => setManual(e.target.value)} />
                  <button type="submit" className="btn" disabled={!manual.trim() || !!busy}>{t('tgBot.saveChatBtn')}</button>
                </form>
              </details>
            )}
          </div>

          <div className="tg-row">
            <div className="cfg-actions">
              <button type="button" className="btn btn-primary" onClick={sendTest} disabled={!st.ready || !!busy}>
                {busy === 'test' ? t('tgBot.sendingBtn') : t('tgBot.sendTestBtn')}
              </button>
              {!st.ready && <span className="muted small">{t('tgBot.missingTokenOrChat')}</span>}
            </div>
            <Feedback msg={testMsg} />
          </div>
        </>
      )}
    </div>
  )
}

/** Agendador interno: liga/desliga (salva na hora), situação e "Rodar agora". */
function SchedulerBox({ sched, meta, enabled, onToggle }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const s = sched.data

  const toggle = async (on) => {
    setBusy(true)
    setMsg(null)
    try {
      await onToggle(on)
      sched.reload()
      setMsg({ ok: true, text: on ? t('sched.enabledMsg') : t('sched.disabledMsg') })
    } catch (err) {
      setMsg({ ok: false, text: err.fields?.scheduler_enabled || err.message })
    } finally {
      setBusy(false)
    }
  }

  const runNow = async () => {
    setBusy(true)
    setMsg(null)
    try {
      await api.runNow()
      setMsg({ ok: true, text: t('sched.startedMsg') })
      sched.reload()
    } catch (err) {
      setMsg({ ok: false, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  const situation = !s ? '…' : s.running ? t('sched.statusRunning') : s.enabled ? t('sched.statusOn') : t('sched.statusOff')
  return (
    <div className="tg-box" role="group" aria-labelledby="sched-title">
      <h3 id="sched-title">{t('sched.title')}</h3>
      <label className="cfg-check">
        <input type="checkbox" role="switch" checked={!!enabled} disabled={meta?.locked || busy}
          aria-describedby="sched-note" onChange={(e) => toggle(e.target.checked)} />
        {t('sched.switchLabel')}
      </label>
      <p id="sched-note" className="muted small">{t('sched.note')}</p>
      {meta?.locked && <p className="small cfg-locked">{t('sched.lockedEnv')}<code>PCB_SCHEDULER</code>).</p>}
      {sched.error && <p className="small cfg-error" role="alert">{t('sched.readError', { error: sched.error.message })}</p>}
      {s && (
        <dl className="sched-status">
          <div><dt>{t('sched.dtStatus')}</dt><dd>{situation}</dd></div>
          <div><dt>{t('sched.dtLastRun')}</dt><dd>{when(s.last_run_at)}{s.last_run_at && (s.last_ok ? t('sched.lastOk') : t('sched.lastErr'))}</dd></div>
          <div><dt>{t('sched.dtNext')}</dt><dd>{s.enabled ? (s.next_run_at ? when(s.next_run_at) : t('sched.soon')) : '—'}</dd></div>
          {s.last_error && <div><dt>{t('sched.dtError')}</dt><dd className="cfg-error">{s.last_error}</dd></div>}
          {s.skipped === 'jogo' && <div><dt>{t('sched.dtSkipped')}</dt><dd>{t('sched.skippedGame')}</dd></div>}
        </dl>
      )}
      <div className="cfg-actions">
        <button type="button" className="btn" onClick={runNow} disabled={busy || s?.running}>{t('sched.runNowBtn')}</button>
      </div>
      <Feedback msg={msg} />
    </div>
  )
}

function ChannelsSection({ max }) {
  const { t } = useI18n()
  const { data, error, loading, reload, setData } = useLoad(() => api.channels(), [])
  const [handle, setHandle] = useState('')
  const [addError, setAddError] = useState(null)
  const [adding, setAdding] = useState(false)
  const [rowError, setRowError] = useState(null)
  const [confirming, setConfirming] = useState(null)
  const [done, setDone] = useState(null)

  const add = async (e) => {
    e.preventDefault()
    setDone(null)
    const slug = normalizeHandle(handle)
    if (!slug) {
      setAddError(t('chCfg.invalidHandle'))
      return
    }
    setAdding(true)
    setAddError(null)
    try {
      const ch = await api.addChannel(handle.trim())
      setData((list) => [...(list || []).filter((c) => c.slug !== ch.slug), ch])
      setHandle('')
      setDone(t('chCfg.added', { slug: ch.slug }))
    } catch (err) {
      setAddError(err.message)
    } finally {
      setAdding(false)
    }
  }

  const toggle = async (c) => {
    setRowError(null)
    try {
      const ch = await api.setChannel(c.slug, !c.enabled)
      setData((list) => list.map((x) => (x.slug === ch.slug ? ch : x)))
    } catch (err) {
      setRowError(`@${c.slug}: ${err.message}`)
    }
  }

  const remove = async (c) => {
    setRowError(null)
    try {
      await api.removeChannel(c.slug)
      setData((list) => list.filter((x) => x.slug !== c.slug))
      setConfirming(null)
    } catch (err) {
      setRowError(`@${c.slug}: ${err.message}`)
    }
  }

  const list = data || []
  return (
    <section className="card pad cfg-section cfg-channels" aria-labelledby="cfg-channels">
      <div className="cfg-head">
        <h2 id="cfg-channels">{t('chCfg.title')}</h2>
        {data && <span className="chip">{t('chCfg.countOf', { n: list.length, max })}</span>}
      </div>
      <p className="muted small cfg-note">{t('chCfg.note')}</p>
      <form className="cfg-add" onSubmit={add} noValidate>
        <label htmlFor="cfg-add-channel">{t('chCfg.addLabel')}</label>
        <div className="cfg-add-row">
          <input id="cfg-add-channel" className="search cfg-input" type="text" autoComplete="off" spellCheck="false"
            placeholder={t('chCfg.addPlaceholder')} maxLength={200} value={handle}
            aria-invalid={addError ? 'true' : undefined} aria-describedby={addError ? 'cfg-add-error' : undefined}
            onChange={(e) => { setHandle(e.target.value); setAddError(null) }} />
          <button type="submit" className="btn btn-primary" disabled={adding || !handle.trim() || list.length >= max}>
            {adding ? t('chCfg.checkingPreview') : t('chCfg.addBtn')}
          </button>
        </div>
        {addError && <p id="cfg-add-error" className="small cfg-error" role="alert">{addError}</p>}
        {done && <p className="small cfg-ok" role="status">{done}</p>}
      </form>
      {loading && !data && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {rowError && <p className="small cfg-error" role="alert">{rowError}</p>}
      {data && (
        <ul className="cfg-channel-list">
          {list.map((c) => (
            <li key={c.slug} className={c.enabled ? 'cfg-channel' : 'cfg-channel off'}>
              <label className="switch">
                <input type="checkbox" role="switch" checked={c.enabled} onChange={() => toggle(c)}
                  aria-label={t('chCfg.readAria', { slug: c.slug })} />
                <span className="switch-ui" aria-hidden="true" />
              </label>
              <div className="cfg-channel-info">
                <b>@{c.slug}</b>{c.title && <span className="muted"> · {c.title}</span>}
                <span className="muted small">
                  {t('chCfg.offersAndLast', { posts: c.posts, when: when(c.last_ok_at) })}
                  {c.fail_count >= 3 && <> · <span className="cfg-error" title={c.last_error || ''}>{t('chCfg.failing')}</span></>}
                </span>
              </div>
              {confirming === c.slug ? (
                <span className="cfg-confirm">
                  <button type="button" className="btn btn-sm btn-danger" onClick={() => remove(c)}
                    aria-label={t('chCfg.confirmRemoveAria', { slug: c.slug })}>{t('tgBot.removeBtn')}</button>
                  <button type="button" className="btn btn-sm btn-ghost" onClick={() => setConfirming(null)}>{t('tgBot.cancelBtn')}</button>
                </span>
              ) : (
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setConfirming(c.slug)}
                  aria-label={t('chCfg.removeAria', { slug: c.slug })}>{t('tgBot.removeBtn')}</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Num({ id, label, value, onChange, min, max, suffix }) {
  return (
    <div className="cfg-field">
      <label htmlFor={id}>{label}</label>
      <span className="cfg-num">
        <input id={id} className="search cfg-input" type="number" inputMode="numeric" min={min} max={max} step="1"
          aria-describedby={suffix ? `${id}-unit` : undefined}
          value={value ?? ''} onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))} />
        {suffix && <span id={`${id}-unit`} className="muted small">{suffix}</span>}
      </span>
    </div>
  )
}

function Select({ id, label, value, options, onChange, labels = {} }) {
  return (
    <div className="cfg-field">
      <label htmlFor={id}>{label}</label>
      <select id={id} className="search cfg-input" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o} value={o}>{labels[o] || o}</option>)}
      </select>
    </div>
  )
}

function Text({ id, label, value, onChange, maxLength = 80, placeholder }) {
  return (
    <div className="cfg-field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="search cfg-input" type="text" maxLength={maxLength} value={value ?? ''}
        placeholder={placeholder} autoComplete="off" onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}

export default function Settings() {
  const { t } = useI18n()
  const st = useLoad(() => api.settings(), [])
  const sched = useLoad(() => api.scheduler(), [])
  const [draft, setDraft] = useState(null)
  const [errors, setErrors] = useState({})
  const [msgs, setMsgs] = useState({})
  const [busy, setBusy] = useState(null)

  useEffect(() => {
    if (st.data) {
      if (st.data.values?.language) setLanguage(st.data.values.language)
      if (!draft) setDraft(clone(st.data.values))
    }
  }, [st.data, draft])

  if (st.loading && !st.data) return <section><PageHeader title={t('cfg.title')} /><Loading /></section>
  if (st.error) return <section><PageHeader title={t('cfg.title')} /><ErrorBox error={st.error} onRetry={st.reload} /></section>
  if (!draft) return null

  const { meta, options } = st.data
  const set = (key, value) => setDraft((d) => ({ ...d, [key]: value }))
  const setIn = (key, field, value) => setDraft((d) => ({ ...d, [key]: { ...d[key], [field]: value } }))

  const finish = (key, res, msgKey) => {
    if (res?.values?.language) setLanguage(res.values.language)
    st.setData(res)
    setDraft((d) => ({ ...d, [key]: clone(res.values[key]) }))
    setErrors((e) => ({ ...e, [key]: null }))
    setMsgs((m) => ({ ...m, [key]: { ok: true, msgKey } }))
  }

  const save = async (key) => {
    const value = draft[key]
    if (key === 'stores' && !Object.values(value).some(Boolean)) {
      setErrors((e) => ({ ...e, stores: t('cfg.storesMinError') }))
      setMsgs((m) => ({ ...m, stores: null }))
      return
    }
    setBusy(key)
    setMsgs((m) => ({ ...m, [key]: null }))
    try {
      finish(key, await api.saveSettings({ [key]: value }), 'cfg.saved')
    } catch (err) {
      setErrors((e) => ({ ...e, [key]: err.fields?.[key] || err.message }))
      setMsgs((m) => ({ ...m, [key]: { ok: false, msgKey: 'cfg.notSaved' } }))
    } finally {
      setBusy(null)
    }
  }

  const reset = async (key) => {
    setBusy(key)
    try {
      finish(key, await api.resetSetting(key), 'cfg.restored')
    } catch (err) {
      setMsgs((m) => ({ ...m, [key]: { ok: false, text: err.message } }))
    } finally {
      setBusy(null)
    }
  }

  // o interruptor do agendador salva na hora (sem botão Salvar)
  const toggleScheduler = async (on) => {
    const res = await api.saveSettings({ scheduler_enabled: on })
    st.setData(res)
    setDraft((d) => ({ ...d, scheduler_enabled: res.values.scheduler_enabled }))
  }

  const props = (key, title, note) => ({
    id: key, title, note, meta: meta[key], error: errors[key], msg: msgs[key], busy: busy === key,
    onSave: () => save(key), onReset: () => reset(key),
  })
  const pc = draft.current_pc
  const ramOptions = RAM_OPTIONS.includes(pc.ram_gb) || typeof pc.ram_gb !== 'number' ? RAM_OPTIONS
    : [...RAM_OPTIONS, pc.ram_gb].sort((a, b) => a - b)
  const notifyLabels = {
    telegram: t('cfg.notify.telegram'),
    stdout: t('cfg.notify.stdout'),
    none: t('cfg.notify.none'),
  }

  return (
    <section className="cfg">
      <PageHeader title={t('cfg.title')} subtitle={t('cfg.subtitle')} />

      <ChannelsSection max={options.max_channels} />

      <Section {...props('stores', t('cfg.storesTitle'), t('cfg.storesNote'))}>
        <div className="cfg-checks">
          {options.stores.map((s) => (
            <label key={s} className="cfg-check">
              <input type="checkbox" checked={!!draft.stores[s]} onChange={(e) => setIn('stores', s, e.target.checked)} />
              {STORE_NAME[s] || s}
            </label>
          ))}
        </div>
      </Section>

      <Section {...props('collect_every_minutes', t('cfg.collectTitle'), t('cfg.collectNote'))}
        extra={<SchedulerBox sched={sched} meta={meta.scheduler_enabled} enabled={draft.scheduler_enabled}
          onToggle={toggleScheduler} />}>
        <Num id="cfg-collect" label={t('cfg.collectEveryLabel')} value={draft.collect_every_minutes} suffix={t('cfg.minutesSuffix')}
          min={options.collect_every_minutes.min} max={options.collect_every_minutes.max}
          onChange={(v) => set('collect_every_minutes', v)} />
      </Section>

      <Section {...props('current_pc', t('cfg.pcTitle'), t('cfg.pcNote'))}>
        <div className="cfg-grid">
          <Text id="cfg-pc-cpu" label={t('cfg.pcCpu')} value={pc.cpu} onChange={(v) => setIn('current_pc', 'cpu', v)} />
          <Text id="cfg-pc-board" label={t('cfg.pcBoard')} value={pc.motherboard} onChange={(v) => setIn('current_pc', 'motherboard', v)} />
          <Text id="cfg-pc-gpu" label={t('cfg.pcGpu')} value={pc.gpu} onChange={(v) => setIn('current_pc', 'gpu', v)} />
          <Select id="cfg-pc-socket" label={t('cfg.pcSocket')} value={pc.socket} options={options.sockets}
            onChange={(v) => setIn('current_pc', 'socket', v)} />
          <Select id="cfg-pc-mem" label={t('cfg.pcMem')} value={pc.memory_type} options={options.memory_types}
            onChange={(v) => setIn('current_pc', 'memory_type', v)} />
          <Select id="cfg-pc-ff" label={t('cfg.pcFf')} value={pc.form_factor} options={options.form_factors}
            onChange={(v) => setIn('current_pc', 'form_factor', v)} />
          <Select id="cfg-pc-ram" label={t('cfg.pcRam')} value={String(pc.ram_gb)} options={ramOptions.map(String)}
            onChange={(v) => setIn('current_pc', 'ram_gb', Number(v))} />
        </div>
      </Section>

      <Section {...props('price_range', t('cfg.priceTitle'), t('cfg.priceNote'))}>
        <div className="cfg-grid">
          <Num id="cfg-price-min" label={t('cfg.priceMin')} value={draft.price_range.min} suffix="R$" min={0} max={options.price_max}
            onChange={(v) => setIn('price_range', 'min', v)} />
          <Num id="cfg-price-max" label={t('cfg.priceMax')} value={draft.price_range.max} suffix="R$" min={0} max={options.price_max}
            onChange={(v) => setIn('price_range', 'max', v)} />
        </div>
      </Section>

      <Section {...props('game_mode', t('cfg.gameTitle'), t('cfg.gameNote'))}>
        {sched.data?.game_mode_available === false && (
          <p className="small cfg-locked">{t('cfg.gameDockerUnavailable')}</p>
        )}
        <label className="cfg-check">
          <input type="checkbox" role="switch" checked={draft.game_mode} onChange={(e) => set('game_mode', e.target.checked)} />
          {t('cfg.gameSwitch')}
        </label>
      </Section>

      <Section {...props('notify_target', t('cfg.notifyTitle'), t('cfg.notifyNote'))}
        extra={<TelegramBox target={st.data.values.notify_target} />}>
        <Select id="cfg-notify" label={t('cfg.notifyTargetLabel')} value={draft.notify_target}
          options={NOTIFY_ORDER.filter((o) => options.notify_targets.includes(o))}
          labels={notifyLabels} onChange={(v) => set('notify_target', v)} />
      </Section>

      <OllamaSection values={st.data.values} meta={meta} options={options} origin={<Origin meta={meta.ollama} />}
        onSaved={(res) => {
          st.setData(res)
          setDraft((d) => ({ ...d, ollama: clone(res.values.ollama), classifier: res.values.classifier }))
        }} />

      <Section {...props('language', t('cfg.langTitle'), t('cfg.langNote'))}>
        <Select id="cfg-lang" label={t('cfg.langLabel')} value={draft.language} options={options.languages} labels={LANG_LABEL}
          onChange={(v) => set('language', v)} />
      </Section>
    </section>
  )
}
