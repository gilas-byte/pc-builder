import { api } from '../api.js'
import { CATEGORY_LABEL, money, shortDate, STORE_NAME, when } from '../format.js'
import { go, useLoad } from '../hooks.js'
import { useI18n } from '../i18n/index.jsx'
import Icon from '../components/Icon.jsx'
import { FavButton, PartImage, StoreLink } from '../components/PartCard.jsx'
import { ErrorBox, Loading } from '../components/States.jsx'

const STORE_COLOR = { kabum: '#ffea00', terabyte: '#f5f5f5', amazon: '#ff9f1c', pichau: '#8a8a8a' }

// Histórico completo: uma linha por loja, SVG puro.
export function HistoryChart({ rows }) {
  const { t } = useI18n()
  const W = 640, H = 220, PAD = { l: 64, r: 12, t: 12, b: 28 }
  if (!rows || rows.length < 2) return <p className="muted">{t('detail.shortHistory')}</p>
  const days = [...new Set(rows.map((r) => r.collected_at.slice(0, 10)))].sort()
  const prices = rows.map((r) => r.price_cash)
  const min = Math.min(...prices), max = Math.max(...prices), span = max - min || 1
  const x = (d) => PAD.l + (days.indexOf(d) / Math.max(days.length - 1, 1)) * (W - PAD.l - PAD.r)
  const y = (v) => PAD.t + (1 - (v - min) / span) * (H - PAD.t - PAD.b)
  const byStore = {}
  rows.forEach((r) => { (byStore[r.store] ||= []).push(r) })

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={t('detail.chartAria')}>
        {[min, (min + max) / 2, max].map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} className="grid-line" />
            <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end" className="axis">{money(Math.round(v))}</text>
          </g>
        ))}
        <text x={PAD.l} y={H - 6} className="axis">{shortDate(days[0])}</text>
        <text x={W - PAD.r} y={H - 6} textAnchor="end" className="axis">{shortDate(days.at(-1))}</text>
        {Object.entries(byStore).map(([store, pts]) => (
          <path key={store} fill="none" stroke={STORE_COLOR[store] || '#a3a3a3'} strokeWidth="2"
            d={pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.collected_at.slice(0, 10)).toFixed(1)},${y(p.price_cash).toFixed(1)}`).join(' ')} />
        ))}
      </svg>
      <div className="legend">
        {Object.keys(byStore).map((s) => (
          <span key={s}><i style={{ background: STORE_COLOR[s] || '#a3a3a3' }} />{STORE_NAME[s] || s}</span>
        ))}
      </div>
    </div>
  )
}

export default function PartDetail({ id, onFavorite }) {
  const { t } = useI18n()
  const part = useLoad(() => api.part(id), [id])
  const hist = useLoad(() => api.history(id, 90), [id])

  if (part.loading && !part.data) return <Loading />
  if (part.error) return <ErrorBox error={part.error} onRetry={part.reload} />
  const p = part.data
  const name = `${p.brand} ${p.model}`
  const hot = p.deal?.status === 'deal'
  const specs = Object.entries(p.specs || {})

  return (
    <section className="detail">
      <button type="button" className="link-back" onClick={() => (window.history.length > 1 ? window.history.back() : go('pecas'))}>
        <Icon name="back" size={18} /> {t('detail.back')}
      </button>

      <div className="detail-hero card">
        <PartImage src={p.image_url} category={p.category} alt={name} hot={hot} />
        <div className="detail-info">
          <div className="card-top">
            <span className="chip">{CATEGORY_LABEL[p.category]}</span>
            {hot && <span className="chip chip-hot">-{p.deal.drop_pct}%</span>}
            <FavButton on={p.favorite} label={name}
              onToggle={async () => { await onFavorite(p.id, !p.favorite); part.setData({ ...p, favorite: !p.favorite }) }} />
          </div>
          <p className="brand">{p.brand}</p>
          <h1 className="model big">{p.model}</h1>
          {p.best && <p className={`price big ${hot ? 'hot' : ''}`}>{money(p.best.price_cash)} <span className="muted small">{t('detail.cashAtStore', { store: p.best.store_name })}</span></p>}
          {specs.length > 0 && (
            <dl className="specs">
              {specs.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{Array.isArray(v) ? v.join(', ') : String(v)}</dd></div>)}
            </dl>
          )}
          {p.compat?.compatible === false && <p className="compat bad">{t('detail.inYourPc', { warning: p.compat.warnings[0] })}</p>}
          {p.compat?.compatible === true && p.compat.warnings[0] && <p className="compat unk">{p.compat.warnings[0]}</p>}
        </div>
      </div>

      <h2>{t('detail.priceByStore')}</h2>
      <div className="offers">
        {p.offers.length === 0 && <p className="muted">{t('detail.noStorePrice')}</p>}
        {p.offers.map((o) => (
          <div key={o.listing_id} className={`card offer ${o.deal?.status === 'deal' ? 'is-deal' : ''} ${o.store === 'canal' ? 'is-tg' : ''}`}>
            <div>
              <p className="store">{o.store_name} {o.condition === 'used' && <span className="chip chip-used">{t('card.used')}</span>}</p>
              <p className="muted small">
                {o.title && <span className="offer-title">{o.title}</span>}
                {o.seller && o.seller !== o.store_name && <>{t('detail.soldBy', { seller: o.seller })}</>}
                {o.in_stock ? t('detail.inStock') : t('detail.outOfStock')} · {when(o.collected_at)}
              </p>
            </div>
            <div className="offer-prices">
              <span className={`price ${o.deal?.status === 'deal' ? 'hot' : ''}`}>{money(o.price_cash)}</span>
              {o.price_installment && <span className="muted small">{t('detail.installment', { price: money(o.price_installment) })}</span>}
            </div>
            {o.store === 'canal'
              ? <StoreLink url={o.url} className="btn btn-sm">{t('card.viewInChannel')}</StoreLink>
              : <StoreLink url={o.url} storeName={o.store_name} className="btn btn-sm" />}
          </div>
        ))}
      </div>

      <h2>{t('detail.historyTitle')}</h2>
      <div className="card pad">
        {hist.loading && <Loading />}
        {hist.error && <ErrorBox error={hist.error} onRetry={hist.reload} />}
        {hist.data && <HistoryChart rows={hist.data} />}
      </div>
    </section>
  )
}
