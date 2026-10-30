import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from '../App.jsx'
import ptBR from '../i18n/pt-BR.js'
import en from '../i18n/en.js'
import { getLanguage, setLanguage, t } from '../i18n/index.jsx'
import { CATEGORY_LABEL, money, num, shortDate, STORE_NAME, when } from '../format.js'

const OPTIONS = {
  languages: ['pt-BR', 'en'], stores: ['kabum', 'terabyte', 'amazon'], notify_targets: ['none', 'telegram', 'stdout'],
  sockets: ['AM4', 'AM5', 'LGA1700'], memory_types: ['DDR4', 'DDR5'], form_factors: ['ATX', 'mATX', 'ITX'],
  collect_every_minutes: { min: 15, max: 1440 }, price_max: 1000000, ram_max: 1024, text_max: 80, max_models: 3,
  min_models: 1, model_max: 100, classifiers: ['auto', 'rules', 'ollama'], max_channels: 50,
}
const VALUES_EN = {
  language: 'en', stores: { kabum: true, terabyte: false, amazon: true }, collect_every_minutes: 1440,
  price_range: { min: 500, max: 5000 }, game_mode: false, notify_target: 'stdout',
  current_pc: { socket: 'AM4', memory_type: 'DDR4', motherboard: 'MSI B450 TOMAHAWK MAX', cpu: 'AMD Ryzen 5 5600',
    gpu: 'NVIDIA GeForce RTX 3060', ram_gb: 16, form_factor: 'ATX' },
  ollama: { url: 'http://127.0.0.1:11434', models: ['qwen2.5:3b'] },
  scheduler_enabled: true, classifier: 'auto',
}
const settingsPayload = (over = {}, metaOver = {}) => ({
  values: { ...VALUES_EN, ...over },
  meta: Object.fromEntries(Object.keys(VALUES_EN).map((k) => [k, { source: 'default', env: [], locked: false, ...(metaOver[k] || {}) }])),
  options: OPTIONS,
})
const HEALTH = { status: 'ok', demo: true, last_collection: '2026-10-09T09:00:00', parts: 2 }
const STORES = [
  { slug: 'kabum', name: 'KaBuM!', active: 1, status_note: null },
  { slug: 'terabyte', name: 'Terabyte', active: 0, status_note: null },
  { slug: 'pichau', name: 'Pichau', active: 1, status_note: 'bloqueia robô (HTTP 403)' },
]
const best = (cents, store = 'kabum', name = 'KaBuM!') => ({
  listing_id: 1, url: `https://www.${store}.com.br/p/1`, store, store_name: name,
  price_cash: cents, price_installment: cents + 10000, in_stock: 1, collected_at: '2026-10-09T09:00:00',
})
const GPU = {
  id: 7, category: 'gpu', brand: 'NVIDIA', model: 'RTX 4060', specs: { recommended_psu_w: 550 },
  image_url: 'https://img.kabum.com.br/gpu.jpg', best: best(189990), favorite: false,
  deal: { status: 'normal' }, spark: [200000, 195000, 189990],
}
const DEAL = {
  listing_id: 9, url: 'https://www.pichau.com.br/p/9', part_id: 7, category: 'gpu', brand: 'NVIDIA', model: 'RTX 4060',
  store: 'pichau', store_name: 'Pichau', in_stock: 1, price_cash: 155000, median_cash: 190000, drop_pct: 18.4,
  status: 'deal', condition: 'used', days_of_history: 29, image_url: null, spark: [190000, 189000, 155000], favorite: false,
}

const json = (v, status = 200) => new Response(v === null ? null : JSON.stringify(v), { status })

function mockApi(routes) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts = {}) => {
    const method = opts.method || 'GET'
    const exact = `${method} ${url}`
    if (exact in routes) {
      const v = typeof routes[exact] === 'function' ? routes[exact](url, opts) : routes[exact]
      return v instanceof Response ? v : json(v, v === null ? 204 : 200)
    }
    const key = Object.keys(routes).find((k) => (k.endsWith('*') ? url.startsWith(k.slice(0, -1)) : url === k))
    if (!key) return json({ detail: 'not mocked' }, 404)
    const v = typeof routes[key] === 'function' ? routes[key](url, opts) : routes[key]
    return v instanceof Response ? v : json(v, v === null ? 204 : 200)
  })
}

