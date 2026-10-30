import { render, screen, waitFor, within, fireEvent, act } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from '../App.jsx'
import { money, safeImg, safeUrl, when } from '../format.js'

// ------------------------------------------------------------------ dados falsos
const best = (cents, store = 'kabum', name = 'KaBuM!') => ({
  listing_id: 1, url: `https://www.${store}.com.br/p/1`, store, store_name: name,
  price_cash: cents, price_installment: cents + 1000, in_stock: 1, collected_at: '2026-10-09T09:00:00',
})
const GPU = {
  id: 7, category: 'gpu', brand: 'NVIDIA', model: 'RTX 4060', specs: { recommended_psu_w: 550 },
  image_url: 'https://img.kabum.com.br/gpu.jpg', best: best(189990), favorite: false,
  deal: { status: 'normal' }, spark: [200000, 195000, 189990],
}
const CPU = { ...GPU, id: 1, category: 'cpu', brand: 'AMD', model: 'Ryzen 5 5600', image_url: null, specs: { socket: 'AM4' }, best: best(69900) }
const DEAL = {
  listing_id: 9, url: 'https://www.pichau.com.br/p/9', part_id: 7, category: 'gpu', brand: 'NVIDIA', model: 'RTX 4060',
  store: 'pichau', store_name: 'Pichau', in_stock: 1, price_cash: 155000, median_cash: 190000, drop_pct: 18.4,
  status: 'deal', days_of_history: 29, image_url: null, spark: [190000, 189000, 155000], favorite: false,
}
const item = (category, part, extra = {}) => ({
  category, part_id: part?.id ?? null, brand: part?.brand, model: part?.model, best: part?.best ?? null,
  image_url: null, compat: part ? { compatible: true, warnings: [] } : undefined, ...extra,
})
const FULL = {
  id: 1, name: 'Build completa', kind: 'full', build_id: 1, total_cash: 259890, missing: [], unavailable: [],
  items: [item('cpu', CPU), item('gpu', GPU)],
}
const UPG = {
  id: 2, name: 'Upgrades do PC atual', kind: 'upgrade', build_id: 2, total_cash: 0, missing: ['gpu'], unavailable: [],
  items: [item('gpu', null)],
}

/** fetch falso: rotas → resposta. Função recebe (url, opts). */
function mockApi(routes) {
  const calls = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, opts = {}) => {
    calls.push([url, opts.method || 'GET'])
    const key = Object.keys(routes).find((k) => (k.endsWith('*') ? url.startsWith(k.slice(0, -1)) : url === k))
    if (!key) return new Response(JSON.stringify({ detail: 'rota não mockada' }), { status: 404 })
    const v = typeof routes[key] === 'function' ? routes[key](url, opts) : routes[key]
    if (v instanceof Response) return v
    return v === null ? new Response(null, { status: 204 }) : new Response(JSON.stringify(v), { status: 200 })
  })
  return calls
}
const HEALTH = { status: 'ok', demo: false, last_collection: '2026-10-09T09:00:00', parts: 2 }
const STORES = [
  { slug: 'kabum', name: 'KaBuM!', active: 1, status_note: null },
  { slug: 'amazon', name: 'Amazon', active: 1, status_note: null },
  { slug: 'pichau', name: 'Pichau', active: 1, status_note: 'bloqueia robô (HTTP 403)' },
  { slug: 'mercadolivre', name: 'Mercado Livre', active: 1, status_note: 'bloqueia robô' },
]
const base = (extra = {}) => ({
  '/api/health': HEALTH, '/api/stores': STORES, '/api/current-pc': { cpu: 'Ryzen 5 5600', motherboard: 'B450 TOMAHAWK MAX', gpu: 'RTX 3060', ram_gb: 16, memory_type: 'DDR4' },
  '/api/favorites/*': null, ...extra,
})
const goto = (hash) => { window.location.hash = hash }

