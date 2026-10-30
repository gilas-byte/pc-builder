import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { CATEGORY_LABEL, money } from '../format.js'
import { useLoad } from '../hooks.js'
import { useI18n } from '../i18n/index.jsx'
import Icon from '../components/Icon.jsx'
import { PartImage, StoreLink } from '../components/PartCard.jsx'
import { Empty, ErrorBox, Loading, PageHeader } from '../components/States.jsx'

function CompatNote({ compat }) {
  if (!compat || (compat.compatible === true && !compat.warnings.length)) return null
  const cls = compat.compatible === false ? 'bad' : compat.compatible === null ? 'unk' : 'info'
  return <p className={`compat ${cls}`}>{compat.warnings.join(' ')}</p>
}

// Lista de opções pra trocar a peça de uma categoria.
function Picker({ buildId, category, currentId, onPick, onClose }) {
  const { t } = useI18n()
  const { data, error, loading, reload } = useLoad(() => api.buildOptions(buildId, category), [buildId, category])
  const ref = useRef(null)
  useEffect(() => { ref.current?.focus() }, [])
  useEffect(() => {
    const esc = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const catLabel = CATEGORY_LABEL[category]
  const title = t('builds.swapCategory', { category: catLabel })

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal card" role="dialog" aria-modal="true" aria-label={title}
        onClick={(e) => e.stopPropagation()} tabIndex={-1} ref={ref}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="btn btn-ghost" onClick={onClose} aria-label={t('builds.closeAria')}>✕</button>
        </div>
        {loading && <Loading />}
        {error && <ErrorBox error={error} onRetry={reload} />}
        {data && data.length === 0 && <Empty title={t('builds.noOptions')} />}
        {data && (
          <ul className="options">
            {data.map((o) => {
              const bad = o.compat?.compatible === false
              return (
                <li key={o.id}>
                  <button type="button" className={`option ${o.id === currentId ? 'on' : ''} ${bad ? 'bad' : ''} ${o.best?.store === 'canal' ? 'is-tg' : ''}`}
                    onClick={() => onPick(o.id)}>
                    <span className="option-name"><b>{o.brand}</b> {o.model}</span>
                    <span className="price">{money(o.best.price_cash)}{o.best.store === 'canal' && <span className="muted small">{t('builds.fromChannel')}</span>}</span>
                    {o.compat && o.compat.compatible !== true && (
                      <span className={`compat ${bad ? 'bad' : 'unk'}`}>{o.compat.warnings[0]}</span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}

function BuildView({ build, onChange, currentPc }) {
  const { t } = useI18n()
  const [picking, setPicking] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const isFull = build.kind === 'full'

  const run = async (fn) => {
    setBusy(true); setErr(null)
    try { await fn(); await onChange() } catch (e) { setErr(e) } finally { setBusy(false) }
  }

  const chosen = build.items.filter((i) => i.part_id)
  const bad = build.items.filter((i) => i.compat?.compatible === false)

  return (
    <div>
      <div className="total card">
        <div>
          <p className="muted small">{isFull ? t('builds.totalFull') : t('builds.totalUpgrade')}</p>
          <p className="price huge">{money(build.total_cash)}</p>
          <p className="muted small">
            {t('builds.partsCount', { chosen: chosen.length, total: build.items.length })}
            {build.missing.length > 0 && t('builds.missing', { list: build.missing.map((c) => CATEGORY_LABEL[c]).join(', ') })}
            {build.unavailable.length > 0 && t('builds.unavailable', { list: build.unavailable.map((c) => CATEGORY_LABEL[c]).join(', ') })}
          </p>
          {bad.length > 0 && <p className="compat bad">{t('builds.incompatibleCount', { count: bad.length })}</p>}
        </div>
        {isFull && (
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => run(() => api.autoBuild(build.id))}>
            <Icon name="wand" size={18} /> {busy ? t('builds.building') : t('builds.buildCheapest')}
          </button>
        )}
      </div>

      {!isFull && currentPc && (
        <p className="muted small current-pc">
          {t('builds.yourPc', {
            cpu: currentPc.cpu,
            motherboard: currentPc.motherboard,
            gpu: currentPc.gpu,
            ram: currentPc.ram_gb,
            memory: currentPc.memory_type,
          })}
        </p>
      )}
      {err && <ErrorBox error={err} />}

      <div className="slots">
        {build.items.map((it) => {
          const name = it.part_id ? `${it.brand} ${it.model}` : null
          return (
            <div key={it.category} className={`card slot ${it.compat?.compatible === false ? 'is-bad' : ''} ${it.best?.store === 'canal' ? 'is-tg' : ''}`}>
              <PartImage src={it.image_url} category={it.category} alt={name || CATEGORY_LABEL[it.category]} />
              <div className="slot-info">
                <p className="chip">{CATEGORY_LABEL[it.category]}</p>
                {name ? (
                  <>
                    <h3 className="model">{name}</h3>
                    <p className="price">{it.best ? money(it.best.price_cash) : <span className="muted">{t('builds.noStockPrice')}</span>}
                      {it.best?.store === 'canal' && <span className="muted small"> · {it.best.seller}</span>}</p>
                    <CompatNote compat={it.compat} />
                  </>
                ) : (
                  <p className="muted">{isFull ? t('builds.nothingChosen') : t('builds.noUpgradeHere')}</p>
                )}
              </div>
              <div className="slot-actions">
                <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setPicking(it.category)}>
                  {name ? t('builds.swap') : t('builds.choose')}
                </button>
                {name && (
                  <button type="button" className="btn btn-sm btn-ghost" disabled={busy}
                    onClick={() => run(() => api.setBuildItem(build.id, it.category, null))}>{t('builds.remove')}</button>
                )}
                {it.best && (it.best.store === 'canal'
                  ? <StoreLink url={it.best.url} className="btn btn-sm btn-ghost">{t('card.viewInChannel')}</StoreLink>
                  : <StoreLink url={it.best.url} storeName={it.best.store_name} className="btn btn-sm btn-ghost" />)}
              </div>
            </div>
          )
        })}
      </div>

      {picking && (
        <Picker buildId={build.id} category={picking}
          currentId={build.items.find((i) => i.category === picking)?.part_id}
          onClose={() => setPicking(null)}
          onPick={(pid) => { setPicking(null); run(() => api.setBuildItem(build.id, picking, pid)) }} />
      )}
    </div>
  )
}

export default function Builds({ tab = 'completa' }) {
  const { t } = useI18n()
  const { data, error, loading, reload } = useLoad(() => api.builds(), [])
  const pc = useLoad(() => api.currentPc(), [])
  const autoTried = useRef(false)
  const kind = tab === 'upgrades' ? 'upgrade' : 'full'
  const build = data?.find((b) => b.kind === kind)

  // Decisão do projeto: a build completa já nasce montada (a mais barata compatível); o usuário troca o que quiser.
  useEffect(() => {
    const full = data?.find((b) => b.kind === 'full')
    if (full && !autoTried.current && full.items.every((i) => !i.part_id)) {
      autoTried.current = true
      api.autoBuild(full.id).then(reload).catch(() => {})
    }
  }, [data, reload])

  return (
    <section>
      <PageHeader title={t('builds.title')} subtitle={t('builds.subtitle')} />
      <div className="tabs" role="tablist" aria-label={t('builds.typeAria')}>
        <a role="tab" aria-selected={kind === 'full'} className={kind === 'full' ? 'tab on' : 'tab'} href="#/builds/completa">{t('builds.tabFull')}</a>
        <a role="tab" aria-selected={kind === 'upgrade'} className={kind === 'upgrade' ? 'tab on' : 'tab'} href="#/builds/upgrades">{t('builds.tabUpgrades')}</a>
      </div>
      {loading && !data && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {build && <BuildView key={build.id} build={build} onChange={reload} currentPc={pc.data} />}
    </section>
  )
}
