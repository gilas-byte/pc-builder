import { api } from '../api.js'
import { money } from '../format.js'
import { useLoad } from '../hooks.js'
import { setLanguage, useI18n } from '../i18n/index.jsx'
import { useEffect } from 'react'

// Quais lojas a coleta lê, quais ficaram de fora (bloqueiam robô; regra: não contornar), quais a pessoa desligou
// nas Configurações e a faixa de preço em uso (quando não é a padrão).
export default function StoresNote() {
  const { t } = useI18n()
  const { data } = useLoad(() => api.stores(), [])
  const cfg = useLoad(() => api.settings(), [])
  useEffect(() => {
    if (cfg.data?.values?.language) setLanguage(cfg.data.values.language)
  }, [cfg.data?.values?.language])
  if (!data) return null
  const known = cfg.data ? cfg.data.options.stores : []
  const on = data.filter((s) => s.active && !s.status_note)
  const off = data.filter((s) => s.status_note)
  const disabled = data.filter((s) => !s.active && !s.status_note && known.includes(s.slug))
  const range = cfg.data?.values.price_range
  const ranged = range && (range.min > 0 || range.max < cfg.data.options.price_max)
  return (
    <p className="stores-note muted small">
      {t('stores.collecting')} <b>{on.map((s) => s.name).join(', ')}</b>
      {off.length > 0 && (
        <> · {t('stores.out')} {off.map((s, i) => (
          <span key={s.slug} title={s.status_note} className="store-off">{s.name}{i < off.length - 1 ? ', ' : ''}</span>
        ))} <span className="hint">{t('stores.botBlock')}</span></>
      )}
      {disabled.length > 0 && <> · {t('stores.disabled')} {disabled.map((s) => s.name).join(', ')}</>}
      {ranged && <> · {t('stores.priceRange')} <b>{t('stores.priceRangeTo', { min: money(range.min * 100), max: money(range.max * 100) })}</b></>}
      {(disabled.length > 0 || ranged) && <> · <a href="#/config">{t('stores.changeInSettings')}</a></>}
    </p>
  )
}