const PT_FORBIDDEN = [
  'Promoções', 'Peças', 'Favoritos', 'Configurações', 'Ajustes', 'Última coleta', 'EXEMPLO',
  'Coletando:', 'Desligadas:', 'Faixa de preço:', 'mudar nas Configurações',
  'Placa de vídeo', 'Processador', 'Placa-mãe', 'Memória RAM', 'Armazenamento', 'Fonte', 'Gabinete',
  'à vista', 'mediana 30 dias', 'Ver na ', 'Ver no canal', 'sem estoque', 'usado',
  'Buscar modelo', 'Todas', 'voltar', 'Preço em cada loja', 'Histórico (90 dias)', 'vendido por', 'parcelado',
  'Total da build', 'Montar a mais barata', 'Build completa', 'Upgrades do PC atual', 'Escolher', 'Tirar',
  'menor preço já visto', 'abaixo do típico', 'só promoção de verdade', 'ofertas guardadas', 'gerenciar canais',
  'Canais do Telegram', 'Lojas', 'Coleta', 'Meu PC', 'Modo jogo', 'Notificação', 'IA local', 'Idioma',
  'Restaurar padrão', 'Bot do Telegram', 'Encontrar meu chat', 'Agendador interno', 'Rodar agora',
  'Automático', 'Só regras', 'Só Ollama', 'Teste rápido', 'Classificar',
]

function expectNoPtText(container) {
  const text = container.textContent
  for (const pt of PT_FORBIDDEN) {
    expect(text).not.toContain(pt)
  }
}

describe('i18n: dicionários, fallback, params e <html lang>', () => {
  it('pt-BR e en têm exatamente as mesmas chaves e nenhuma vazia', () => {
    const ptKeys = Object.keys(ptBR).sort()
    const enKeys = Object.keys(en).sort()
    expect(enKeys).toEqual(ptKeys)
    expect(ptKeys.length).toBeGreaterThan(50)
    for (const k of ptKeys) {
      expect(typeof ptBR[k]).toBe('string')
      expect(ptBR[k].length).toBeGreaterThan(0)
      expect(typeof en[k]).toBe('string')
      expect(en[k].length).toBeGreaterThan(0)
    }
  })

  it('troca de idioma atualiza t(), getLanguage() e <html lang>', () => {
    setLanguage('pt-BR')
    expect(getLanguage()).toBe('pt-BR')
    expect(document.documentElement.lang).toBe('pt-BR')
    expect(t('nav.deals')).toBe('Promoções')

    setLanguage('en')
    expect(getLanguage()).toBe('en')
    expect(document.documentElement.lang).toBe('en')
    expect(t('nav.deals')).toBe('Deals')
  })

  it('interpola parâmetros {chave} nos dois idiomas', () => {
    setLanguage('pt-BR')
    expect(t('builds.partsCount', { chosen: 3, total: 8 })).toBe('3 de 8 peças')
    setLanguage('en')
    expect(t('builds.partsCount', { chosen: 3, total: 8 })).toBe('3 of 8 parts')
  })

  it('faz fallback para pt-BR quando falta uma chave no idioma ativo', () => {
    const saved = en['nav.deals']
    delete en['nav.deals']
    try {
      setLanguage('en')
      expect(t('nav.deals')).toBe('Promoções')
    } finally {
      en['nav.deals'] = saved
    }
    expect(t('chave.que.nao.existe')).toBe('chave.que.nao.existe')
  })

  it('formata moeda (BRL), datas e números segundo o idioma via Intl', () => {
    setLanguage('pt-BR')
    expect(money(129990).replace(/\s/g, ' ')).toBe('R$ 1.299,90')
    expect(when('2026-10-09T09:05:00')).toBe('09/10 às 09:05')
    expect(when(null)).toBe('nunca')
    expect(shortDate('2026-10-09')).toBe('09/10')
    expect(num(87.3, { maximumFractionDigits: 1 })).toBe('87,3')
    expect(CATEGORY_LABEL.gpu).toBe('Placa de vídeo')
    expect(STORE_NAME.canal).toBe('Canais do Telegram')

    setLanguage('en')
    expect(money(129990).replace(/\s/g, ' ')).toBe('R$1,299.90')
    expect(when('2026-10-09T09:05:00')).toBe('10/09 at 09:05')
    expect(when(null)).toBe('never')
    expect(shortDate('2026-10-09')).toBe('10/09')
    expect(num(87.3, { maximumFractionDigits: 1 })).toBe('87.3')
    expect(CATEGORY_LABEL.gpu).toBe('GPU')
    expect(STORE_NAME.canal).toBe('Telegram channels')
  })
})

