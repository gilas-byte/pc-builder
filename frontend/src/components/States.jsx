import { useI18n } from '../i18n/index.jsx'

// Estados comuns: carregando, erro, vazio.
export function Loading() {
  const { t } = useI18n()
  return <div className="state" role="status"><span className="spinner" aria-hidden="true" />{t('state.loading')}</div>
}

export function ErrorBox({ error, onRetry }) {
  const { t } = useI18n()
  return (
    <div className="state state-error" role="alert">
      <p>{t('state.backendError')}</p>
      <p className="muted small">{error?.message}</p>
      {onRetry && <button type="button" className="btn" onClick={onRetry}>{t('state.retry')}</button>}
    </div>
  )
}

export function Empty({ title, children }) {
  return (
    <div className="state">
      <p className="state-title">{title}</p>
      {children && <p className="muted">{children}</p>}
    </div>
  )
}

export function PageHeader({ title, subtitle, children }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {children && <div className="page-actions">{children}</div>}
    </header>
  )
}
