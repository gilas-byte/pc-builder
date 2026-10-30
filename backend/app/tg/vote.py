"""Tipo da oferta por votação de 1 a 3 modelos locais (Ollama). Prompts validados em testes manuais com os 3 modelos padrão
(unânime em 84% dos posts, com 98,4% de acerto).

Regra com 3 modelos: 3 iguais → aceita; 2 iguais → aceita, mas `agree=2`; tudo diferente → 'duvidoso'.
Com 2: concordam ou 'duvidoso'. Com 1: ele decide sozinho. Quem fala HTTP com o Ollama é app/ollama.py.
A IA só diz o TIPO. Preço e "mesmo produto" nunca passam por ela.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Callable

OLLAMA = "http://127.0.0.1:11434"
MODELS = ("qwen2.5:3b", "llama3.2:3b", "gemma3:4b")

TECH_KINDS = ["peca:cpu", "peca:gpu", "peca:motherboard", "peca:ram", "peca:storage", "peca:psu", "peca:case",
              "peca:cooler", "monitor", "notebook", "periferico", "audio", "console_jogo", "celular_tablet",
              "tv_streaming", "outro_tech"]
NOT_TECH, COUPON, DOUBT = "nao_tech", "cupom", "duvidoso"

GATE = """Você filtra anúncios de promoção. Pergunta: o produto é um ELETRÔNICO / produto de TECNOLOGIA?

SIM: computador e peças, notebook, monitor, celular, tablet, smartwatch, TV, console, jogo de videogame,
controle, fone, caixa de som, Alexa/Echo, mouse, teclado, webcam, cabo, carregador, power bank, roteador,
Starlink, câmera de segurança, projetor, suporte de monitor, pasta térmica, capa de notebook.

NÃO: comida, bebida, roupa, calçado, beleza, higiene, fralda, remédio, suplemento, pet, brinquedo, livro,
móvel, cadeira, mochila, panela, louça, utensílio de cozinha, garrafa/cuia térmica, eletrodoméstico
(geladeira, lava e seca, air fryer, fritadeira, liquidificador, mixer, chaleira, sorveteira, cafeteira,
ar-condicionado, ventilador, ferro de passar, aspirador), ferramenta (roçadeira, furadeira, lavadora de alta
pressão), jardim, pilha, produto de limpeza, carro.
Atenção: ter "Inverter", "Smart", "Wi-Fi", "AI", bateria ou ser elétrico NÃO torna eletrodoméstico ou ferramenta
em tecnologia. Ar-condicionado é sempre NÃO.

Jogo de videogame (PS5, Switch, Xbox, "Franquia Mortal Kombat") é SIM.
Anúncio só de cupom/código de desconto, sem produto (ex.: "Cupom Mercado Livre", "15% OFF acima de R$ 79"):
responda "cupom". Produto com nome é sempre "sim" ou "nao", nunca "cupom".

Responda SOMENTE o JSON {"resposta": "sim"} ou {"resposta": "nao"} ou {"resposta": "cupom"}."""

KIND = """Você classifica anúncios de produtos de tecnologia em português. Responda SOMENTE com JSON {"tipo": "<um dos tipos>"}.

Tipos:
- peca:cpu = processador AVULSO (Ryzen, Core i5...) vendido sozinho
- peca:gpu = placa de vídeo AVULSA (RTX, RX, GeForce...)
- peca:motherboard = placa-mãe
- peca:ram = pente de memória RAM avulso (DDR4/DDR5), inclusive de notebook
- peca:storage = SSD ou HD INTERNO (NVMe, M.2, SATA)
- peca:psu = fonte de alimentação de PC (com watts, 80 Plus)
- peca:case = gabinete
- peca:cooler = cooler de processador, water cooler ou ventoinha/fan de gabinete
- monitor = monitor de computador (não TV, não suporte de monitor)
- notebook = notebook/laptop/MacBook, inclusive quando o texto só cita o modelo (IdeaPad, Vivobook, TUF F16, Nitro V, LOQ, Slim 3, HP 200, Positivo Vision, Galaxy Book...)
- periferico = mouse, teclado, mousepad, webcam, volante gamer
- audio = fone, headset, headphone, AirPods, earbuds, caixa de som, Echo/Alexa (headset NÃO é periférico)
- console_jogo = console, jogo, controle de console, Nintendo/PlayStation/Xbox
- celular_tablet = celular, tablet, smartwatch
- tv_streaming = TV, Roku, Fire Stick, Chromecast
- outro_tech = outro eletrônico/acessório de tecnologia: cabo, carregador, power bank, suporte de monitor, projetor, câmera, roteador, Starlink, pasta térmica (NÃO é cooler), capa de notebook