// ------------------------------------------------------------------ utilitários
describe('formatação', () => {
  it('dinheiro em centavos vira real', () => {
    expect(money(129990).replace(/\s/g, ' ')).toBe('R$ 1.299,90')
    expect(money(null)).toBe('—')
  })
  it('data', () => expect(when('2026-10-09T09:05:00')).toBe('09/10 às 09:05'))
  it('link perigoso é barrado', () => {
    expect(safeUrl('javascript:alert(1)')).toBeNull()
    expect(safeUrl('https://www.kabum.com.br/x')).toBe('https://www.kabum.com.br/x')
  })
  it('foto de canal (cópia local) passa; caminho esquisito não', () => {
    expect(safeImg('/api/tg/img/gpcrpromo_9.jpg')).toBe('/api/tg/img/gpcrpromo_9.jpg')
    expect(safeImg('https://img.kabum.com.br/x.jpg')).toBe('https://img.kabum.com.br/x.jpg')
    for (const ruim of ['/api/tg/img/../x', '//evil.com/x.jpg', '/api/outra/coisa.jpg', 'javascript:alert(1)',
      '/api/tg/img/a b.jpg', '/api/tg/img/gpcrpromo_9.svg', '/api/tg/img/gpcrpromo_9.jpg?x=1', null, undefined, '']) expect(safeImg(ruim)).toBeNull()
  })
})

// ------------------------------------------------------------------ telas
describe('Promoções (tela inicial)', () => {
  it('mostra o cartão com queda, preço e link seguro pra loja', async () => {
    mockApi(base({ '/api/deals': [DEAL] }))
    render(<App />)
    expect(await screen.findByText('RTX 4060')).toBeInTheDocument()
    expect(screen.getByText('-18.4%')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /ver na pichau/i })
    expect(link).toHaveAttribute('href', 'https://www.pichau.com.br/p/9')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toContain('noopener')
    expect(screen.getAllByText(/09\/10 às 09:00/).length).toBeGreaterThan(0)
  })

  it('vazio explica o porquê', async () => {
    mockApi(base({ '/api/deals': [] }))
    render(<App />)
    expect(await screen.findByText('Nenhuma promoção hoje.')).toBeInTheDocument()
  })

  it('erro de API vira mensagem e botão de tentar de novo', async () => {
    mockApi(base({ '/api/deals': new Response('{}', { status: 500 }) }))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Não consegui falar com o backend')
    expect(screen.getByRole('button', { name: 'Tentar de novo' })).toBeInTheDocument()
  })

  it('faixa EXEMPLO aparece só no modo exemplo', async () => {
    mockApi(base({ '/api/health': { ...HEALTH, demo: true }, '/api/deals': [] }))
    render(<App />)
    expect(await screen.findByRole('note')).toHaveTextContent('EXEMPLO')
  })

  it('sem modo exemplo, sem faixa', async () => {
    mockApi(base({ '/api/deals': [] }))
    render(<App />)
    await screen.findByText('Nenhuma promoção hoje.')
    expect(screen.queryByRole('note')).toBeNull()
  })
})

