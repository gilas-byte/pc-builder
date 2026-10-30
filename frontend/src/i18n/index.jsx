import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import ptBR from './pt-BR.js'
import en from './en.js'

const DICTS = { 'pt-BR': ptBR, en }
export const DEFAULT_LANG = 'pt-BR'
const SUPPORTED = ['pt-BR', 'en']

let currentLang = DEFAULT_LANG
const listeners = new Set()

export function normalizeLang(lang) {
  return SUPPORTED.includes(lang) ? lang : DEFAULT_LANG
}

export function getLanguage() {
  return currentLang
}

export function setLanguage(lang) {
  const next = normalizeLang(lang)
  const changed = next !== currentLang
  currentLang = next
  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.lang = next
  }
  if (changed) listeners.forEach((fn) => fn(next))
  return next
}

export function translate(lang, key, params) {
  const dict = DICTS[lang] || DICTS[DEFAULT_LANG]
  const raw = (dict && dict[key] !== undefined ? dict[key] : undefined) ?? DICTS[DEFAULT_LANG]?.[key] ?? key
  if (!params) return raw
  return String(raw).replace(/\{(\w+)\}/g, (_, k) => (params[k] !== undefined && params[k] !== null ? String(params[k]) : `{${k}}`))
}

export function t(key, params) {
  return translate(currentLang, key, params)
}

const I18nContext = createContext(null)

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(currentLang)

  useEffect(() => {
    if (typeof document !== 'undefined' && document.documentElement) {
      document.documentElement.lang = lang
    }
  }, [lang])

  useEffect(() => {
    setLangState(currentLang)
    const onChange = (next) => setLangState(next)
    listeners.add(onChange)
    return () => { listeners.delete(onChange) }
  }, [])

  const value = useMemo(() => ({
    lang,
    setLanguage,
    t: (key, params) => translate(lang, key, params),
  }), [lang])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const ctx = useContext(I18nContext)
  const [lang, setLangState] = useState(currentLang)

  useEffect(() => {
    if (ctx) return undefined
    setLangState(currentLang)
    const onChange = (next) => setLangState(next)
    listeners.add(onChange)
    return () => { listeners.delete(onChange) }
  }, [ctx])

  if (ctx) return ctx
  return {
    lang,
    setLanguage,
    t: (key, params) => translate(lang, key, params),
  }
}