describe('páginas principais em inglês (en) sem sobrar texto em português', () => {
  it('Promoções (Deals) + moldura principal + StoresNote + PartCard em en', async () => {
    mockApi({
      '/api/health': HEALTH,
      '/api/settings': settingsPayload(),
      '/api/stores': STORES,
      '/api/deals': [DEAL],
    })
    const { container } = render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Deals' })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('en')
    expect(screen.getByRole('note')).toHaveTextContent('DEMO')
    expect(screen.getByText(/Checking:/)).toBeInTheDocument()
    expect(screen.getByText(/Disabled: Terabyte/)).toBeInTheDocument()
    expect(screen.getByText(/R\$1,550\.00/)).toBeInTheDocument()
    expect(screen.getByText(/30-day median:/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View at Pichau/ })).toBeInTheDocument()
    expect(screen.getAllByText(/10\/09 at 09:00/).length).toBeGreaterThan(0)
    expectNoPtText(container)
  })

  it('Canais (Channels) em en', async () => {
    window.location.hash = '#/canais'
    mockApi({
      '/api/health': HEALTH,
      '/api/settings': settingsPayload(),
      '/api/tg/meta': {
        kinds: [{ value: 'monitor', n: 1 }], stores: [], total: 5, last_round: '2026-10-12T18:00:00',
        channels: [{ slug: 'gpcrpromo', active: 1, fail_count: 0 }, { slug: 'lipeofertas', active: 1, fail_count: 3, last_error: 'down' }],
      },
      '/api/tg/offers*': [{
        id: 1, channel: 'gpcrpromo', msg_id: 10, posted_at: '2026-10-12T17:00:00', title: 'LG UltraGear 27"',
        price_cash: 119900, store: 'kabum', link: 'https://t.me/gpcrpromo/10', kind: 'monitor', kind_agree: 2,
        product_key: 'monitor|lg 27', ref: { n: 4, min: 125000, median: 139900 }, deal: 'menor_ja_visto', pct: 14,
      }],
    })
    const { container } = render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Channels' })).toBeInTheDocument()
    expect(await screen.findByText('lowest price seen')).toBeInTheDocument()
    expect(screen.getByText(/failing: lipeofertas/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /view in channel/i })).toBeInTheDocument()
    expect(screen.getByText(/real deals only/)).toBeInTheDocument()
    expectNoPtText(container)
  })

  it('Peças (Parts) e Favoritos (Favorites) em en', async () => {
    window.location.hash = '#/pecas'
    mockApi({
      '/api/health': HEALTH,
      '/api/settings': settingsPayload(),
      '/api/stores': STORES,
      '/api/parts*': [GPU],
    })
    const { container, unmount } = render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Parts' })).toBeInTheDocument()
    expect(await screen.findByText('RTX 4060')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'CPU' })).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: 'Search model' })).toBeInTheDocument()
    expectNoPtText(container)
    unmount()

    window.location.hash = '#/favoritos'
    mockApi({
      '/api/health': HEALTH,
      '/api/settings': settingsPayload(),
      '/api/parts*': [],
    })
    const favView = render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Favorites' })).toBeInTheDocument()
    expect(await screen.findByText('No favorites yet.')).toBeInTheDocument()
    expectNoPtText(favView.container)
  })

  it('Detalhe da peça (PartDetail) em en', async () => {
    window.location.hash = '#/pecas/7'
    const offers = [{ ...best(189990), seller: 'ASUS', condition: 'used', deal: { status: 'normal' } }]
    const hist = [
      { store: 'kabum', price_cash: 195000, collected_at: '2026-10-08T09:00:00' },
      { store: 'kabum', price_cash: 189990, collected_at: '2026-10-09T09:00:00' },
    ]
    mockApi({
      '/api/health': HEALTH,
      '/api/settings': settingsPayload(),
      '/api/parts/7': { ...GPU, offers, compat: { compatible: true, warnings: [] } },
      '/api/parts/7/history?days=90': hist,
    })
    const { container } = render(<App />)
    expect(await screen.findByRole('heading', { name: 'Price by store' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'History (90 days)' })).toBeInTheDocument()
    expect(screen.getByText(/sold by ASUS/)).toBeInTheDocument()
    expect(screen.getByText(/in stock/)).toBeInTheDocument()
    expect(screen.getByText(/installments/)).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: 'price history by store' })).toBeInTheDocument()
    expect(screen.getByText('10/08')).toBeInTheDocument()
    expectNoPtText(container)
  })

  it('Builds (completa e upgrades) em en', async () => {
    window.location.hash = '#/builds/completa'
    const full = {
      id: 1, name: 'Build completa', kind: 'full', build_id: 1, total_cash: 189990, missing: ['cpu'], unavailable: [],
      items: [
        { category: 'cpu', part_id: null, brand: null, model: null, best: null, image_url: null },
        { category: 'gpu', part_id: 7, brand: 'NVIDIA', model: 'RTX 4060', best: best(189990), image_url: null, compat: { compatible: true, warnings: [] } },
      ],
    }
    const upg = {
      id: 2, name: 'Upgrades do PC atual', kind: 'upgrade', build_id: 2, total_cash: 0, missing: ['gpu'], unavailable: [],
      items: [{ category: 'gpu', part_id: null, brand: null, model: null, best: null, image_url: null }],
    }
    mockApi({
      '/api/health': HEALTH,
      '/api/settings': settingsPayload(),
      '/api/current-pc': VALUES_EN.current_pc,
      '/api/builds': [full, upg],
      '/api/builds/1/options/gpu': [{ ...GPU, compat: { compatible: true, warnings: [] } }],
    })
    const { container } = render(<App />)
    expect(await screen.findByText('Build total')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Build cheapest' })).toBeInTheDocument()
    expect(screen.getByText(/1 of 2 parts · missing: CPU/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Swap' }))
    expect(await screen.findByRole('dialog', { name: 'Swap GPU' })).toBeInTheDocument()
    expectNoPtText(container)
  })

  it('Configurações (Settings + Telegram + Scheduler + Ollama) em en e troca ao vivo sem recarregar', async () => {
    window.location.hash = '#/config'
    let currentSettings = settingsPayload({ language: 'pt-BR' })
    mockApi({
      '/api/health': HEALTH,
      '/api/settings': () => currentSettings,
      'PUT /api/settings': (u, o) => {
        const body = JSON.parse(o.body)
        currentSettings = settingsPayload(body, { language: { source: 'banco' } })
        return currentSettings
      },
      '/api/channels': [{ slug: 'gpcrpromo', title: 'GPCR', enabled: true, source: 'padrao', posts: 4, last_ok_at: '2026-10-12T10:00:00', fail_count: 0, last_error: null }],
      '/api/secrets/telegram': { configured: true, source: 'file', hint: '…6789', ready: true, file_error: null, chat_id: { configured: true, source: 'file', hint: '…3456' } },
      '/api/scheduler': { enabled: true, running: false, interval_minutes: 1440, last_run_at: '2026-10-19T08:00:00', last_ok: true, last_error: null, next_run_at: '2026-10-19T08:15:00', skipped: 'jogo', game_mode: true, game_mode_available: false },
      '/api/ollama/status': { reachable: true, url: 'http://127.0.0.1:11434', version: '0.12.3', error: null, warning: null, classifier_mode: 'auto', classifier_effective: 'ollama', models_selected: ['qwen2.5:3b'], models_missing: [] },
      '/api/classifier': { mode: 'auto', effective: 'ollama', rules_metrics: { pct: 99.7, n: 295, ok: 294 }, counts: { ollama: 10, rules: 4, sem_tipo: 1 } },
      '/api/ollama/models': { models: [{ name: 'qwen2.5:3b', size: 1_929_000_000, quantization: 'Q4_K_M', parameters: '3.1B' }] },
      '/api/ollama/pull': { model: null, state: 'idle', percent: 0, completed: 0, total: 0, error: null },
    })

    const { container } = render(<App />)
    const langSection = await screen.findByRole('region', { name: 'Idioma' })
    expect(document.documentElement.lang).toBe('pt-BR')

    // Troca para inglês e salva: tudo muda na hora sem recarregar a página
    fireEvent.change(within(langSection).getByLabelText('Idioma'), { target: { value: 'en' } })
    await act(async () => {
      fireEvent.click(within(langSection).getByRole('button', { name: 'Salvar Idioma' }))
    })

    expect(await screen.findByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument()
    expect(document.documentElement.lang).toBe('en')
    const enLangSection = screen.getByRole('region', { name: 'Language' })
    expect(within(enLangSection).getByRole('status')).toHaveTextContent('Saved.')
    for (const s of ['Telegram channels', 'Stores', 'Collection', 'My PC', 'Price range', 'Game mode', 'Notifications', 'Local AI (Ollama)', 'Language']) {
      expect(screen.getByRole('region', { name: s })).toBeInTheDocument()
    }
    expect(screen.getByText('99.7%')).toBeInTheDocument()
    expect(screen.getByText('Ollama reachable')).toBeInTheDocument()
    expect(screen.getByText(/10\/19 at 08:00 · ok/)).toBeInTheDocument()
    expectNoPtText(container)
  })
})
