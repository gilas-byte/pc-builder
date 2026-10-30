import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import OllamaSection, { PULL_POLL_MS, pctText } from '../pages/OllamaSection.jsx'

// Seção "IA local (Ollama)". Nada fala com Ollama de verdade: fetch falso por rota.
const VALUES = { ollama: { url: 'http://127.0.0.1:11434', models: ['qwen2.5:3b'] }, classifier: 'auto' }
const META = { ollama: { source: 'default', env: [], locked: false }, classifier: { source: 'default', env: [], locked: false } }
const OPTIONS = { max_models: 3, min_models: 1 }
const STATUS_OK = { reachable: true, url: VALUES.ollama.url, version: '0.12.3', error: null, warning: null,
  classifier_mode: 'auto', classifier_effective: 'ollama', models_selected: ['qwen2.5:3b'], models_missing: [] }
const STATUS_DOWN = { ...STATUS_OK, reachable: false, version: null, classifier_effective: 'rules',
  error: 'o Ollama não respondeu (está desligado ou o endereço está errado)' }
const MODELS = { models: [
  { name: 'qwen2.5:3b', size: 1_929_000_000, quantization: 'Q4_K_M', parameters: '3.1B' },
  { name: 'llama3.2:3b', size: 2_019_000_000, quantization: 'Q4_K_M', parameters: '3.2B' },
  { name: 'gemma3:4b', size: 3_338_000_000, quantization: 'Q4_K_M', parameters: '4.3B' },
  { name: 'phi4:14b', size: 9_100_000_000, quantization: 'Q4_K_M', parameters: '14.7B' },
] }
const INFO = (pct = 99.7) => ({ mode: 'auto', effective: 'ollama', rules_metrics: { pct, n: 295, ok: 294 },
  counts: { ollama: 10, rules: 4, sem_tipo: 1 } })
const IDLE = { model: null, state: 'idle', percent: 0, completed: 0, total: 0, error: null }
const json = (v, status = 200) => new Response(v === null ? null : JSON.stringify(v), { status })

function mockApi(over = {}) {
  const routes = { '/api/ollama/status': STATUS_OK, '/api/classifier': INFO(), '/api/ollama/models': MODELS,
    '/api/ollama/pull': IDLE, ...over }
  const calls = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts = {}) => {
    const method = opts.method || 'GET'
    calls.push({ url, method, body: opts.body ? JSON.parse(opts.body) : undefined })
    const key = `${method} ${url}`
    const v = key in routes ? routes[key] : method === 'GET' ? routes[url] : undefined
    if (v === undefined) return json({ detail: 'rota não mockada' }, 404)
    const r = typeof v === 'function' ? v(url, opts) : v
    return r instanceof Response ? r : json(r)
  })
  return calls
}

const show = (props = {}) => {
  const onSaved = vi.fn()
  const view = render(<OllamaSection values={VALUES} meta={META} options={OPTIONS} origin={null} onSaved={onSaved}
    {...props} />)
  return { onSaved, ...view }
}