describe('Peças', () => {
  it('lista em cartões, foto quando tem e ícone quando não tem', async () => {
    goto('#/pecas')
    mockApi(base({ '/api/parts*': [CPU, GPU] }))
    render(<App />)
    expect(await screen.findByText('Ryzen 5 5600')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'NVIDIA RTX 4060' })).toHaveAttribute('src', GPU.image_url)
    expect(screen.queryByRole('img', { name: 'AMD Ryzen 5 5600' })).toBeNull() // sem foto → ícone
  })

  it('filtra por categoria e busca', async () => {
    goto('#/pecas')
    const calls = mockApi(base({ '/api/parts*': [CPU] }))
    render(<App />)
    await screen.findByText('Ryzen 5 5600')
    fireEvent.click(screen.getByRole('tab', { name: 'Processador' }))
    await waitFor(() => expect(calls.some(([u]) => u === '/api/parts?category=cpu')).toBe(true))
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'ryzen' } })
    await waitFor(() => expect(calls.some(([u]) => u.includes('q=ryzen'))).toBe(true))
  })

  it('banco vazio: "ainda não tenho preços"', async () => {
    goto('#/pecas')
    mockApi(base({ '/api/parts*': [] }))
    render(<App />)
    expect(await screen.findByText('Ainda não tenho preços.')).toBeInTheDocument()
  })

  it('favoritar chama a API e acende a estrela', async () => {
    goto('#/pecas')
    const calls = mockApi(base({ '/api/parts*': [GPU] }))
    render(<App />)
    const star = await screen.findByRole('button', { name: /favoritar nvidia rtx 4060/i })
    expect(star).toHaveAttribute('aria-pressed', 'false')
    await act(async () => { fireEvent.click(star) })
    expect(calls).toContainEqual(['/api/favorites/7', 'PUT'])
    expect(await screen.findByRole('button', { name: /tirar nvidia rtx 4060/i })).toHaveAttribute('aria-pressed', 'true')
  })

  it('favoritos vazio', async () => {
    goto('#/favoritos')
    const calls = mockApi(base({ '/api/parts*': [] }))
    render(<App />)
    expect(await screen.findByText('Nenhum favorito ainda.')).toBeInTheDocument()
    expect(calls.some(([u]) => u.includes('favorites=true'))).toBe(true)
  })
})

describe('Detalhe da peça', () => {
  it('preço de cada loja lado a lado, links seguros e histórico', async () => {
    goto('#/pecas/7')
    const offers = [
      { ...best(189990), deal: { status: 'normal' } },
      { ...best(195000, 'terabyteshop', 'Terabyte'), listing_id: 2, deal: { status: 'normal' } },
    ]
    const hist = ['2026-10-07', '2026-10-08', '2026-10-09'].flatMap((d, i) => [
      { store: 'kabum', price_cash: 190000 - i * 100, collected_at: `${d}T09:00:00` },
      { store: 'terabyte', price_cash: 196000 - i * 500, collected_at: `${d}T09:00:00` },
    ])
    mockApi(base({
      '/api/parts/7': { ...GPU, offers, compat: { compatible: true, warnings: ['Fonte recomendada: 550 W.'] } },
      '/api/parts/7/history?days=90': hist,
    }))
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'RTX 4060' })).toBeInTheDocument()
    const links = screen.getAllByRole('link', { name: /ver na/i })
    expect(links).toHaveLength(2)
    links.forEach((a) => expect(a.getAttribute('rel')).toContain('noopener'))
    expect(await screen.findByRole('img', { name: /histórico de preço/i })).toBeInTheDocument()
    expect(screen.getByText('Fonte recomendada: 550 W.')).toBeInTheDocument()
  })

  it('peça que não existe mostra erro', async () => {
    goto('#/pecas/999')
    mockApi(base({ '/api/parts/999': new Response(JSON.stringify({ detail: 'peça não encontrada' }), { status: 404 }) }))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('peça não encontrada')
  })
})

