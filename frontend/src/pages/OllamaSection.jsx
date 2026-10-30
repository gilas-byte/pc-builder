import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { num } from '../format.js'
import { useLoad } from '../hooks.js'
import { t as translateCurrent, useI18n } from '../i18n/index.jsx'
import { KIND_LABEL } from './Channels.jsx'

// IA local: modo do classificador, estado do Ollama, endereço, modelos, download e teste rápido.
// O servidor valida tudo de novo. Polling só enquanto há download (a cada PULL_POLL_MS) e para ao sair da página.
export const PULL_POLL_MS = 1000
const MODES = [
  ['auto', 'ai.mode.auto', 'ai.mode.autoHelp'],
  ['rules', 'ai.mode.rules', 'ai.mode.rulesHelp'],
  ['ollama', 'ai.mode.ollama', 'ai.mode.ollamaHelp'],
]
const SUGGESTED = ['qwen2.5:3b', 'llama3.2:3b', 'gemma3:4b']
const MODEL_RX = /^[a-z0-9][a-z0-9._-]*(\/[a-z0-9][a-z0-9._-]*)*(:[A-Za-z0-9._-]+)?$/   // mesma regra do servidor
const MAX_TEXT = 2000

const tagged = (n) => {
  const s = n.replace(/^registry\.ollama\.ai\//, '').replace(/^library\//, '')
  return s.split('/').pop().includes(':') ? s : `${s}:latest`
}
const gb = (bytes) => (typeof bytes === 'number' ? `${num(bytes / 1e9, { maximumFractionDigits: 1 })} GB` : '')
export const pctText = (pct) => `${num(pct, { maximumFractionDigits: 1 })}%`
const validModel = (m) => m.length <= 100 && !m.includes('..') && MODEL_RX.test(m)
const kindName = (k) => (k ? KIND_LABEL[k] || k : translateCurrent('ai.noKind'))

function Msg({ msg }) {
  if (!msg) return null
  return <p className={`small ${msg.ok ? 'cfg-ok' : 'cfg-error'}`} role={msg.ok ? 'status' : 'alert'}>{msg.text}</p>
}

export default function OllamaSection({ values, meta, options, origin, onSaved }) {
  const { t } = useI18n()
  const status = useLoad(() => api.ollamaStatus(), [])
  const info = useLoad(() => api.classifier(), [])
  const models = useLoad(() => api.ollamaModels(), [])
  const [url, setUrl] = useState(values.ollama.url)
  const [chosen, setChosen] = useState(values.ollama.models)
  const [busy, setBusy] = useState(null)
  const [msgs, setMsgs] = useState({})
  const [tested, setTested] = useState(null)
  const [pull, setPull] = useState(null)
  const [pullName, setPullName] = useState('')
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)

  const say = (key, ok, txt) => setMsgs((m) => ({ ...m, [key]: { ok, text: txt } }))
  const lockedOllama = meta.ollama?.locked
  const lockedMode = meta.classifier?.locked
  const max = options.max_models || 3
  const pct = info.data?.rules_metrics?.pct

  useEffect(() => { setUrl(values.ollama.url); setChosen(values.ollama.models) }, [values.ollama])

  // download: lê o estado uma vez; depois, só enquanto estiver baixando
  useEffect(() => { api.pullStatus().then(setPull).catch(() => {}) }, [])
  const running = pull?.state === 'running'
  useEffect(() => {
    if (!running) return undefined
    const tmr = setInterval(() => { api.pullStatus().then(setPull).catch(() => {}) }, PULL_POLL_MS)
    return () => clearInterval(tmr)
  }, [running])
  const finished = pull?.state === 'done'
  useEffect(() => {
    if (finished) { models.reload(); status.reload() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished])

  const save = async (key, body, okKey) => {
    setBusy(key)
    setMsgs((m) => ({ ...m, [key]: null }))
    try {
      onSaved(await api.saveSettings(body))
      say(key, true, t(okKey))
      status.reload()
      info.reload()
    } catch (err) {
      say(key, false, err.fields?.ollama || err.fields?.classifier || err.message)
    } finally {
      setBusy(null)
    }
  }

  const setMode = (mode) => save('mode', { classifier: mode }, 'ai.modeSaved')
  const saveUrl = () => save('url', { ollama: { url: url.trim(), models: values.ollama.models } }, 'ai.urlSaved')
  const saveModels = () => {
    if (!chosen.length) return say('models', false, t('ai.chooseMin1'))
    return save('models', { ollama: { url: values.ollama.url, models: chosen } }, 'ai.modelsSaved')
  }

  const testUrl = async () => {
    setBusy('test-url')
    setTested(null)
    try {
      const s = await api.ollamaStatus(url.trim())
      setTested(s.reachable ? { ok: true, text: t('ai.urlReachable', { version: s.version }) }
        : { ok: false, text: t('ai.urlUnreachable', { error: s.error }) })
    } catch (err) {
      setTested({ ok: false, text: err.message })
    } finally {
      setBusy(null)
    }
  }

  const toggle = (name, on) => setChosen((c) => (on ? [...c, name].slice(0, max) : c.filter((x) => x !== name)))

  const startPull = async (e) => {
    e.preventDefault()
    const name = pullName.trim()
    if (!validModel(name)) return say('pull', false, t('ai.invalidModelName'))
    setMsgs((m) => ({ ...m, pull: null }))
    try {
      setPull(await api.pull(name))
      setPullName('')
    } catch (err) {
      say('pull', false, err.message)
    }
    return undefined
  }
  const cancelPull = async () => {
    try { await api.cancelPull(); setPull(await api.pullStatus()) } catch (err) { say('pull', false, err.message) }
  }

  const runTest = async (e) => {
    e.preventDefault()
    if (!text.trim()) return say('test', false, t('ai.pasteTitleFirst'))
    setBusy('test')
    setResult(null)
    setMsgs((m) => ({ ...m, test: null }))
    try {
      setResult(await api.classifyTest(text))
    } catch (err) {
      say('test', false, err.message)
    } finally {
      setBusy(null)
    }
    return undefined
  }

  const s = status.data
  const mode = values.classifier
  const installed = models.data?.models || []
  const names = [...installed.map((m) => m.name)]
  for (const m of chosen) if (!names.some((n) => tagged(n) === tagged(m))) names.push(m)
  const sizeOf = (n) => installed.find((m) => tagged(m.name) === tagged(n))
  const counts = info.data?.counts

  return (
    <section className="card pad cfg-section ai" aria-labelledby="cfg-ollama">
      <div className="cfg-head">
        <h2 id="cfg-ollama">{t('ai.title')}</h2>
        {origin}
      </div>
      <p className="muted small cfg-note">{t('ai.note')}</p>
      <p className="ai-rules-note">
        {t('ai.rulesNote')}
        {typeof pct === 'number' ? <>{t('ai.rulesNoteAccuracy')}<b>{pctText(pct)}</b>{t('ai.rulesNoteExamples')}</> : null}.
      </p>

      <fieldset className="cfg-fields ai-modes" disabled={lockedMode || busy === 'mode'}>
        <legend>{t('ai.modeLegend')}</legend>
        {MODES.map(([value, labelKey, helpKey]) => (
          <label key={value} className="cfg-check ai-mode">
            <input type="radio" name="ai-mode" value={value} checked={mode === value}
              aria-describedby={`ai-mode-${value}`} onChange={() => setMode(value)} />
            <span><b>{t(labelKey)}</b><span id={`ai-mode-${value}`} className="muted small"> {t(helpKey)}</span></span>
          </label>
        ))}
      </fieldset>
      {lockedMode && <p className="small cfg-locked">{t('ai.modeLocked')}<code>PCB_CLASSIFIER</code>).</p>}
      <Msg msg={msgs.mode} />

      <div className="tg-box" role="group" aria-labelledby="ai-status-title">
        <h3 id="ai-status-title">{t('ai.statusTitle')}</h3>
        {status.loading && !s && <p className="muted small">{t('ai.checking')}</p>}
        {status.error && <p className="small cfg-error" role="alert">{t('ai.statusError', { error: status.error.message })}</p>}
        {s && (
          <>
            <p className="ai-status" role="status">
              <span className={`ai-dot ${s.reachable ? 'ok' : 'bad'}`} aria-hidden="true" />
              <b>{s.reachable ? t('ai.responds') : t('ai.notResponding')}</b>
              {s.reachable && s.version ? <span className="muted small">{t('ai.version', { version: s.version })}</span> : null}
            </p>
            {!s.reachable && s.error && <p className="small muted">{t('ai.reason', { error: s.error })}</p>}
            <p className="small">
              {t('ai.activeClassifier')}<b>{s.classifier_effective === 'ollama' ? t('ai.classifierOllama') : t('ai.classifierRules')}</b>
            </p>
            {s.models_missing?.length > 0 && (
              <p className="small cfg-locked">{t('ai.missingModels', { models: s.models_missing.join(', ') })}</p>
            )}
            {s.warning && <p className="small cfg-locked">{t('ai.warning', { warning: s.warning })}</p>}
          </>
        )}
        {counts && (
          <p className="muted small">
            {t('ai.counts', { ollama: counts.ollama, rules: counts.rules, untyped: counts.sem_tipo })}
          </p>
        )}
      </div>

      <div className="tg-box" role="group" aria-labelledby="ai-url-title">
        <h3 id="ai-url-title">{t('ai.urlTitle')}</h3>
        <div className="cfg-add-row">
          <label htmlFor="ai-url" className="sr-only">{t('ai.urlLabel')}</label>
          <input id="ai-url" className="search cfg-input" type="url" maxLength={200} value={url} autoComplete="off"
            disabled={lockedOllama} placeholder="http://127.0.0.1:11434" onChange={(e) => setUrl(e.target.value)} />
          <button type="button" className="btn" disabled={!!busy || !url.trim()} onClick={testUrl}
            aria-label={t('ai.testUrlAria')}>{t('ai.testBtn')}</button>
          <button type="button" className="btn btn-primary" disabled={lockedOllama || !!busy || !url.trim()}
            onClick={saveUrl} aria-label={t('ai.saveUrlAria')}>{t('ai.saveBtn')}</button>
        </div>
        {lockedOllama && <p className="small cfg-locked">{t('ai.lockedEnv')}<code>PCB_OLLAMA_URL</code> / <code>PCB_OLLAMA_MODELS</code>).</p>}
        <Msg msg={tested} />
        <Msg msg={msgs.url} />
      </div>

      <div className="tg-box" role="group" aria-labelledby="ai-models-title">
        <h3 id="ai-models-title">{t('ai.modelsTitle', { max })}</h3>
        <p className="muted small">{t('ai.modelsHelp')}</p>
        {models.loading && !models.data && <p className="muted small">{t('ai.loadingModels')}</p>}
        {models.error && <p className="small muted">{t('ai.modelsError', { error: models.error.message })}</p>}
        {models.data && installed.length === 0 && (
          <p className="small">{t('ai.noModelsInstalled')}<code>qwen2.5:3b</code>{t('ai.noModelsInstalledSuffix')}</p>
        )}
        {names.length > 0 && (
          <ul className="ai-models">
            {names.map((n) => {
              const m = sizeOf(n)
              const on = chosen.includes(n)
              return (
                <li key={n}>
                  <label className="cfg-check">
                    <input type="checkbox" checked={on} disabled={lockedOllama || (!on && chosen.length >= max)}
                      onChange={(e) => toggle(n, e.target.checked)} />
                    <span className="ai-model-name">{n}</span>
                    <span className="muted small">
                      {m ? [gb(m.size), m.quantization, m.parameters].filter(Boolean).join(' · ') : t('ai.notInstalled')}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        )}
        <div className="cfg-actions">
          <button type="button" className="btn btn-primary" disabled={lockedOllama || !!busy} onClick={saveModels}
            aria-label={t('ai.saveModelsAria')}>{t('ai.saveModelsBtn')}</button>
        </div>
        <Msg msg={msgs.models} />

        <form className="cfg-add" onSubmit={startPull}>
          <label htmlFor="ai-pull">{t('ai.pullLabel')}</label>
          <div className="cfg-add-row">
            <input id="ai-pull" className="search cfg-input" list="ai-suggested" maxLength={100} value={pullName}
              placeholder={t('ai.pullPlaceholder')} autoComplete="off" disabled={running}
              onChange={(e) => setPullName(e.target.value)} />
            <datalist id="ai-suggested">{SUGGESTED.map((m) => <option key={m} value={m} />)}</datalist>
            <button type="submit" className="btn" disabled={running || !pullName.trim()}>{t('ai.pullBtn')}</button>
          </div>
        </form>
        {pull && pull.state !== 'idle' && (
          <div className="ai-pull" aria-live="polite">
            <p className="small">
              {pull.state === 'running' && <>{t('ai.pullRunning')}<b>{pull.model}</b>… {pull.percent}%</>}
              {pull.state === 'done' && <>{t('ai.pullDonePrefix')}<b>{pull.model}</b>{t('ai.pullDoneSuffix')}</>}
              {pull.state === 'canceled' && <>{t('ai.pullCanceledPrefix')}<b>{pull.model}</b>{t('ai.pullCanceledSuffix')}</>}
              {pull.state === 'error' && <span className="cfg-error" role="alert">{t('ai.pullError', { model: pull.model, error: pull.error })}</span>}
            </p>
            {pull.state === 'running' && (
              <div className="cfg-add-row">
                <div className="ai-bar" role="progressbar" aria-label={t('ai.pullBarAria', { model: pull.model })} aria-valuemin={0}
                  aria-valuemax={100} aria-valuenow={pull.percent}>
                  <span style={{ width: `${pull.percent}%` }} />
                </div>
                <button type="button" className="btn btn-danger" onClick={cancelPull}>{t('ai.cancelBtn')}</button>
              </div>
            )}
          </div>
        )}
        <Msg msg={msgs.pull} />
      </div>

      <form className="tg-box" onSubmit={runTest} aria-labelledby="ai-test-title">
        <h3 id="ai-test-title">{t('ai.testTitle')}</h3>
        <label htmlFor="ai-test" className="muted small">{t('ai.testLabel')}</label>
        <textarea id="ai-test" className="search cfg-input ai-test" rows={3} maxLength={MAX_TEXT} value={text}
          onChange={(e) => setText(e.target.value)} placeholder={t('ai.testPlaceholder')} />
        <div className="cfg-actions">
          <button type="submit" className="btn" disabled={busy === 'test'}>{t('ai.classifyBtn')}</button>
          <span className="muted small">{text.length}/{MAX_TEXT}</span>
        </div>
        <Msg msg={msgs.test} />
        {result && (
          <dl className="sched-status" aria-live="polite">
            <div><dt>{t('ai.resType')}</dt><dd>{kindName(result.kind)}</dd></div>
            <div><dt>{t('ai.resSource')}</dt><dd>{result.source === 'ollama'
              ? (result.agree === 1 ? t('ai.resSourceOllama1') : t('ai.resSourceOllamaN', { n: result.agree }))
              : result.source === 'rules' ? t('ai.resSourceRules') : '—'}</dd></div>
            {result.fallback && <div><dt>{t('ai.resFallbackDt')}</dt><dd>{t('ai.resFallbackDd')}</dd></div>}
            {!result.fallback && result.error && <div><dt>{t('ai.resErrorDt')}</dt><dd className="cfg-error">{result.error}</dd></div>}
            <div><dt>{t('ai.resRulesSay')}</dt><dd>{kindName(result.rules.kind)}: {result.rules.why}</dd></div>
          </dl>
        )}
      </form>
    </section>
  )
}
