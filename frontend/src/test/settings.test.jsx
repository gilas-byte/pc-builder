import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from '../App.jsx'
import { normalizeHandle } from '../pages/Settings.jsx'

const OPTIONS = {
  languages: ['pt-BR', 'en'], stores: ['kabum', 'terabyte', 'amazon'], notify_targets: ['none', 'telegram', 'stdout'],
  sockets: ['AM4', 'AM5', 'LGA1700'], memory_types: ['DDR4', 'DDR5'], form_factors: ['ATX', 'mATX', 'ITX'],
  collect_every_minutes: { min: 15, max: 1440 }, price_max: 1000000, ram_max: 1024, text_max: 80, max_models: 3,
  min_models: 1, model_max: 100, classifiers: ['auto', 'rules', 'ollama'], max_channels: 50,
}
const VALUES = {
  language: 'pt-BR', stores: { kabum: true, terabyte: true, amazon: true }, collect_every_minutes: 1440,
  price_range: { min: 0, max: 1000000 }, game_mode: false, notify_target: 'stdout',
  current_pc: { socket: 'AM4', memory_type: 'DDR4', motherboard: 'MSI B450 TOMAHAWK MAX', cpu: 'AMD Ryzen 5 5600',
    gpu: 'NVIDIA GeForce RTX 3060', ram_gb: 16, form_factor: 'ATX' },
  ollama: { url: 'http://127.0.0.1:11434', models: ['qwen2.5:3b', 'llama3.2:3b', 'gemma3:4b'] },
  scheduler_enabled: false, classifier: 'auto',
}
const TG_EMPTY = { configured: false, source: null, hint: null, ready: false, file_error: null,
  chat_id: { configured: false, source: null, hint: null } }
const SCHED = { enabled: false, running: false, interval_minutes: 1440, last_run_at: null, last_ok: null,
  last_error: null, next_run_at: null, skipped: null, game_mode: false, game_mode_available: true }
const meta = (over = {}) => Object.fromEntries(Object.keys(VALUES).map((k) => [k,
  { source: 'default', env: [], locked: false, ...(over[k] || {}) }]))
const settings = (values = {}, metaOver = {}) => ({ values: { ...VALUES, ...values }, meta: meta(metaOver), options: OPTIONS })
const CHANNELS = [
  { slug: 'gpcrpromo', title: 'GPCR Promo', enabled: true, source: 'padrao', posts: 12, last_ok_at: '2026-10-12T10:00:00',
    fail_count: 0, last_error: null },
  { slug: 'lipeofertas', title: null, enabled: false, source: 'padrao', posts: 0, last_ok_at: null, fail_count: 3,
    last_error: 'fora do ar' },
]

const json = (v, status = 200) => new Response(v === null ? null : JSON.stringify(v), { status })

/** fetch falso que guarda método e corpo. routes['MÉTODO url'] ou routes[url] (GET). */
function mockApi(routes) {
  const calls = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts = {}) => {
    const method = opts.method || 'GET'
    calls.push({ url, method, body: opts.body ? JSON.parse(opts.body) : undefined, headers: opts.headers })
    const key = `${method} ${url}`
    const v = key in routes ? routes[key] : method === 'GET' ? routes[url] : undefined
    if (v === undefined) return json({ detail: 'rota não mockada' }, 404)
    const r = typeof v === 'function' ? v(url, opts) : v
    return r instanceof Response ? r : json(r, r === null ? 204 : 200)
  })
  return calls
}
const base = (extra = {}) => ({
  '/api/health': { status: 'ok', demo: false, last_collection: null }, '/api/settings': settings(),
  '/api/channels': CHANNELS, '/api/secrets/telegram': TG_EMPTY, '/api/scheduler': SCHED, ...extra,
})
const open = () => { window.location.hash = '#/config' }
const section = (name) => screen.getByRole('region', { name })