Regras importantes:
1. Notebook que cita processador, placa de vídeo, RAM ou SSD continua sendo "notebook" (é o produto inteiro, não a peça).
2. Peça só é peça se for vendida AVULSA. "Processador" em liquidificador, celular ou TV NÃO é peça.
3. SSD/RAM anunciado "pra notebook/PS5" continua peca:storage / peca:ram.
4. Suporte, braço ou cabo para monitor é outro_tech, não monitor.
5. Controle de videogame é console_jogo; volante gamer é periferico.

Exemplos:
"ASUS ROG Strix G16 Intel Core i9 - RTX 5060 8GB" -> notebook
"Lenovo Slim 3 com Ryzen 7 7735HS - 16GB RAM DDR5 - 512GB SSD" -> notebook
"Placa de Vídeo PELADN RTX 5060, 8GB, GDDR7" -> peca:gpu
"UPGRADE PRA NOTEBOOK, PC e PS5 Kingston NV3 1TB M.2 NVMe" -> peca:storage
"Kit Ventoinha Pichau Ventus NX, ARGB, 5x120mm" -> peca:cooler
"Suporte Articulado Para Monitor Zinnia Nimbo 110" -> outro_tech
"Smart TV Hisense 50 com Processador AI" -> tv_streaming
"Controle Sony Dualsense Sem Fio PS5" -> console_jogo"""

Chat = Callable[[str, str, str, dict], str]   # (modelo, system, user, schema) -> conteúdo JSON


class OllamaDown(RuntimeError):
    """O Ollama não respondeu (conexão recusada, tempo esgotado, erro do servidor)."""


def _enum(key, values):
    return {"type": "object", "properties": {key: {"type": "string", "enum": values}}, "required": [key]}


def one_model(chat: Chat, model: str, title: str) -> str:
    g = json.loads(chat(model, GATE, f"Anúncio: {title}", _enum("resposta", ["sim", "nao", "cupom"])))["resposta"]
    if g == "nao":
        return NOT_TECH
    if g == "cupom":
        return COUPON
    return json.loads(chat(model, KIND, f"Anúncio: {title}", _enum("tipo", TECH_KINDS)))["tipo"]


def quorum(n_models: int) -> int:
    """Quantos votos iguais decidem: 1 modelo decide sozinho; 2 têm de concordar; 3 = maioria (2), como sempre."""
    return 1 if n_models == 1 else 2


def vote(titles: list[str], chat: Chat, models=MODELS,
         unload_fn: Callable[[str], None] | None = None) -> list[tuple[str, int, dict]]:
    """Classifica vários títulos com 1 a 3 modelos. Modelo por modelo: cada um carrega na placa uma vez só e sai
    em seguida (`unload_fn`, keep_alive 0; os 3 juntos não cabem em 8 GB e o último cairia pra CPU).
    Devolve (tipo, quantos concordam, votos) por título; sem quórum, 'duvidoso'."""
    models = list(models)
    if not models:
        raise ValueError("escolha de 1 a 3 modelos")
    need = quorum(len(models))
    votes = [{} for _ in titles]
    for m in models:
        try:
            for i, t in enumerate(titles):
                try:
                    votes[i][m] = one_model(chat, m, t)
                except (ValueError, KeyError):            # resposta fora do formato: voto perdido
                    votes[i][m] = "erro"
        finally:
            if unload_fn is not None:
                unload_fn(m)
    out = []
    for v in votes:
        top, n = Counter(x for x in v.values() if x != "erro").most_common(1)[0] if any(
            x != "erro" for x in v.values()) else (DOUBT, 0)
        out.append((top if n >= need else DOUBT, n, v))
    return out