describe('Builds', () => {
  it('build completa: total, peças e troca', async () => {
    goto('#/builds/completa')
    const calls = mockApi(base({
      '/api/builds': [FULL, UPG],
      '/api/builds/1/options/cpu': [
        { ...CPU, compat: { compatible: true, warnings: [] } },
        { ...CPU, id: 3, model: 'Ryzen 5 7600', best: best(109900), compat: { compatible: false, warnings: ['CPU AM5 não encaixa na placa AM4.'] } },
      ],
      '/api/builds/1/items/cpu': FULL,
    }))
    render(<App />)
    expect(await screen.findByText('AMD Ryzen 5 5600')).toBeInTheDocument()
    expect(screen.getByText(/2 de 2 peças/)).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: 'Trocar' })[0])
    const dialog = await screen.findByRole('dialog', { name: /trocar processador/i })
    expect(await within(dialog).findByText('CPU AM5 não encaixa na placa AM4.')).toBeInTheDocument()
    await act(async () => { fireEvent.click(within(dialog).getByText('Ryzen 5 7600')) })
    await waitFor(() => expect(calls).toContainEqual(['/api/builds/1/items/cpu', 'PUT']))
  })

  it('build completa vazia é montada sozinha (a mais barata)', async () => {
    goto('#/builds/completa')
    let auto = false
    const vazia = { ...FULL, total_cash: 0, missing: ['cpu', 'gpu'], items: [item('cpu', null), item('gpu', null)] }
    const calls = mockApi(base({
      '/api/builds': () => [auto ? FULL : vazia, UPG],
      '/api/builds/1/auto': () => { auto = true; return FULL },
    }))
    render(<App />)
    await waitFor(() => expect(calls).toContainEqual(['/api/builds/1/auto', 'POST']))
    expect(await screen.findByText('AMD Ryzen 5 5600')).toBeInTheDocument()
  })

  it('upgrades: sem botão de montar e mostra o PC atual', async () => {
    goto('#/builds/upgrades')
    mockApi(base({ '/api/builds': [FULL, UPG] }))
    render(<App />)
    expect(await screen.findByText('Sem upgrade aqui.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /montar a mais barata/i })).toBeNull()
    expect(await screen.findByText(/Seu PC: Ryzen 5 5600 · B450 TOMAHAWK MAX · RTX 3060 · 16 GB DDR4/)).toBeInTheDocument()
  })
})

describe('segurança dos links', () => {
  it('link javascript: vindo do banco não vira link', async () => {
    mockApi(base({ '/api/deals': [{ ...DEAL, url: 'javascript:alert(1)' }] }))
    render(<App />)
    await screen.findByText('RTX 4060')
    expect(screen.queryByRole('link', { name: /ver na/i })).toBeNull()
  })

  it('todo link externo renderizado tem noopener', async () => {
    goto('#/pecas')
    mockApi(base({ '/api/parts*': [CPU, GPU] }))
    render(<App />)
    await screen.findByText('Ryzen 5 5600')
    const externos = screen.getAllByRole('link').filter((a) => a.getAttribute('target') === '_blank')
    expect(externos.length).toBeGreaterThan(0)
    externos.forEach((a) => expect(a.getAttribute('rel')).toMatch(/noopener/))
  })
})


describe('usado, vendedor e lojas de fora', () => {
  it('promoção de usado mostra a etiqueta', async () => {
    mockApi(base({ '/api/deals': [{ ...DEAL, condition: 'used' }] }))
    render(<App />)
    expect(await screen.findByText('usado')).toBeInTheDocument()
  })

  it('novo não tem etiqueta de usado', async () => {
    mockApi(base({ '/api/deals': [{ ...DEAL, condition: 'new' }] }))
    render(<App />)
    await screen.findByText('RTX 4060')
    expect(screen.queryByText('usado')).toBeNull()
  })

  it('mostra quais lojas são coletadas e quais estão de fora', async () => {
    goto('#/pecas')
    mockApi(base({ '/api/parts*': [CPU] }))
    render(<App />)
    expect(await screen.findByText('KaBuM!, Amazon')).toBeInTheDocument()
    const fora = screen.getByText(/^Pichau/)
    expect(fora).toHaveAttribute('title', 'bloqueia robô (HTTP 403)')
    expect(screen.getByText(/Mercado Livre/)).toBeInTheDocument()
  })

  it('detalhe mostra vendedor de terceiro e usado', async () => {
    goto('#/pecas/7')
    const offers = [{ ...best(150000, 'terabyte', 'Terabyte'), condition: 'used', seller: 'Terabyte', title: 'RTX 4060 Open Box', deal: { status: 'normal' } },
      { ...best(189990, 'kabum', 'KaBuM!'), listing_id: 2, condition: 'new', seller: 'ASUS', deal: { status: 'normal' } }]
    mockApi(base({ '/api/parts/7': { ...GPU, offers, compat: { compatible: true, warnings: [] } }, '/api/parts/7/history?days=90': [] }))
    render(<App />)
    expect(await screen.findByText('RTX 4060 Open Box')).toBeInTheDocument()
    expect(screen.getByText(/vendido por ASUS/)).toBeInTheDocument()
    expect(screen.getAllByText('usado')).toHaveLength(1)
  })
})