describe('handle do canal (mesmas regras do servidor)', () => {
  it('aceita @nome, nome e links t.me', () => {
    for (const t of ['gpcrpromo', '@gpcrpromo', ' @gpcrpromo ', 'https://t.me/gpcrpromo', 't.me/s/gpcrpromo', 'https://t.me/s/gpcrpromo/'])
      expect(normalizeHandle(t)).toBe('gpcrpromo')
  })
  it('recusa o estranho', () => {
    for (const t of ['a/b', '@@x', 'abc', 'cañal_x', 'https://evil.example/abcd', 'https://user@t.me/abcd', // public-ok
      'https://t.me/abcd?x=1', 't.me/abcd/12', 'gpcr promo', '', null, 'a'.repeat(33)])
      expect(normalizeHandle(t)).toBeNull()
  })
})

describe('Configurações', () => {
  it('engrenagem na navegação leva pra página', async () => {
    mockApi(base({ '/api/deals': [], '/api/stores': [] }))
    render(<App />)
    const link = screen.getByRole('link', { name: 'Configurações' })
    expect(link).toHaveAttribute('href', '#/config')
    expect(link.querySelector('svg')).not.toBeNull()
  })

  it('mostra todas as seções, com a origem de cada campo', async () => {
    open()
    mockApi(base({ '/api/settings': settings({ language: 'pt-BR' }, { language: { source: 'banco' } }) }))
    render(<App />)
    expect(await screen.findByRole('region', { name: 'Idioma' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Configurações' })).toBeInTheDocument()
    for (const t of ['Canais do Telegram', 'Lojas', 'Coleta', 'Meu PC', 'Faixa de preço', 'Modo jogo', 'Notificação',
      'IA local (Ollama)', 'Idioma']) expect(section(t)).toBeInTheDocument()
    expect(within(section('Idioma')).getByText('salvo')).toBeInTheDocument()
    expect(within(section('Lojas')).getByText('padrão')).toBeInTheDocument()
    expect(within(section('Notificação')).getByText(/quem agenda entrega/)).toBeInTheDocument()
    expect(within(section('IA local (Ollama)')).getByRole('radio', { name: /Automático/ })).toBeChecked()
    expect(screen.getByLabelText('Socket')).toHaveValue('AM4')
    expect(screen.getByLabelText('Processador')).toHaveValue('AMD Ryzen 5 5600')
    // restaurar só fica ativo no que está salvo
    expect(within(section('Idioma')).getByRole('button', { name: /restaurar padrão/i })).toBeEnabled()
    expect(within(section('Lojas')).getByRole('button', { name: /restaurar padrão/i })).toBeDisabled()
  })

  it('campo de variável de ambiente fica bloqueado e diz qual', async () => {
    open()
    mockApi(base({ '/api/settings': settings({ collect_every_minutes: 30 },
      { collect_every_minutes: { source: 'env', env: ['PCB_COLLECT_EVERY_MINUTES'], locked: true } }) }))
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Coleta' })
    expect(within(s).getByText('variável de ambiente (PCB_COLLECT_EVERY_MINUTES)')).toBeInTheDocument()
    expect(within(s).getByLabelText('Coletar a cada')).toBeDisabled()
    expect(within(s).getByRole('button', { name: 'Salvar Coleta' })).toBeDisabled()
  })

  it('salvar manda só a chave da seção, em JSON, e avisa', async () => {
    open()
    const calls = mockApi(base({
      'PUT /api/settings': (u, o) => settings(JSON.parse(o.body), { price_range: { source: 'banco' } }),
    }))
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Faixa de preço' })
    fireEvent.change(within(s).getByLabelText('De'), { target: { value: '1000' } })
    fireEvent.change(within(s).getByLabelText('Até'), { target: { value: '5000' } })
    fireEvent.click(within(s).getByRole('button', { name: 'Salvar Faixa de preço' }))
    expect(await within(s).findByRole('status')).toHaveTextContent('Salvo.')
    const put = calls.find((c) => c.method === 'PUT')
    expect(put.url).toBe('/api/settings')
    expect(put.body).toEqual({ price_range: { min: 1000, max: 5000 } })
    expect(put.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(within(s).getByText('salvo')).toBeInTheDocument()
  })

  it('erro 422 da API aparece no campo', async () => {
    open()
    mockApi(base({
      'PUT /api/settings': json({ detail: { message: 'configuração recusada',
        fields: { price_range: 'o mínimo não pode ser maior que o máximo' } } }, 422),
    }))
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Faixa de preço' })
    fireEvent.change(within(s).getByLabelText('De'), { target: { value: '9000' } })
    fireEvent.change(within(s).getByLabelText('Até'), { target: { value: '10' } })
    fireEvent.click(within(s).getByRole('button', { name: 'Salvar Faixa de preço' }))
    await waitFor(() => expect(within(s).getAllByRole('alert').map((a) => a.textContent).join(' '))
      .toContain('o mínimo não pode ser maior que o máximo'))
    expect(within(s).getByText('padrão')).toBeInTheDocument()
  })

  it('lojas: não deixa desligar todas sem nem chamar a API', async () => {
    open()
    const calls = mockApi(base())
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Lojas' })
    for (const n of ['KaBuM!', 'Terabyte', 'Amazon']) fireEvent.click(within(s).getByLabelText(n))
    fireEvent.click(within(s).getByRole('button', { name: 'Salvar Lojas' }))
    expect(await within(s).findByRole('alert')).toHaveTextContent('pelo menos uma loja')
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
  })

  it('restaurar padrão chama a rota e volta o valor', async () => {
    open()
    const calls = mockApi(base({
      '/api/settings': settings({ language: 'en' }, { language: { source: 'banco' } }),
      'POST /api/settings/reset/language': settings(),
    }))
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Language' })
    expect(within(s).getByLabelText('Language')).toHaveValue('en')
    fireEvent.click(within(s).getByRole('button', { name: /restore default/i }))
    const sPt = await screen.findByRole('region', { name: 'Idioma' })
    expect(await within(sPt).findByRole('status')).toHaveTextContent('Padrão restaurado.')
    expect(within(sPt).getByLabelText('Idioma')).toHaveValue('pt-BR')
    expect(calls.some((c) => c.method === 'POST' && c.url === '/api/settings/reset/language')).toBe(true)
  })

  it('PC: troca socket e RAM e manda o PC inteiro', async () => {
    open()
    const calls = mockApi(base({ 'PUT /api/settings': (u, o) => settings(JSON.parse(o.body)) }))
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Meu PC' })
    fireEvent.change(within(s).getByLabelText('Socket'), { target: { value: 'AM5' } })
    fireEvent.change(within(s).getByLabelText('RAM (GB)'), { target: { value: '32' } })
    fireEvent.click(within(s).getByRole('button', { name: 'Salvar Meu PC' }))
    await within(s).findByRole('status')
    const body = calls.find((c) => c.method === 'PUT').body.current_pc
    expect(body).toMatchObject({ socket: 'AM5', ram_gb: 32, memory_type: 'DDR4', cpu: 'AMD Ryzen 5 5600' })
  })

  it('erro ao carregar as configurações mostra o erro', async () => {
    open()
    mockApi(base({ '/api/settings': json({}, 500) }))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Não consegui falar com o backend')
  })
})

describe('Configurações: canais', () => {
  it('lista os canais com estado e contador', async () => {
    open()
    mockApi(base())
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Canais do Telegram' })
    expect(await within(s).findByText('@gpcrpromo')).toBeInTheDocument()
    expect(within(s).getByText('2 de 50')).toBeInTheDocument()
    expect(within(s).getByRole('switch', { name: 'Ler @gpcrpromo' })).toBeChecked()
    expect(within(s).getByRole('switch', { name: 'Ler @lipeofertas' })).not.toBeChecked()
    expect(within(s).getByText('com problema')).toBeInTheDocument()
  })

  it('adicionar: handle inválido avisa sem chamar a API', async () => {
    open()
    const calls = mockApi(base())
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Canais do Telegram' })
    fireEvent.change(within(s).getByLabelText('Adicionar canal'), { target: { value: 'a/b' } })
    fireEvent.click(within(s).getByRole('button', { name: 'Adicionar' }))
    expect(await within(s).findByRole('alert')).toHaveTextContent('Nome de canal inválido')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('adicionar: sucesso entra na lista', async () => {
    open()
    const calls = mockApi(base({
      'POST /api/channels': json({ slug: 'NovoCanal', title: 'Novo', enabled: true, source: 'usuario', posts: 0,
        last_ok_at: null, fail_count: 0, last_error: null }, 201),
    }))
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Canais do Telegram' })
    await within(s).findByText('@gpcrpromo')
    fireEvent.change(within(s).getByLabelText('Adicionar canal'), { target: { value: 'https://t.me/NovoCanal' } })
    fireEvent.click(within(s).getByRole('button', { name: 'Adicionar' }))
    expect(await within(s).findByText('@NovoCanal')).toBeInTheDocument()
    expect(within(s).getByRole('status')).toHaveTextContent('@NovoCanal adicionado.')
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ handle: 'https://t.me/NovoCanal' })
  })

  it.each([
    [422, 'este canal não tem prévia pública (t.me/s/<nome>); só canal público com prévia funciona'],
    [409, 'o canal @gpcrpromo já está na lista'],
    [503, 'sem rede: não consegui abrir o t.me agora; nada foi gravado, tente de novo'],
  ])('adicionar: erro %i da API aparece', async (status, detail) => {
    open()
    mockApi(base({ 'POST /api/channels': json({ detail }, status) }))
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Canais do Telegram' })
    fireEvent.change(within(s).getByLabelText('Adicionar canal'), { target: { value: '@canalfechado' } })
    fireEvent.click(within(s).getByRole('button', { name: 'Adicionar' }))
    expect(await within(s).findByRole('alert')).toHaveTextContent(detail)
    expect(within(s).queryByText('@canalfechado')).toBeNull()
  })

  it('liga/desliga chama PUT com enabled', async () => {
    open()
    const calls = mockApi(base({ 'PUT /api/channels/gpcrpromo': { ...CHANNELS[0], enabled: false } }))
    render(<App />)
    const sw = await screen.findByRole('switch', { name: 'Ler @gpcrpromo' })
    fireEvent.click(sw)
    await waitFor(() => expect(sw).not.toBeChecked())
    expect(calls.find((c) => c.method === 'PUT').body).toEqual({ enabled: false })
  })

  it('remover pede confirmação e depois chama DELETE', async () => {
    open()
    const calls = mockApi(base({ 'DELETE /api/channels/gpcrpromo': null }))
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Canais do Telegram' })
    fireEvent.click(await within(s).findByRole('button', { name: 'Remover @gpcrpromo' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    fireEvent.click(within(s).getByRole('button', { name: 'Confirmar remoção de @gpcrpromo' }))
    await waitFor(() => expect(within(s).queryByText('@gpcrpromo')).toBeNull())
    expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/channels/gpcrpromo')).toBe(true)
  })
})

describe('o resto do app mostra as configurações', () => {
  it('promoções avisam a faixa de preço e a loja desligada', async () => {
    mockApi(base({
      '/api/deals': [],
      '/api/stores': [{ slug: 'kabum', name: 'KaBuM!', active: 1, status_note: null },
        { slug: 'terabyte', name: 'Terabyte', active: 0, status_note: null }],
      '/api/settings': settings({ price_range: { min: 1000, max: 5000 } }),
    }))
    render(<App />)
    expect(await screen.findByText(/Desligadas: Terabyte/)).toBeInTheDocument()
    expect(screen.getByText(/Faixa de preço/)).toHaveTextContent(/1\.000,00 a R\$\s5\.000,00/)
    expect(screen.getByRole('link', { name: 'mudar nas Configurações' })).toHaveAttribute('href', '#/config')
  })
})
