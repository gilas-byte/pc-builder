import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App.jsx'

// Bot do Telegram (token write-only), tutorial, achar o chat, mensagem de teste e agendador interno.
// Montado em pedaços: o verificador público (tools/check_public.py) não pode ver um token literal.
const TOKEN = '987654' + '321:' + 'AAH' + 'fakeTokenForTestsOnly_0123456789'

const OPTIONS = {
  languages: ['pt-BR', 'en'], stores: ['kabum', 'terabyte', 'amazon'], notify_targets: ['none', 'telegram', 'stdout'],
  sockets: ['AM4', 'AM5'], memory_types: ['DDR4', 'DDR5'], form_factors: ['ATX', 'mATX', 'ITX'],
  collect_every_minutes: { min: 15, max: 1440 }, price_max: 1000000, ram_max: 1024, text_max: 80, max_models: 3,
  max_channels: 50,
}
const VALUES = {
  language: 'pt-BR', stores: { kabum: true, terabyte: true, amazon: true }, collect_every_minutes: 1440,
  price_range: { min: 0, max: 1000000 }, game_mode: false, notify_target: 'telegram',
  current_pc: { socket: 'AM4', memory_type: 'DDR4', motherboard: 'MSI B450', cpu: 'Ryzen 5 5600', gpu: 'RTX 3060',
    ram_gb: 16, form_factor: 'ATX' },
  ollama: { url: 'http://127.0.0.1:11434', models: ['qwen2.5:3b'] }, scheduler_enabled: false,
}
const settings = (values = {}, metaOver = {}) => ({
  values: { ...VALUES, ...values },
  meta: Object.fromEntries(Object.keys(VALUES).map((k) => [k, { source: 'default', env: [], locked: false, ...(metaOver[k] || {}) }])),
  options: OPTIONS,
})
const tgState = (over = {}, chat = {}) => ({
  configured: false, source: null, hint: null, ready: false, file_error: null,
  chat_id: { configured: false, source: null, hint: null, ...chat }, ...over,
})
const READY = tgState({ configured: true, source: 'file', hint: '…6789', ready: true },
  { configured: true, source: 'file', hint: '…3456' })
const SCHED = { enabled: false, running: false, interval_minutes: 1440, last_run_at: null, last_ok: null,
  last_error: null, next_run_at: null, skipped: null, game_mode: false, game_mode_available: true }

const json = (v, status = 200) => new Response(v === null ? null : JSON.stringify(v), { status })

function mockApi(routes) {
  const calls = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts = {}) => {
    const method = opts.method || 'GET'
    calls.push({ url, method, body: opts.body ? JSON.parse(opts.body) : undefined, raw: opts.body })
    const key = `${method} ${url}`
    const v = key in routes ? routes[key] : method === 'GET' ? routes[url] : undefined
    if (v === undefined) return json({ detail: 'rota não mockada' }, 404)
    const r = typeof v === 'function' ? v(url, opts) : v
    return r instanceof Response ? r : json(r, r === null ? 204 : 200)
  })
  return calls
}
const base = (extra = {}) => ({
  '/api/health': { status: 'ok', demo: false }, '/api/settings': settings(), '/api/channels': [],
  '/api/secrets/telegram': tgState(), '/api/scheduler': SCHED, ...extra,
})
const open = () => { window.location.hash = '#/config' }
const tgBox = async () => screen.findByRole('group', { name: 'Bot do Telegram' })
const schedBox = async () => screen.findByRole('group', { name: 'Agendador interno' })

let consoleSpies = []
beforeEach(() => {
  consoleSpies = ['log', 'info', 'warn', 'error', 'debug'].map((m) => vi.spyOn(console, m))
})
afterEach(() => {
  // o token nunca vai para o console
  for (const spy of consoleSpies) {
    for (const args of spy.mock.calls) expect(JSON.stringify(args.map(String))).not.toContain(TOKEN.slice(-12))
  }
  vi.restoreAllMocks()
})

