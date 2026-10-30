import { api } from '../api.js'
import { go, useLoad } from '../hooks.js'
import { useI18n } from '../i18n/index.jsx'
import PartCard from '../components/PartCard.jsx'
import { Empty, ErrorBox, Loading, PageHeader } from '../components/States.jsx'
import StoresNote from '../components/StoresNote.jsx'

export default function Deals({ onFavorite }) {
  const { t } = useI18n()
  const { data, error, loading, reload, setData } = useLoad(() => api.deals(), [])

  const fav = async (id, on) => {
    await onFavorite(id, on)
    setData((list) => list.map((d) => (d.part_id === id ? { ...d, favorite: on } : d)))
  }

  return (
    <section>
      <PageHeader title={t('deals.title')} subtitle={t('deals.subtitle')} />
      <StoresNote />
      {loading && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && data.length === 0 && (
        <Empty title={t('deals.emptyTitle')}>
          {t('deals.emptyBody')}
        </Empty>
      )}
      {data && data.length > 0 && (
        <div className="grid">
          {data.map((d) => (
            <PartCard key={d.listing_id} part={d} onOpen={(id) => go(`pecas/${id}`)} onFavorite={fav} />
          ))}
        </div>
      )}
    </section>
  )
}
