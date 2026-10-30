import { useCallback, useEffect } from 'react'
import { api } from './api.js'
import { when } from './format.js'
import { useLoad, useRoute } from './hooks.js'
import { I18nProvider, setLanguage, useI18n } from './i18n/index.jsx'
import Icon from './components/Icon.jsx'
import Builds from './pages/Builds.jsx'
import Channels from './pages/Channels.jsx'
import Deals from './pages/Deals.jsx'
import PartDetail from './pages/PartDetail.jsx'
import Parts from './pages/Parts.jsx'
import Settings from './pages/Settings.jsx'

const NAV = [
  ['', 'deals', 'nav.deals'],
  ['canais', 'channels', 'nav.channels'],
  ['pecas', 'parts', 'nav.parts'],
  ['favoritos', 'star', 'nav.favorites'],
  ['builds', 'builds', 'nav.builds'],
  ['config', 'gear', 'nav.settings', 'nav.settingsShort'],    // no celular a barra é estreita: rótulo curto
]

function Shell() {
  const { t } = useI18n()
  const route = useRoute()
  const health = useLoad(() => api.health(), [])
  const [page, arg] = route
  const favorite = useCallback((id, on) => api.favorite(id, on), [])

  useEffect(() => {
    let alive = true
    if (page !== 'config') {
      api.settings()
        .then((res) => { if (alive && res?.values?.language) setLanguage(res.values.language) })
        .catch(() => {})
    }
    return () => { alive = false }
  }, [page])

  let content
  if (page === 'pecas' && arg) content = <PartDetail key={arg} id={arg} onFavorite={favorite} />
  else if (page === 'pecas') content = <Parts onFavorite={favorite} />
  else if (page === 'favoritos') content = <Parts key="fav" favoritesOnly onFavorite={favorite} />
  else if (page === 'builds') content = <Builds tab={arg} />
  else if (page === 'canais') content = <Channels />
  else if (page === 'config') content = <Settings />
  else content = <Deals onFavorite={favorite} />

  const demo = health.data?.demo

  return (
    <div className={`app ${demo ? 'has-demo' : ''}`}>
      {demo && (
        <div className="demo-banner" role="note">
          <b>{t('app.demoTag')}</b> · {t('app.demoText')}
        </div>
      )}

      <nav className="sidebar" aria-label={t('app.navAria')}>
        <a className="logo" href="#/">
          <span className="logo-mark" aria-hidden="true" />
          <span className="logo-text">PC<b>Builder</b></span>
        </a>
        <ul>
          {NAV.map(([path, icon, labelKey, shortKey]) => {
            const label = t(labelKey)
            const short = shortKey ? t(shortKey) : null
            const active = (page || '') === path
            return (
              <li key={path || 'deals'}>
                <a href={`#/${path}`} className={active ? 'nav on' : 'nav'} aria-current={active ? 'page' : undefined}
                  aria-label={short ? label : undefined}>
                  <Icon name={icon} size={22} />
                  {short ? <><span className="nav-long">{label}</span><span className="nav-short" aria-hidden="true">{short}</span></>
                    : <span>{label}</span>}
                </a>
              </li>
            )
          })}
        </ul>
        <p className="sidebar-foot muted small">
          {t('app.lastCollection')}<br /><b>{health.data ? when(health.data.last_collection) : '…'}</b>
        </p>
      </nav>

      <main className="main">{content}</main>

      <footer className="footer muted small">
        {t('app.lastCollection')}: {health.data ? when(health.data.last_collection) : '…'}
        {health.error && ` · ${t('app.backendDown')}`}
      </footer>
    </div>
  )
}

export default function App() {
  return (
    <I18nProvider>
      <Shell />
    </I18nProvider>
  )
}
