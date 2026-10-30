// Chamadas à API do backend (mesma origem: o FastAPI serve este frontend).
import { t } from './i18n/index.jsx'

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
    ...options,
  })
  if (!res.ok) {
    let detail = t('api.httpError', { status: res.status })
    let fields = null
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (body?.detail?.fields) {                   // 422 das configurações: mensagem por campo
        fields = body.detail.fields
        detail = body.detail.message || detail
      }
    } catch { /* corpo vazio */ }
    const err = new Error(detail)
    err.status = res.status
    err.fields = fields
    throw err
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  health: () => request('/api/health'),
  stores: () => request('/api/stores'),
  deals: () => request('/api/deals'),
  parts: (params = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== false))
    return request(`/api/parts${qs.size ? `?${qs}` : ''}`)
  },
  part: (id) => request(`/api/parts/${id}`),
  history: (id, days = 90) => request(`/api/parts/${id}/history?days=${days}`),
  builds: () => request('/api/builds'),
  buildOptions: (buildId, category) => request(`/api/builds/${buildId}/options/${category}`),
  setBuildItem: (buildId, category, partId) =>
    request(`/api/builds/${buildId}/items/${category}`, { method: 'PUT', body: JSON.stringify({ part_id: partId }) }),
  autoBuild: (buildId) => request(`/api/builds/${buildId}/auto`, { method: 'POST' }),
  currentPc: () => request('/api/current-pc'),
  favorite: (id, on) => request(`/api/favorites/${id}`, { method: on ? 'PUT' : 'DELETE' }),
  tgMeta: () => request('/api/tg/meta'),
  settings: () => request('/api/settings'),
  saveSettings: (patch) => request('/api/settings', { method: 'PUT', body: JSON.stringify(patch) }),
  resetSetting: (key) => request(`/api/settings/reset/${encodeURIComponent(key)}`, { method: 'POST' }),
  channels: () => request('/api/channels'),
  addChannel: (handle) => request('/api/channels', { method: 'POST', body: JSON.stringify({ handle }) }),
  setChannel: (slug, enabled) =>
    request(`/api/channels/${encodeURIComponent(slug)}`, { method: 'PUT', body: JSON.stringify({ enabled }) }),
  removeChannel: (slug) => request(`/api/channels/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
  // o token só vai (PUT); a API devolve só "configurado" e os 4 últimos caracteres
  telegram: () => request('/api/secrets/telegram'),
  saveTelegram: (body) => request('/api/secrets/telegram', { method: 'PUT', body: JSON.stringify(body) }),
  removeTelegram: () => request('/api/secrets/telegram', { method: 'DELETE' }),
  detectChat: () => request('/api/secrets/telegram/detect-chat', { method: 'POST' }),
  notifyTest: (target) => request('/api/notify/test', { method: 'POST', body: JSON.stringify({ target }) }),
  scheduler: () => request('/api/scheduler'),
  runNow: () => request('/api/scheduler/run-now', { method: 'POST' }),
  // IA local (Ollama) e classificador por regras
  ollamaStatus: (url) => request(`/api/ollama/status${url ? `?${new URLSearchParams({ url })}` : ''}`),
  ollamaModels: () => request('/api/ollama/models'),
  pullStatus: () => request('/api/ollama/pull'),
  pull: (model) => request('/api/ollama/pull', { method: 'POST', body: JSON.stringify({ model }) }),
  cancelPull: () => request('/api/ollama/pull', { method: 'DELETE' }),
  classifier: () => request('/api/classifier'),
  classifyTest: (text) => request('/api/classifier/test', { method: 'POST', body: JSON.stringify({ text }) }),
  tgOffers: (params = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== false))
    return request(`/api/tg/offers${qs.size ? `?${qs}` : ''}`)
  },
}
