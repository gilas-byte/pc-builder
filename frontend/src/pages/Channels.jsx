import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { money, safeImg, safeUrl, STORE_NAME, when } from '../format.js'
import { useLoad } from '../hooks.js'
import { t as translateCurrent, useI18n } from '../i18n/index.jsx'
import Icon from '../components/Icon.jsx'
import { Empty, ErrorBox, Loading, PageHeader } from '../components/States.jsx'

const KIND_KEYS = [
  'peca:cpu', 'peca:gpu', 'peca:motherboard', 'peca:ram', 'peca:storage', 'peca:psu', 'peca:case', 'peca:cooler',
  'monitor', 'notebook', 'periferico', 'audio', 'console_jogo', 'celular_tablet', 'tv_streaming', 'outro_tech',
  'duvidoso', 'nao_peca', 'nao_tech', 'cupom',
]

// Tipos que a votação devolve (app/tg/vote.py) e o das regras (app/tg/rules.py) → rótulo da tela.
export const KIND_LABEL = new Proxy({}, {
  get: (_, key) => (typeof key === 'string' && KIND_KEYS.includes(key) ? translateCurrent(`kind.${key}`) : undefined),
})

const GROUPS = [
  ['', 'tg.groupAll'],
  ['monitor', 'kind.monitor'],
  ['notebook', 'kind.notebook'],
  ['periferico', 'kind.periferico'],
  ['audio', 'kind.audio'],
  ['console_jogo', 'kind.console_jogo'],
  ['celular_tablet', 'tg.groupPhone'],
  ['tv_streaming', 'kind.tv_streaming'],
  ['outro_tech', 'kind.outro_tech'],
]
const PERIODS = [[1, 'tg.period1d'], [3, 'tg.period3d'], [7, 'tg.period7d'], [30, 'tg.period30d']]

function DealBadge({ o }) {
  const { t } = useI18n()
  if (o.deal === 'menor_ja_visto') return <span className="chip chip-hot">{t('tg.lowestEver')}</span>
  if (o.deal === 'abaixo_7') return <span className="chip chip-hot">{t('tg.belowTypical', { pct: o.pct })}</span>
  if (o.ref && o.pct !== null) {
    const txt = o.pct > 0 ? t('tg.belowTypical', { pct: o.pct }) : o.pct < 0 ? t('tg.aboveTypical', { pct: -o.pct }) : t('tg.atTypical')
    return <span className="chip">{txt}</span>
  }
  if (o.product_key) return <span className="chip" title={t('tg.shortHistoryTitle')}>{t('spark.short')}</span>
  return null
}

export function OfferRow({ o }) {
  const { t } = useI18n()
  const link = safeUrl(o.link)
  return (
    <li className="tg-offer card">
      {safeImg(o.image) && (
        <img className="tg-thumb" src={safeImg(o.image)} alt="" loading="lazy" referrerPolicy="no-referrer" />
      )}
      <div className="tg-main">
        <div className="tg-chips">
          <span className="chip">{KIND_LABEL[o.kind] || o.kind}</span>
          {o.kind_agree === 2 && <span className="chip" title={t('tg.agree2of3Title')}>2/3</span>}
          <DealBadge o={o} />
        </div>
        <p className="tg-title">{o.title}</p>
        <p className="muted small">
          {STORE_NAME[o.store] || o.store || t('tg.unknownStore')} · @{o.channel} · {when(o.posted_at)}
          {o.ref && <>{t('tg.refSummary', { median: money(o.ref.median), min: money(o.ref.min), n: o.ref.n })}</>}
        </p>
      </div>
      <div className="tg-side">
        <b className="price">{money(o.price_cash)}</b>
        {link && (
          <a className="btn" href={link} target="_blank" rel="noopener noreferrer">
            {t('tg.viewInChannel')} <Icon name="ext" size={16} />
          </a>
        )}
      </div>
    </li>
  )
}

export default function Channels() {
  const { t } = useI18n()
  const [group, setGroup] = useState('')
  const [days, setDays] = useState(3)
  const [onlyDeals, setOnlyDeals] = useState(false)
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')

  useEffect(() => {
    const tmr = setTimeout(() => setQ(typed.trim()), 250)
    return () => clearTimeout(tmr)
  }, [typed])

  const meta = useLoad(() => api.tgMeta(), [])
  const kind = group || undefined
  const { data, error, loading, reload } = useLoad(
    () => api.tgOffers({ kind, days, q, only_deals: onlyDeals, no_parts: true }), [kind, days, q, onlyDeals])
  const list = data || []
  const bad = (meta.data?.channels || []).filter((c) => c.fail_count >= 3)

  return (
    <section>
      <PageHeader title={t('tg.title')} subtitle={t('tg.subtitle')} />
      <p className="stores-note muted small">
        {t('tg.reading')}<b>{meta.data ? t('tg.channelsCount', { n: meta.data.channels.filter((c) => c.active).length }) : '…'}</b>{t('tg.every45m')}
        <b>{meta.data ? when(meta.data.last_round) : '…'}</b>
        · <b>{meta.data?.total ?? '…'}</b>{t('tg.savedOffers')}
        · <a href="#/config">{t('tg.manageChannels')}</a>
        {bad.length > 0 && <> · <span className="store-off" title={bad.map((c) => c.last_error).join('\n')}>
          {t('tg.failingChannels', { list: bad.map((c) => c.slug).join(', ') })}</span></>}
      </p>

      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label={t('tg.typeAria')}>
          {GROUPS.map(([key, labelKey]) => (
            <button key={key || 'all'} type="button" role="tab" aria-selected={group === key}
              className={group === key ? 'tab on' : 'tab'} onClick={() => setGroup(key)}>{t(labelKey)}</button>
          ))}
        </div>
        <input className="search" type="search" placeholder={t('tg.searchPlaceholder')} aria-label={t('tg.searchAria')}
          value={typed} onChange={(e) => setTyped(e.target.value)} />
      </div>
      <div className="toolbar tg-filters">
        <div className="tabs" role="tablist" aria-label={t('tg.periodAria')}>
          {PERIODS.map(([d, labelKey]) => (
            <button key={d} type="button" role="tab" aria-selected={days === d}
              className={days === d ? 'tab on' : 'tab'} onClick={() => setDays(d)}>{t(labelKey)}</button>
          ))}
        </div>
        <label className="tg-check">
          <input type="checkbox" checked={onlyDeals} onChange={(e) => setOnlyDeals(e.target.checked)} />
          {t('tg.onlyRealDeals')}
        </label>
      </div>

      {loading && !data && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && list.length === 0 && (
        <Empty title={onlyDeals ? t('tg.emptyDealsTitle') : t('tg.emptyFilterTitle')}>
          {onlyDeals ? t('tg.emptyDealsBody') : t('tg.emptyFilterBody')}
        </Empty>
      )}
      {list.length > 0 && <ul className="tg-list">{list.map((o) => <OfferRow key={o.id} o={o} />)}</ul>}
    </section>
  )
}
