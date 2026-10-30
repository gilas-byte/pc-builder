import { useState } from 'react'
import Icon from './Icon.jsx'
import Sparkline from './Sparkline.jsx'
import { CATEGORY_LABEL, money, safeImg, safeUrl } from '../format.js'
import { useI18n } from '../i18n/index.jsx'

// Imagem com halo de luz. Sem foto (ou foto quebrada) → ícone da categoria, mesma luz.
export function PartImage({ src, category, alt, hot = false }) {
  const [broken, setBroken] = useState(false)
  const url = src && !broken ? safeImg(src) : null
  return (
    <div className={`glow-frame ${hot ? 'hot' : ''}`}>
      <div className="glow-halo" aria-hidden="true" />
      {url ? (
        <img src={url} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
      ) : (
        <Icon name={category} size={72} className="glow-icon" />
      )}
    </div>
  )
}

export function FavButton({ on, onToggle, label }) {
  const { t } = useI18n()
  return (
    <button
      type="button"
      className={`fav ${on ? 'on' : ''}`}
      aria-pressed={on}
      aria-label={on ? t('fav.removeAria', { name: label }) : t('fav.addAria', { name: label })}
      title={on ? t('fav.removeTitle') : t('fav.addTitle')}
      onClick={(e) => { e.stopPropagation(); e.preventDefault(); onToggle() }}
    >
      <Icon name="star" size={20} filled={on} />
    </button>
  )
}

export function StoreLink({ url, storeName, children, className = 'btn' }) {
  const { t } = useI18n()
  const href = safeUrl(url)
  if (!href) return null
  return (
    <a className={className} href={href} target="_blank" rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}>
      {children || <>{t('card.viewAtStore', { store: storeName })}</>} <Icon name="ext" size={14} />
    </a>
  )
}

/**
 * Cartão grande de peça.
 * part: { id, category, brand, model, image_url, spark, favorite, best?, deal? }
 * Promoções vêm "achatadas" (price_cash, store_name, url, drop_pct, median_cash) — normalizado aqui.
 */
export default function PartCard({ part, onOpen, onFavorite, compat }) {
  const { t } = useI18n()
  const best = part.best || (part.price_cash ? {
    price_cash: part.price_cash, store_name: part.store_name, url: part.url, in_stock: part.in_stock,
    condition: part.condition, seller: part.seller,
  } : null)
  const deal = part.deal || (part.drop_pct !== undefined ? part : null)
  const hot = deal?.status === 'deal'
  const name = `${part.brand} ${part.model}`
  // azul = o preço que está valendo veio dos canais do Telegram (peça só do canal, ou canal mais barato que as lojas)
  const fromTg = part.source === 'canal' || best?.store === 'canal'
  const where = best?.store === 'canal' ? best.seller : best?.store_name

  return (
    <article className={`card part-card ${hot ? 'is-deal' : ''} ${!best && part.out_of_stock ? 'is-out' : ''} ${fromTg ? 'is-tg' : ''}`}
      title={fromTg ? t('card.fromTgTitle') : undefined}>
      <button type="button" className="card-hit" onClick={() => onOpen?.(part.id ?? part.part_id)}
        aria-label={t('card.openAria', { name })} />
      <div className="card-top">
        <span className="chip">{CATEGORY_LABEL[part.category]}</span>
        {hot && <span className="chip chip-hot">-{deal.drop_pct}%</span>}
        {best?.condition === 'used' && <span className="chip chip-used">{t('card.used')}</span>}
        <FavButton on={!!part.favorite} label={name} onToggle={() => onFavorite?.(part.id ?? part.part_id, !part.favorite)} />
      </div>

      <PartImage src={part.image_url} category={part.category} alt={name} hot={hot} />

      <div className="card-body">
        <p className="brand">{part.brand}</p>
        <h3 className="model">{part.model}</h3>

        {best ? (
          <>
            <div className="price-row">
              <span className={`price ${hot ? 'hot' : ''}`}>{money(best.price_cash)}</span>
              <span className="muted small">{t('card.cashAt', { where })}</span>
            </div>
            {hot && deal.median_cash && (
              <p className="muted small">{t('card.median30d')} <s>{money(deal.median_cash)}</s></p>
            )}
            {deal?.status === 'short_history' && <p className="muted small">{t('card.shortHistoryDeal')}</p>}
          </>
        ) : part.out_of_stock ? (
          <div className="price-row out">
            <span className="price">{money(part.out_of_stock.price_cash)}</span>
            <span className="chip chip-out">{t('card.outOfStock')}</span>
            <span className="muted small">{part.out_of_stock.store_name}</span>
          </div>
        ) : (
          <p className="muted">{t('card.noPrice')}</p>
        )}

        {compat && compat.compatible !== true && (
          <p className={`compat ${compat.compatible === false ? 'bad' : 'unk'}`}>
            {compat.compatible === false ? t('card.compatBad') : t('card.compatWarn')}{compat.warnings[0]}
          </p>
        )}

        <div className="card-foot">
          <Sparkline values={part.spark || []} highlight={hot} />
          {best && (best.store === 'canal'
            ? <StoreLink url={best.url} className="btn btn-sm">{t('card.viewInChannel')}</StoreLink>
            : <StoreLink url={best.url} storeName={best.store_name} className="btn btn-sm" />)}
        </div>
      </div>
    </article>
  )
}