describe('IA local (Ollama)', () => {
  it('a porcentagem das regras vem da API, não do código', async () => {
    mockApi({ '/api/classifier': INFO(87.3) })
    show()
    expect(await screen.findByText('87,3%')).toBeInTheDocument()
    expect(screen.getByText(/Sem Ollama instalado\? O app usa as regras/)).toBeInTheDocument()
    expect(screen.queryByText(/99,7/)).toBeNull()
    expect(pctText(99.7)).toBe('99,7%')
  })

  it('sem métricas na API não inventa número', async () => {
    mockApi({ '/api/classifier': { ...INFO(), rules_metrics: null } })
    show()
    expect(await screen.findByText(/Ofertas guardadas: 10 pela IA, 4 pelas regras, 1 sem tipo/)).toBeInTheDocument()
    expect(screen.queryByText(/%/)).toBeNull()
  })

  it('verde "responde" e quem classifica agora', async () => {
    mockApi()
    const { container } = show()
    expect(await screen.findByText('Ollama responde')).toBeInTheDocument()
    expect(container.querySelector('.ai-dot.ok')).not.toBeNull()
    expect(screen.getByText('a IA (Ollama)')).toBeInTheDocument()
  })

  it('vermelho "não responde" com o motivo, e as regras assumem', async () => {
    mockApi({ '/api/ollama/status': STATUS_DOWN, '/api/ollama/models': json({ detail: STATUS_DOWN.error }, 503) })
    const { container } = show()
    expect(await screen.findByText('Ollama não responde')).toBeInTheDocument()
    expect(container.querySelector('.ai-dot.bad')).not.toBeNull()
    expect(screen.getByText(/Motivo: o Ollama não respondeu/)).toBeInTheDocument()
    expect(screen.getByText('as regras')).toBeInTheDocument()
    expect(await screen.findByText(/Não deu para listar os modelos/)).toBeInTheDocument()
  })

  it('sem modelos instalados: estado vazio com sugestão', async () => {
    mockApi({ '/api/ollama/models': { models: [] } })
    show({ values: { ...VALUES, ollama: { ...VALUES.ollama, models: ['qwen2.5:3b'] } } })
    expect(await screen.findByText(/Nenhum modelo instalado ainda/)).toBeInTheDocument()
    expect(screen.getByText('não instalado')).toBeInTheDocument()             // o escolhido aparece marcado
  })

  it('trocar o modo salva na hora só a chave classifier', async () => {
    const calls = mockApi({ 'PUT /api/settings': { values: { ...VALUES, classifier: 'rules' } } })
    const { onSaved } = show()
    fireEvent.click(screen.getByRole('radio', { name: /Só regras/ }))
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    expect(calls.find((c) => c.method === 'PUT').body).toEqual({ classifier: 'rules' })
    expect(await screen.findByText('Modo salvo.')).toBeInTheDocument()
  })

  it('modo travado por variável de ambiente', async () => {
    mockApi()
    show({ meta: { ...META, classifier: { source: 'env', env: ['PCB_CLASSIFIER'], locked: true } } })
    expect(screen.getByRole('radio', { name: /Só Ollama/ })).toBeDisabled()
    expect(screen.getByText(/PCB_CLASSIFIER/)).toBeInTheDocument()
  })

  it('modelos: mostra tamanho, no máximo 3 e salva a escolha', async () => {
    const calls = mockApi({ 'PUT /api/settings': { values: VALUES } })
    show()
    const box = await screen.findByRole('checkbox', { name: /llama3\.2:3b/ })
    expect(screen.getByText(/2 GB · Q4_K_M · 3\.2B/)).toBeInTheDocument()
    expect(screen.getByText(/precisam de mais memória de vídeo\/RAM/)).toBeInTheDocument()
    fireEvent.click(box)
    fireEvent.click(screen.getByRole('checkbox', { name: /gemma3:4b/ }))
    expect(screen.getByRole('checkbox', { name: /phi4:14b/ })).toBeDisabled()          // já tem 3
    fireEvent.click(screen.getByRole('button', { name: 'Salvar modelos escolhidos' }))
    await screen.findByText('Modelos salvos.')
    expect(calls.find((c) => c.method === 'PUT').body).toEqual(
      { ollama: { url: VALUES.ollama.url, models: ['qwen2.5:3b', 'llama3.2:3b', 'gemma3:4b'] } })
  })

  it('modelos: nenhum escolhido não chama a API', async () => {
    const calls = mockApi()
    show()
    fireEvent.click(await screen.findByRole('checkbox', { name: /qwen2\.5:3b/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Salvar modelos escolhidos' }))
    expect(await screen.findByText('Escolha pelo menos 1 modelo.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
  })

  it('Testar o endereço não salva; Salvar manda o endereço', async () => {
    const other = 'http://192.0.2.10:11434'  // public-ok (exemplo)
    const calls = mockApi({
      [`/api/ollama/status?url=${encodeURIComponent(other)}`]: { ...STATUS_OK, url: other, warning: 'outra máquina' },
      'PUT /api/settings': { values: { ...VALUES, ollama: { ...VALUES.ollama, url: other } } },
    })
    show()
    const input = screen.getByLabelText('Endereço do Ollama')
    fireEvent.change(input, { target: { value: other } })
    fireEvent.click(screen.getByRole('button', { name: 'Testar endereço do Ollama' }))
    expect(await screen.findByText('Responde (versão 0.12.3).')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Salvar endereço do Ollama' }))
    await screen.findByText('Endereço salvo.')
    expect(calls.find((c) => c.method === 'PUT').body).toEqual({ ollama: { url: other, models: ['qwen2.5:3b'] } })
  })

  it('erro 422 ao salvar o endereço aparece', async () => {
    mockApi({ 'PUT /api/settings': json({ detail: { message: 'configuração recusada',
      fields: { ollama: 'endereço do Ollama não pode ser link-local' } } }, 422) })
    show()
    fireEvent.change(screen.getByLabelText('Endereço do Ollama'), { target: { value: 'http://169.254.169.254' } })
    fireEvent.click(screen.getByRole('button', { name: 'Salvar endereço do Ollama' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('link-local')
  })

  it('baixar: nome inválido nem chama a API', async () => {
    const calls = mockApi()
    show()
    fireEvent.change(screen.getByLabelText('Baixar outro modelo'), { target: { value: 'a b' } })
    fireEvent.click(screen.getByRole('button', { name: 'Baixar' }))
    expect(await screen.findByText(/Nome inválido/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('baixar: barra com aria-valuenow, polling de 1 s que para no fim e cancelar', async () => {
    const running = (p) => ({ ...IDLE, model: 'qwen2.5:7b', state: 'running', percent: p })
    let next = running(40)
    const calls = mockApi({ 'POST /api/ollama/pull': running(0), '/api/ollama/pull': () => next,
      'DELETE /api/ollama/pull': { canceled: true } })
    const timers = []
    const real = window.setInterval
    vi.spyOn(window, 'setInterval').mockImplementation((fn, ms) => { timers.push({ fn, ms }); return real(() => {}, 1e9) })
    const clear = vi.spyOn(window, 'clearInterval')
    show()
    fireEvent.change(screen.getByLabelText('Baixar outro modelo'), { target: { value: 'qwen2.5:7b' } })
    fireEvent.click(screen.getByRole('button', { name: 'Baixar' }))
    const bar = await screen.findByRole('progressbar', { name: 'Download de qwen2.5:7b' })
    expect(bar).toHaveAttribute('aria-valuenow', '0')
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ model: 'qwen2.5:7b' })
    const poll = timers.find((t) => t.ms === PULL_POLL_MS)
    expect(PULL_POLL_MS).toBe(1000)
    expect(poll).toBeTruthy()
    await act(async () => { poll.fn() })
    await waitFor(() => expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40'))
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    next = { ...running(40), state: 'done', percent: 100 }
    await act(async () => { poll.fn() })
    expect(await screen.findByText(/instalado\. Marque na lista/)).toBeInTheDocument()
    expect(clear).toHaveBeenCalled()                                    // terminou: o polling parou
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('o polling para ao sair da página', async () => {
    mockApi({ '/api/ollama/pull': { ...IDLE, model: 'x:1', state: 'running', percent: 5 } })
    const set = vi.spyOn(window, 'setInterval')
    const clear = vi.spyOn(window, 'clearInterval')
    const { unmount } = show()
    await screen.findByRole('progressbar')
    const id = set.mock.results.find((r, i) => set.mock.calls[i][1] === PULL_POLL_MS).value
    unmount()
    expect(clear).toHaveBeenCalledWith(id)
  })

  it('sem download: nenhum polling', async () => {
    mockApi()
    const set = vi.spyOn(window, 'setInterval')
    show()
    await screen.findByText('Ollama responde')
    expect(set.mock.calls.filter((c) => c[1] === PULL_POLL_MS)).toEqual([])
  })

  it('download que falhou mostra o motivo', async () => {
    mockApi({ '/api/ollama/pull': { ...IDLE, model: 'nao-existe:1b', state: 'error',
      error: 'esse modelo não existe na biblioteca do Ollama (confira o nome)' } })
    show()
    expect(await screen.findByText(/O download de nao-existe:1b falhou: esse modelo não existe/)).toBeInTheDocument()
  })

  it('teste rápido: tipo, origem e o porquê das regras', async () => {
    const calls = mockApi({ 'POST /api/classifier/test': { kind: 'peca:gpu', source: 'ollama', agree: 3, why: null,
      fallback: false, error: null, rules: { kind: 'peca:gpu', why: 'cita “rtx 5060” e a ficha do produto' } } })
    show()
    const box = screen.getByLabelText(/Cole o título/)
    expect(box).toHaveAttribute('maxLength', '2000')
    fireEvent.change(box, { target: { value: 'Placa de Vídeo RTX 5060 8GB' } })
    fireEvent.click(screen.getByRole('button', { name: 'Classificar' }))
    const dl = await screen.findByText('De onde veio')
    const res = dl.closest('dl')
    expect(within(res).getAllByText('Placa de vídeo')[0]).toBeInTheDocument()
    expect(within(res).getByText('IA (Ollama), 3 votos')).toBeInTheDocument()
    expect(within(res).getByText(/cita “rtx 5060”/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ text: 'Placa de Vídeo RTX 5060 8GB' })
  })

  it('teste rápido: Ollama fora no automático avisa que usou as regras', async () => {
    mockApi({ 'POST /api/classifier/test': { kind: null, source: null, agree: null, why: 'RAM sem sinal de desktop',
      fallback: true, error: 'o Ollama não respondeu', rules: { kind: null, why: 'RAM sem sinal de desktop' } } })
    show()
    fireEvent.change(screen.getByLabelText(/Cole o título/), { target: { value: 'Memória DDR5 8GB' } })
    fireEvent.click(screen.getByRole('button', { name: 'Classificar' }))
    expect(await screen.findByText('O Ollama não respondeu; usei as regras.')).toBeInTheDocument()
    expect(screen.getAllByText(/sem tipo \(na dúvida\)/).length).toBeGreaterThan(0)
  })
})
