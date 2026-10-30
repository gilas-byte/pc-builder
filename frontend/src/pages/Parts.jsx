import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { getCategories } from '../format.js'
import { go, useLoad } from '../hooks.js'
import { useI18n } from '../i18n/index.jsx'
import PartCard from '../components/PartCard.jsx'
import { Empty, ErrorBox, Loading, PageHeader } from '../components/States.jsx'
import StoresNote from '../components/StoresNote.jsx'

export default function Parts({ onFavorite, favoritesOnly = false }) {
  const { t } = useI18n()
  const [category, setCategory] = useState('')
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')

  // espera parar de digitar antes de buscar
  useEffect(() => {
    const tmr = setTimeout(() => setQ(typed.trim()), 250)
    return () => clearTimeout(tmr)
  }, [typed])

  const { data, error, loading, reload, setData } = useLoad(
    () => api.parts({ category, q, favorites: favoritesOnly }), [category, q, favoritesOnly])

  const fav = async (id, on) => {
    await onFavorite(id, on)
    setData((list) => (favoritesOnly && !on ? list.filter((p) => p.id !== id)
      : list.map((p) => (p.id === id ? { ...p, favorite: on } : p))))
  }

  return (
    <section>
      <PageHeader
        title={favoritesOnly ? t('parts.favTitle') : t('parts.title')}
        subtitle={favoritesOnly ? t('parts.favSubtitle') : t('parts.subtitle')}
      />
      {!favoritesOnly && <StoresNote />}

      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label={t('parts.categoriesAria')}>
          <button type="button" role="tab" aria-selected={category === ''} className={category === '' ? 'tab on' : 'tab'}
            onClick={() => setCategory('')}>{t('parts.all')}</button>
          {getCategories().map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={category === key}
              className={category === key ? 'tab on' : 'tab'} onClick={() => setCategory(key)}>{label}</button>
          ))}
        </div>
        <input className="search" type="search" placeholder={t('parts.searchPlaceholder')} aria-label={t('parts.searchAria')}
          value={typed} onChange={(e) => setTyped(e.target.value)} />
      </div>

      {loading && !data && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && data.length === 0 && (
        favoritesOnly
          ? <Empty title={t('parts.favEmptyTitle')}>{t('parts.favEmptyBody')}</Empty>
          : <Empty title={q || category ? t('parts.filterEmptyTitle') : t('parts.emptyTitle')}>
              {q || category ? t('parts.filterEmptyBody') : t('parts.emptyBody')}
            </Empty>
      )}
      {data && data.length > 0 && (
        <div className="grid">
          {data.map((p) => <PartCard key={p.id} part={p} onOpen={(id) => go(`pecas/${id}`)} onFavorite={fav} />)}
        </div>
      )}

    </section>
  )
}
