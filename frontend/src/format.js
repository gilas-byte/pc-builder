import { getLanguage, t } from './i18n/index.jsx'

export const CATEGORY_KEYS = ['cpu', 'motherboard', 'ram', 'gpu', 'storage', 'psu', 'case', 'cooler']

export const CATEGORY_LABEL = new Proxy({}, {
  get: (_, key) => (typeof key === 'string' && CATEGORY_KEYS.includes(key) ? t(`cat.${key}`) : undefined),
})

export function getCategories() {
  return CATEGORY_KEYS.map((k) => [k, t(`cat.${k}`)])
}

export const CATEGORIES = CATEGORY_KEYS.map((k) => [k, t(`cat.${k}`)])

/** centavos (int) → "R$ 1.299,90" (pt-BR) ou "R$1,299.90" (en). Moeda continua BRL nos dois idiomas. */
export function money(cents) {
  if (cents === null || cents === undefined) return '—'
  return new Intl.NumberFormat(getLanguage(), { style: 'currency', currency: 'BRL' }).format(cents / 100)
}

/** Número formatado segundo o idioma escolhido via Intl. */
export function num(value, options) {
  return new Intl.NumberFormat(getLanguage(), options).format(value)
}

/** "2026-10-09" → "09/10" (pt-BR) ou "10/09" (en) via Intl. */
export function shortDate(ymd) {
  const [y, m, day] = ymd.split('-').map(Number)
  return new Intl.DateTimeFormat(getLanguage(), { day: '2-digit', month: '2-digit' }).format(new Date(y, m - 1, day))
}

/** "2026-10-09T09:00:00" → "09/10 às 09:00" (pt-BR) ou "10/09 at 09:00" (en). */
export function when(iso) {
  if (!iso) return t('when.never')
  const [d, timePart] = iso.split('T')
  return t('when.at', { date: shortDate(d), time: (timePart || '00:00').slice(0, 5) })
}

/** Só deixa passar link http(s): nada de javascript: vindo do banco. */
export function safeUrl(url) {
  try {
    const u = new URL(url)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null
  } catch {
    return null
  }
}

/** Foto de peça: https de qualquer loja OU a cópia local de foto de canal (/api/tg/img/<nome>). Nada além disso. */
export function safeImg(src) {
  if (typeof src !== 'string' || !src) return null
  if (/^\/api\/tg\/img\/[A-Za-z0-9_]{3,64}_\d{1,12}\.(jpg|png|webp)$/.test(src)) return src
  try {
    const u = new URL(src)
    return u.protocol === 'https:' ? u.href : null
  } catch {
    return null
  }
}

const STATIC_STORES = {
  kabum: 'KaBuM!', pichau: 'Pichau', terabyte: 'Terabyte', amazon: 'Amazon', mercadolivre: 'Mercado Livre', shopee: 'Shopee',
  magalu: 'Magalu', aliexpress: 'AliExpress',
}

export const STORE_NAME = new Proxy(STATIC_STORES, {
  get: (target, key) => (key === 'canal' ? t('store.canal') : target[key]),
})