// ------------------------------------------------------------------ canais do Telegram
const TG_META = {
  kinds: [{ value: 'peca:gpu', n: 1 }, { value: 'audio', n: 1 }], stores: [], total: 2, last_round: '2026-10-12T18:00:00',
  channels: [{ slug: 'gpcrpromo', active: 1, fail_count: 0 }, { slug: 'lipeofertas', active: 1, fail_count: 3, last_error: 'fora do ar' }],
}
const TG_GPU = {
  id: 1, channel: 'gpcrpromo', msg_id: 10, posted_at: '2026-10-12T17:00:00', title: 'Placa de Vídeo RTX 5060 8GB',
  price_cash: 256400, store: 'mercadolivre', link: 'https://t.me/gpcrpromo/10', kind: 'peca:gpu', kind_agree: 3,
  product_key: 'gpu|rtx 5060|8gb', ref: { n: 5, min: 269999, median: 279999 }, deal: 'menor_ja_visto', pct: 8,
}
const TG_FONE = {
  id: 2, channel: 'gpcrpromo', msg_id: 11, posted_at: '2026-10-12T17:30:00', title: 'Fone JBL Tune 520',
  price_cash: 19900, store: 'amazon', link: 'javascript:alert(1)', kind: 'audio', kind_agree: 2,
  product_key: null, ref: null, deal: null, pct: null,
}

describe('Canais', () => {
  it('lista ofertas com tipo, selo de promoção, loja e link seguro', async () => {
    goto('#/canais')
    mockApi(base({ '/api/tg/meta': TG_META, '/api/tg/offers*': [TG_GPU, TG_FONE] }))
    render(<App />)
    expect(await screen.findByText('Placa de Vídeo RTX 5060 8GB')).toBeInTheDocument()
    expect(screen.getByText('menor preço já visto')).toBeInTheDocument()
    expect(screen.getByText('Placa de vídeo')).toBeInTheDocument()
    expect(screen.getByText('2/3')).toBeInTheDocument()                    // fone: só 2 modelos concordaram
    const links = screen.getAllByRole('link', { name: /ver no canal/ })
    expect(links).toHaveLength(1)                                           // javascript: não vira link
    expect(links[0]).toHaveAttribute('href', 'https://t.me/gpcrpromo/10')
    expect(screen.getByText(/com problema: lipeofertas/)).toBeInTheDocument()
  })

  it('filtro de tipo e "só promoção" vão pra API', async () => {
    goto('#/canais')
    const calls = mockApi(base({ '/api/tg/meta': TG_META, '/api/tg/offers*': [] }))
    render(<App />)
    await screen.findByText('Nada com esse filtro.')
    fireEvent.click(screen.getByRole('tab', { name: 'Áudio' }))
    await waitFor(() => expect(calls.some(([u]) => u.includes('kind=audio'))).toBe(true))
    fireEvent.click(screen.getByRole('checkbox'))
    await waitFor(() => expect(calls.some(([u]) => u.includes('only_deals=true'))).toBe(true))
    expect(await screen.findByText('Nenhuma promoção de verdade nesse período.')).toBeInTheDocument()
  })

  it('Canais pede pra API sem peça de PC e não tem aba de peças', async () => {
    goto('#/canais')
    const calls = mockApi(base({ '/api/tg/meta': TG_META, '/api/tg/offers*': [TG_FONE] }))
    render(<App />)
    await screen.findByText('Fone JBL Tune 520')
    expect(calls.some(([u]) => u.startsWith('/api/tg/offers') && u.includes('no_parts=true'))).toBe(true)
    expect(screen.queryByRole('tab', { name: 'Peças de PC' })).toBeNull()
  })
})