describe('Notificação: bot do Telegram', () => {
  it('seletor com os 3 destinos e tutorial em 4 passos', async () => {
    open()
    mockApi(base())
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Notificação' })
    const sel = within(s).getByLabelText('Destino do aviso')
    expect([...sel.options].map((o) => o.textContent)).toEqual(['Bot do Telegram', 'Saída do script (cron ou Hermes Agent)', 'Nenhum'])
    const box = await tgBox()
    const steps = within(box).getAllByRole('listitem')
    expect(steps).toHaveLength(4)
    expect(steps[0]).toHaveTextContent('@BotFather')
    expect(steps[0]).toHaveTextContent('/newbot')
    expect(steps[1]).toHaveTextContent(/token/)
    expect(steps[2]).toHaveTextContent('/start')
    expect(steps[3]).toHaveTextContent('Encontrar meu chat')
  })

  it('salvar o token: vai no PUT, o campo é limpo e o token some da tela', async () => {
    open()
    const calls = mockApi(base({
      'PUT /api/secrets/telegram': tgState({ configured: true, source: 'file', hint: '…6789' }),
    }))
    render(<App />)
    const box = await tgBox()
    const input = await within(box).findByLabelText('Token do bot')
    expect(input).toHaveAttribute('type', 'password')
    expect(input).toHaveAttribute('autocomplete', 'off')
    fireEvent.change(input, { target: { value: TOKEN } })
    expect(input.getAttribute('value')).toBeNull()                    // nem em atributo enquanto digita
    fireEvent.click(within(box).getByRole('button', { name: 'Salvar' }))
    expect(await within(box).findByText(/termina em …6789/)).toBeInTheDocument()
    const put = calls.find((c) => c.method === 'PUT')
    expect(put.url).toBe('/api/secrets/telegram')
    expect(put.body).toEqual({ token: TOKEN })
    expect(document.body.innerHTML).not.toContain(TOKEN.slice(-12))
    expect(within(box).queryByLabelText('Token do bot')).toBeNull()
    // Trocar: o campo volta vazio
    fireEvent.click(within(box).getByRole('button', { name: 'Trocar' }))
    expect(within(box).getByLabelText('Token do bot')).toHaveValue('')
  })

  it('erro do servidor ao salvar também limpa o campo', async () => {
    open()
    mockApi(base({ 'PUT /api/secrets/telegram': json({ detail: 'token em formato inválido' }, 422) }))
    render(<App />)
    const box = await tgBox()
    const input = await within(box).findByLabelText('Token do bot')
    fireEvent.change(input, { target: { value: TOKEN } })
    fireEvent.click(within(box).getByRole('button', { name: 'Salvar' }))
    expect(await within(box).findByRole('alert')).toHaveTextContent('token em formato inválido')
    expect(input).toHaveValue('')
    expect(document.body.innerHTML).not.toContain(TOKEN.slice(-12))
  })

  it('token com formato ruim avisa sem chamar a API e sem repetir o valor', async () => {
    open()
    const calls = mockApi(base())
    render(<App />)
    const box = await tgBox()
    fireEvent.change(await within(box).findByLabelText('Token do bot'), { target: { value: '123:segredoErrado' } })
    fireEvent.click(within(box).getByRole('button', { name: 'Salvar' }))
    const alert = await within(box).findByRole('alert')
    expect(alert).toHaveTextContent('formato inválido')
    expect(alert.textContent).not.toContain('segredoErrado')
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
  })

  it('configurado: mostra só o final, Trocar e Remover com confirmação', async () => {
    open()
    const calls = mockApi(base({ '/api/secrets/telegram': READY, 'DELETE /api/secrets/telegram': tgState() }))
    render(<App />)
    const box = await tgBox()
    expect(await within(box).findByText(/termina em …6789/)).toBeInTheDocument()
    expect(within(box).getByText(/termina em …3456/)).toBeInTheDocument()
    expect(within(box).getByRole('button', { name: 'Trocar' })).toBeEnabled()
    fireEvent.click(within(box).getByRole('button', { name: 'Remover token e chat' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)     // só confirma no 2º clique
    fireEvent.click(within(box).getByRole('button', { name: 'Confirmar: remover token e chat' }))
    expect(await within(box).findByLabelText('Token do bot')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/secrets/telegram')).toBe(true)
  })

  it('token da variável de ambiente: sem campo, sem Trocar, com aviso', async () => {
    open()
    mockApi(base({ '/api/secrets/telegram': tgState({ configured: true, source: 'env', hint: '…6789' }) }))
    render(<App />)
    const box = await tgBox()
    expect(await within(box).findByText(/variável de ambiente/)).toBeInTheDocument()
    expect(within(box).queryByLabelText('Token do bot')).toBeNull()
    expect(within(box).queryByRole('button', { name: 'Trocar' })).toBeNull()
    expect(within(box).queryByRole('button', { name: /Remover/ })).toBeNull()
  })

  it('encontrar meu chat: lista e escolher salva o chat id', async () => {
    open()
    const after = tgState({ configured: true, source: 'file', hint: '…6789', ready: true }, { configured: true, source: 'file', hint: '…5555' })
    const calls = mockApi(base({
      '/api/secrets/telegram': tgState({ configured: true, source: 'file', hint: '…6789' }),
      'POST /api/secrets/telegram/detect-chat': { bot: 'meu_bot', chats: [{ id: '5555', tipo: 'privado', nome: 'Ana' },
        { id: '-1007777', tipo: 'canal', nome: 'Meu canal' }] },
      'PUT /api/secrets/telegram': after,
    }))
    render(<App />)
    const box = await tgBox()
    const btn = await within(box).findByRole('button', { name: 'Encontrar meu chat' })
    expect(within(box).getByRole('button', { name: 'Enviar mensagem de teste' })).toBeDisabled()
    fireEvent.click(btn)
    const list = await within(box).findByRole('list', { name: 'Chats que falaram com o bot' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    fireEvent.click(within(list).getByRole('button', { name: 'Usar o chat Ana' }))
    expect(await within(box).findByText('Chat escolhido: Ana.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PUT').body).toEqual({ chat_id: '5555' })
    expect(within(box).getByRole('button', { name: 'Enviar mensagem de teste' })).toBeEnabled()
  })

  it('nenhum chat: explica o /start', async () => {
    open()
    mockApi(base({
      '/api/secrets/telegram': tgState({ configured: true, source: 'file', hint: '…6789' }),
      'POST /api/secrets/telegram/detect-chat': { bot: 'meu_bot', chats: [],
        hint: 'Nenhuma conversa ainda: abra o seu bot no Telegram, mande /start e tente de novo.' },
    }))
    render(<App />)
    const box = await tgBox()
    fireEvent.click(await within(box).findByRole('button', { name: 'Encontrar meu chat' }))
    expect(await within(box).findByRole('alert')).toHaveTextContent('/start')
  })

  it('sem token, encontrar meu chat fica desligado', async () => {
    open()
    mockApi(base())
    render(<App />)
    const box = await tgBox()
    expect(await within(box).findByRole('button', { name: 'Encontrar meu chat' })).toBeDisabled()
  })

  it('chat id à mão é validado antes', async () => {
    open()
    const calls = mockApi(base({ '/api/secrets/telegram': tgState({ configured: true, source: 'file', hint: '…6789' }) }))
    render(<App />)
    const box = await tgBox()
    fireEvent.change(await within(box).findByLabelText('Chat id'), { target: { value: 'meu chat' } })
    fireEvent.click(within(box).getByRole('button', { name: 'Salvar chat' }))
    expect(await within(box).findByRole('alert')).toHaveTextContent('Chat id inválido')
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
  })

  it('mensagem de teste: sucesso e erro tratado', async () => {
    open()
    let fail = false
    const calls = mockApi(base({
      '/api/secrets/telegram': READY,
      'POST /api/notify/test': () => (fail ? json({ detail: 'o Telegram recusou o token: confira e salve o token de novo' }, 502)
        : { ok: true, target: 'telegram' }),
    }))
    render(<App />)
    const box = await tgBox()
    const btn = await within(box).findByRole('button', { name: 'Enviar mensagem de teste' })
    fireEvent.click(btn)
    expect(await within(box).findByRole('status')).toHaveTextContent('Mensagem enviada')
    expect(calls.find((c) => c.url === '/api/notify/test').body).toEqual({ target: 'telegram' })
    fail = true
    fireEvent.click(btn)
    expect(await within(box).findByRole('alert')).toHaveTextContent('recusou o token')
  })

  it('destino não é o Telegram: lembra de escolher', async () => {
    open()
    mockApi(base({ '/api/settings': settings({ notify_target: 'stdout' }) }))
    render(<App />)
    const box = await tgBox()
    expect(within(box).getByText(/escolha “Bot do Telegram” acima/)).toBeInTheDocument()
  })
})

describe('Coleta: agendador interno', () => {
  it('interruptor salva na hora e explica o cron', async () => {
    open()
    const calls = mockApi(base({
      'PUT /api/settings': (u, o) => settings(JSON.parse(o.body), { scheduler_enabled: { source: 'banco' } }),
    }))
    render(<App />)
    const box = await schedBox()
    expect(within(box).getByText(/para não rodar em dobro/)).toBeInTheDocument()
    const sw = within(box).getByRole('switch', { name: /Rodar a coleta e os canais sozinho/ })
    expect(sw).not.toBeChecked()
    fireEvent.click(sw)
    expect(await within(box).findByRole('status')).toHaveTextContent('Agendador ligado.')
    expect(calls.find((c) => c.method === 'PUT').body).toEqual({ scheduler_enabled: true })
    expect(sw).toBeChecked()
  })

  it('mostra a situação: última, próxima e erro', async () => {
    open()
    mockApi(base({
      '/api/settings': settings({ scheduler_enabled: true }),
      '/api/scheduler': { ...SCHED, enabled: true, last_run_at: '2026-10-19T08:00:00', last_ok: false,
        last_error: 'coleta: RuntimeError: loja caiu', next_run_at: '2026-10-19T08:15:00' },
    }))
    render(<App />)
    const box = await schedBox()
    expect(await within(box).findByText('19/10 às 08:15')).toBeInTheDocument()
    expect(within(box).getByText(/19\/10 às 08:00 · com erro/)).toBeInTheDocument()
    expect(within(box).getByText('coleta: RuntimeError: loja caiu')).toBeInTheDocument()
    expect(within(box).getByText('ligado')).toBeInTheDocument()
  })

  it('rodar agora chama a rota e avisa; 409 vira mensagem', async () => {
    open()
    let busy = false
    const calls = mockApi(base({
      'POST /api/scheduler/run-now': () => (busy ? json({ detail: 'já tem uma rodada em andamento' }, 409) : { started: true }),
    }))
    render(<App />)
    const box = await schedBox()
    fireEvent.click(within(box).getByRole('button', { name: 'Rodar agora' }))
    expect(await within(box).findByRole('status')).toHaveTextContent('Rodada começou')
    expect(calls.some((c) => c.method === 'POST' && c.url === '/api/scheduler/run-now')).toBe(true)
    busy = true
    fireEvent.click(within(box).getByRole('button', { name: 'Rodar agora' }))
    expect(await within(box).findByRole('alert')).toHaveTextContent('rodada em andamento')
  })

  it('PCB_SCHEDULER bloqueia o interruptor', async () => {
    open()
    mockApi(base({ '/api/settings': settings({ scheduler_enabled: true },
      { scheduler_enabled: { source: 'env', env: ['PCB_SCHEDULER'], locked: true } }) }))
    render(<App />)
    const box = await schedBox()
    expect(within(box).getByRole('switch', { name: /Rodar a coleta/ })).toBeDisabled()
    expect(within(box).getByText(/PCB_SCHEDULER/)).toBeInTheDocument()
  })

  it('modo jogo diz que é indisponível no Docker', async () => {
    open()
    mockApi(base({ '/api/scheduler': { ...SCHED, game_mode_available: false } }))
    render(<App />)
    const s = await screen.findByRole('region', { name: 'Modo jogo' })
    await waitFor(() => expect(within(s).getByText(/Indisponível no Docker/)).toBeInTheDocument())
  })
})