describe('Fotos das ofertas dos canais', () => {
  it('linha da aba Canais mostra a miniatura quando tem foto, e nada quando não tem', async () => {
    goto('#/canais')
    mockApi(base({ '/api/tg/meta': TG_META, '/api/tg/offers*': [
      { ...TG_GPU, image: '/api/tg/img/gpcrpromo_10.jpg' }, { ...TG_FONE, image: null }] }))
    render(<App />)
    const row = (await screen.findByText('Placa de Vídeo RTX 5060 8GB')).closest('li')
    expect(row.querySelector('img')).toHaveAttribute('src', '/api/tg/img/gpcrpromo_10.jpg')
    expect(screen.getByText('Fone JBL Tune 520').closest('li').querySelector('img')).toBeNull()
  })

  it('cartão da peça de canal usa a foto local; foto quebrada cai no ícone', async () => {
    goto('#/pecas')
    const canal = { ...best(9100, 'canal', 'Canais do Telegram'), url: 'https://t.me/gpcrpromo/10' }
    mockApi(base({ '/api/parts*': [{ ...CPU, id: 50, category: 'case', brand: 'Aigo', model: 'Apollo A275', source: 'canal',
      specs: {}, best: canal, image_url: '/api/tg/img/gpcrpromo_9.jpg' }] }))
    render(<App />)
    const card = (await screen.findByText('Apollo A275')).closest('article')
    const img = card.querySelector('img')
    expect(img).toHaveAttribute('src', '/api/tg/img/gpcrpromo_9.jpg')
    fireEvent.error(img)
    expect(card.querySelector('img')).toBeNull()
  })
})

describe('Peças dos canais junto com as das lojas', () => {
  const canal = (cents) => ({ ...best(cents, 'canal', 'Canais do Telegram'), url: 'https://t.me/gpcrpromo/10', seller: 'Shopee via @gpcrpromo' })
  const SO_CANAL = { ...CPU, id: 50, category: 'case', brand: 'Aigo', model: 'Apollo A275', source: 'canal', specs: {}, best: canal(9100) }

  it('peça do canal aparece no meio das outras, com cartão azul e "Ver no canal"', async () => {
    goto('#/pecas')
    mockApi(base({ '/api/parts*': [{ ...CPU, source: 'loja' }, SO_CANAL] }))
    render(<App />)
    const card = (await screen.findByText('Apollo A275')).closest('article')
    expect(card.className).toContain('is-tg')
    expect(within(card).getByText(/Shopee via @gpcrpromo/)).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: /Ver no canal/ })).toHaveAttribute('href', 'https://t.me/gpcrpromo/10')
    const loja = screen.getByText('Ryzen 5 5600').closest('article')
    expect(loja.className).not.toContain('is-tg')
  })

  it('peça da loja com o canal mais barato também fica azul', async () => {
    goto('#/pecas')
    mockApi(base({ '/api/parts*': [{ ...GPU, source: 'loja', best: canal(256400) }] }))
    render(<App />)
    const card = (await screen.findByText('RTX 4060')).closest('article')
    expect(card.className).toContain('is-tg')
  })

  it('não existe mais a seção separada', async () => {
    goto('#/pecas')
    const calls = mockApi(base({ '/api/parts*': [SO_CANAL] }))
    render(<App />)
    await screen.findByText('Apollo A275')
    expect(screen.queryByText('Vistas nos canais')).toBeNull()
    expect(calls.some(([u]) => u.startsWith('/api/tg/parts'))).toBe(false)
  })
})

describe('Peça sem estoque', () => {
  it('mostra o último preço apagado com selo, sem link de compra', async () => {
    goto('#/pecas')
    const semEstoque = { ...CPU, id: 9, model: 'WD Blue 2TB HD', category: 'storage', best: null,
      out_of_stock: { ...best(37690, 'terabyte', 'Terabyte'), in_stock: 0 } }
    mockApi(base({ '/api/parts*': [semEstoque], '/api/tg/parts*': [] }))
    render(<App />)
    const card = (await screen.findByText('WD Blue 2TB HD')).closest('article')
    expect(within(card).getByText('sem estoque')).toBeInTheDocument()
    expect(within(card).getByText(/376,90/)).toBeInTheDocument()
    expect(within(card).queryByRole('link')).toBeNull()
    expect(card.className).toContain('is-out')
  })
})
