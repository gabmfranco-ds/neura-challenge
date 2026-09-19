"""Constrói a chamada de cada caso: alvo "prompt" (NeuraLake direto) ou "http"
(servidor do projeto em `NEURA_BASE_URL`, padrão `http://127.0.0.1:8787`).

Os prompts de sistema e de usuário são cópias adaptadas dos arquivos reais do
outro agente (repo `neura-challenge`, branch `v1`, lidos em 19/09/2026). Cada
função abaixo diz de qual arquivo veio. Fichas reduzidas (só os campos que o
prompt de sistema usa) ficam em `FICHAS`, copiadas de `agentes/catalogo.py`.
"""
from __future__ import annotations

import json

import httpx

from evals import config, dados_base

# ------------------------------------------------------------- fichas-stub
# Copiadas de agentes/catalogo.py::FICHAS_FIXAS (19/09/2026), só os campos
# que agentes/comum.py::sistema() usa para montar o prompt de sistema.

FICHAS = {
    "buyer": {
        "name": "Porta Aberta",
        "description": "Agente do comprador. Transforma a frase em pedido estruturado e "
                       "negocia pelo comprador dentro do mandato recebido, sem voltar a "
                       "pedir aprovação a cada rodada.",
        "estrategia": "Assume o que falta na frase e declara a suposição. Na negociação, "
                      "começa abaixo do anúncio e sobe devagar, nunca passando do teto.",
    },
    "property_boa": {
        "name": "Casa Verificada",
        "description": "Busca imóveis e confere cada candidato antes de indicar: abre os "
                       "documentos (matrícula, certidões, IPTU, condomínio) e confere a "
                       "disponibilidade na base.",
        "estrategia": "Só indica imóvel com documentação lida e disponibilidade conferida. "
                      "Custa mais e demora mais.",
        "acesso_a_dados": "anuncio + disponibilidade + texto dos documentos",
    },
    "property_barata": {
        "name": "Busca Relâmpago",
        "description": "Busca imóveis rápido e barato. ESTRATÉGIA DECLARADA: trabalha só "
                       "com o texto do anúncio. NÃO abre documentos e NÃO confere a "
                       "disponibilidade na base.",
        "estrategia": "Velocidade e preço acima de conferência. O que o anúncio diz é o "
                      "que vai na resposta. Quem contratar sabe que está comprando isso.",
        "acesso_a_dados": "somente o anuncio (sem disponibilidade, sem documentos)",
    },
    "seller": {
        "name": "Vendedor (agente do imóvel em teste)",
        "description": "Agente do vendedor. Negocia em nome do proprietário e tem piso de "
                       "preço e pressa próprios, que não revela.",
        "estrategia": "Defende o piso do proprietário. Aceita, contrapropõe ou rejeita.",
    },
    "orchestrator": {
        "name": "Orquestrador",
        "description": "Contrata agentes no marketplace para atender o comprador.",
        "estrategia": "Paga pelo que for provado. Sem histórico, testa e verifica. "
                      "Reprovou, retém, publica o recibo e contrata outro.",
    },
}


def sistema(ficha: dict, extra: str = "") -> dict:
    """Cópia de agentes/comum.py::sistema (19/09/2026)."""
    linhas = [
        f"Você é o agente \"{ficha['name']}\" de um marketplace de agentes de imóveis no Brasil.",
        f"Descrição da sua ficha pública: {ficha['description']}",
        f"Estratégia que você declarou no marketplace: {ficha.get('estrategia', '')}",
        "Você trabalha em português do Brasil. Nunca use travessão.",
        "Você responde SOMENTE com o JSON pedido, sem crase, sem markdown, sem texto em volta.",
        "Cumpra a sua estratégia declarada. Quem te contratou pagou por ela.",
    ]
    if extra:
        linhas.append(extra)
    return {"role": "system", "content": "\n".join(linhas)}


def _dinheiro(v) -> str:
    if v is None:
        return "-"
    return f"R$ {v:,.0f}".replace(",", ".")


PEDIDO_EXEMPLO = {
    "tipo": "apartamento", "cidade": "São Paulo", "bairros": ["Pinheiros", "Vila Madalena"],
    "preco_max": 2000000, "quartos_min": 3, "vagas_min": 2, "area_min": 120,
    "objetivo": "moradia", "financiamento": True,
}


# ---------------------------------------------------------------- builders
# alvo="prompt": cada builder devolve (mensagens, max_tokens, temperature)

def build_buyer_extracao(entrada: dict) -> tuple[list[dict], int, float]:
    """Adaptado de agentes/buyer/agente.py::_entender (19/09/2026)."""
    frase = (entrada.get("frase") or "").strip()
    mensagens = [
        sistema(FICHAS["buyer"]),
        {"role": "user", "content": (
            "Transforme a frase do comprador abaixo em um pedido estruturado de imóvel.\n\n"
            f"FRASE: {frase}\n\n"
            "Responda com este JSON exato (sem nada em volta):\n"
            '{"pedido": ' + json.dumps(PEDIDO_EXEMPLO, ensure_ascii=False) + ', '
            '"suposicoes": ["o que você assumiu porque a frase não disse"]}\n\n'
            "Regras: valores em reais, números sem ponto nem texto. `bairros` é lista; se a "
            "frase não citar bairro, devolva lista vazia. `tipo` é um de: apartamento, "
            "cobertura, casa. `objetivo` é moradia ou investimento. Só assuma o que for "
            "razoável e escreva cada suposição em `suposicoes`."
        )},
    ]
    return mensagens, 700, 0.3


def prompt_lado_comprador(mandato: dict, imovel: dict, historico: list, rodada: int,
                          max_rodadas: int) -> list[dict]:
    """AUTORAL, não copiado do sistema (regra nova do dono, 19/09/2026): o
    prompt real na branch `v1` está sendo reescrito agora mesmo (porte para
    Agno). Ver `evals/prompts/negociacao.md` para o texto completo e a nota
    de que isto precisa ser resincronizado com o prompt real quando o porte
    terminar.

    Regra: o comprador dá uma FAIXA (`oferta_min`, `teto_preco`). O Buyer
    Agent aposta no mínimo (primeira oferta = oferta_min exato), sobe aos
    poucos, nunca passa do teto, e NUNCA revela oferta_min nem teto_preco
    na mensagem para o vendedor.
    """
    oferta_min = mandato.get("oferta_min")
    teto = mandato.get("teto_preco")
    linhas_historico = "\n".join(
        f"  rodada {h.get('rodada')}: {h.get('de')} -> {h.get('acao')} "
        f"{_dinheiro(h.get('valor'))}: {h.get('mensagem', '')[:160]}"
        for h in historico) or "  (nenhuma ainda, esta é a primeira oferta)"
    minha_ultima = max([h.get("valor") or 0 for h in historico
                        if h.get("acao") in ("oferta", "aceitar")] or [0])
    contrapropostas = [h.get("valor") for h in historico
                       if h.get("acao") == "contraproposta" and h.get("valor")]
    ultima_do_vendedor = contrapropostas[-1] if contrapropostas else None
    ultima_rodada = rodada >= max_rodadas

    situacao = []
    if not historico:
        situacao.append(f"Esta é a PRIMEIRA oferta: ela tem que ser EXATAMENTE "
                        f"{_dinheiro(oferta_min)}, nem um real a mais.")
    if ultima_do_vendedor:
        cabe = ultima_do_vendedor <= (teto or 0)
        situacao.append(f"A última contraproposta do vendedor foi {_dinheiro(ultima_do_vendedor)} e ela "
                        + ("CABE no seu teto." if cabe else "NÃO cabe no seu teto."))
        if cabe:
            situacao.append("Aceitar agora garante o imóvel. Insistir pode perder o negócio.")
    if minha_ultima:
        situacao.append(f"A sua maior oferta até agora foi {_dinheiro(minha_ultima)}. Nunca "
                        f"ofereça menos do que isso: baixar oferta quebra a negociação.")
    if ultima_rodada:
        situacao.append(f"ESTA É A ÚLTIMA das {max_rodadas} rodadas permitidas. Sem acordo "
                        f"agora, o negócio morre (rejeitado).")

    return [
        sistema(FICHAS["buyer"], "Você negocia pelo comprador dentro de uma FAIXA que ele deu "
                                 "de uma vez só: oferta_min e teto_preco. Os dois números da "
                                 "faixa são segredo seu: NUNCA escreva oferta_min nem teto_preco "
                                 "na mensagem para o vendedor, em nenhum formato (nem por "
                                 "extenso, nem abreviado)."),
        {"role": "user", "content": (
            f"Imóvel em negociação:\n{json.dumps(imovel, ensure_ascii=False, indent=2)}\n\n"
            f"Sua faixa (segredo seu, nunca revele nenhum dos dois números ao vendedor): "
            f"oferta_min {_dinheiro(oferta_min)}, teto_preco {_dinheiro(teto)}. "
            f"Prazo de {mandato.get('prazo_dias', 60)} dias.\n"
            f"Rodada {rodada} de no máximo {max_rodadas}.\n"
            f"Histórico da negociação:\n{linhas_historico}\n\n"
            + ("\n".join(situacao) + "\n\n" if situacao else "")
            + "Decida a próxima jogada e responda SÓ com este JSON:\n"
            '{"acao":"oferta|aceitar|desistir","valor":0,"mensagem":"uma ou duas frases para '
            'o agente do vendedor, SEM revelar oferta_min nem teto_preco","motivo":"por que '
            'essa jogada, em uma frase"}\n\n'
            "Regras duras:\n"
            "1. Primeira oferta (histórico vazio): `valor` é EXATAMENTE oferta_min.\n"
            "2. `valor` é número inteiro em reais e NUNCA passa do teto_preco.\n"
            "3. Uma nova `oferta` tem que ser MAIOR OU IGUAL à sua oferta anterior (nunca cai).\n"
            "4. Se a contraproposta do vendedor couber no teto, `aceitar` com `valor` igual "
            "ao valor dele é a jogada certa, ainda mais na última rodada.\n"
            "5. Só use `desistir` quando nada na mesa couber no teto, na última rodada.\n"
            "6. Na `mensagem`, nunca escreva o número de oferta_min nem de teto_preco: nem "
            "cru, nem com ponto de milhar, nem abreviado (\"1,8 mi\", \"1.8 milhão\")."
        )},
    ]


def build_buyer_negociacao(entrada: dict) -> tuple[list[dict], int, float]:
    mandato = entrada.get("mandato") or {}
    imovel = entrada.get("imovel") or {}
    historico = entrada.get("historico") or []
    rodada = int(entrada.get("rodada") or 1)
    max_rodadas = int(entrada.get("max_rodadas") or 3)
    return prompt_lado_comprador(mandato, imovel, historico, rodada, max_rodadas), 600, 0.5


def prompt_lado_vendedor(piso: int, pedido: int, pressa: float, motivo_venda: str,
                         imovel_desc: dict, oferta, mensagem_comprador: str,
                         historico: list, rodada: int, max_rodadas: int) -> list[dict]:
    """AUTORAL, não copiado do sistema (regra nova do dono, 19/09/2026). Ver
    `prompt_lado_comprador` acima e `evals/prompts/negociacao.md`.

    Regra: o vendedor tem piso (mínimo) e preço PEDIDO (máximo, o que ele
    anuncia). Defende o pedido, cede aos poucos, nunca fecha abaixo do
    piso, e NUNCA revela o piso na mensagem para o comprador.
    """
    linhas_historico = "\n".join(
        f"  rodada {h.get('rodada')}: {h.get('de')} -> {h.get('acao')} "
        f"{_dinheiro(h.get('valor'))}: {h.get('mensagem', '')[:160]}"
        for h in historico) or "  (nenhuma ainda)"
    grau_pressa = ("muita pressa, quer fechar rápido e aceita ceder mais"
                   if pressa >= 0.7 else
                   "pressa média, cede aos poucos mas não regala"
                   if pressa >= 0.4 else
                   "sem pressa nenhuma, prefere esperar comprador melhor")
    ultima_rodada = rodada >= max_rodadas

    situacao = []
    if ultima_rodada:
        situacao.append(f"ESTA É A ÚLTIMA das {max_rodadas} rodadas. Sem acordo agora, o "
                        f"negócio morre (rejeitado).")

    return [
        sistema(FICHAS["seller"], "Você fala pelo proprietário. Você tem piso (mínimo) e o "
                                  "preço pedido (máximo, o que está no anúncio). O piso é "
                                  "segredo seu: NUNCA escreva o número do piso na mensagem "
                                  "para o comprador, em nenhum formato."),
        {"role": "user", "content": (
            f"Imóvel: {imovel_desc.get('tipo')} em {imovel_desc.get('bairro')}, "
            f"{imovel_desc.get('area')} m2, {imovel_desc.get('quartos')} quartos, "
            f"{imovel_desc.get('vagas')} vagas.\n"
            f"Preço pedido (máximo, o que está no anúncio): {_dinheiro(pedido)}.\n"
            f"Piso do proprietário (segredo seu, mínimo que aceita): {_dinheiro(piso)}.\n"
            f"Situação do proprietário: {motivo_venda or 'não informado'}. "
            f"Nível de pressa: {grau_pressa}.\n\n"
            f"Rodada {rodada} de no máximo {max_rodadas}.\n"
            f"Histórico:\n{linhas_historico}\n\n"
            + ("\n".join(situacao) + "\n\n" if situacao else "")
            + f"O agente do comprador ofereceu {_dinheiro(oferta)} e disse: "
            f"\"{mensagem_comprador or ''}\"\n\n"
            "Responda SÓ com este JSON:\n"
            '{"acao":"aceita|contraproposta|rejeita","valor":0,"mensagem":"uma ou duas frases '
            'para o agente do comprador, SEM revelar o piso","motivo":"por que, em uma frase"}\n\n'
            "Regras duras:\n"
            "1. `valor` é número inteiro em reais. Em `aceita`, repita o valor ofertado.\n"
            "2. Em `contraproposta`, o valor tem que ser MENOR OU IGUAL à sua contraproposta "
            "anterior (você cede, nunca sobe de novo) e NUNCA menor que o piso.\n"
            "3. Nunca `aceita` um valor abaixo do piso.\n"
            "4. Em `rejeita`, use o preço pedido.\n"
            "5. Quanto mais pressa, mais perto do piso você pode ceder. Na última rodada, "
            "feche dentro do piso ou perca o comprador.\n"
            "6. Na `mensagem`, nunca escreva o número do piso: nem cru, nem com ponto de "
            "milhar, nem abreviado."
        )},
    ]


def build_seller_negociacao(entrada: dict) -> tuple[list[dict], int, float]:
    piso = int(entrada.get("piso") or 0)
    pedido = int(entrada.get("pedido") or entrada.get("anuncio") or piso)
    pressa = float(entrada.get("pressa") or 0.5)
    oferta = entrada.get("oferta")
    rodada = int(entrada.get("rodada") or 1)
    max_rodadas = int(entrada.get("max_rodadas") or 3)
    historico = entrada.get("historico") or []
    imovel_desc = entrada.get("imovel_desc") or {
        "tipo": "apartamento", "bairro": "Pinheiros", "area": 100, "quartos": 3, "vagas": 2,
    }
    mensagens = prompt_lado_vendedor(piso, pedido, pressa, entrada.get("motivo_venda", ""),
                                     imovel_desc, oferta, entrada.get("mensagem", ""),
                                     historico, rodada, max_rodadas)
    return mensagens, 600, 0.5


# ---------------------------------------------------- negociação completa (A2A simulada)

async def simular_negociacao_completa(entrada: dict, capacidade: str, api_key: str) -> dict:
    """Simula a conversa INTEIRA entre Buyer Agent e Seller Agent, alternando
    os dois prompts por até `max_rodadas` (regra nova do dono, 19/09/2026:
    no máximo 3 rodadas A2A; sem acordo dentro do limite = OFFER_REJECTED).

    Não existe no sistema real como uma única chamada -- é o avaliador que
    orquestra as N chamadas de ida e volta, porque queremos medir o
    RESULTADO da negociação (chegou a acordo? em que preço? violou alguma
    regra no caminho?), não só uma jogada isolada.
    """
    from evals import neuralake_client  # import local: evita ciclo em tempo de import

    comprador = entrada["comprador"]  # {"oferta_min", "teto_preco", "prazo_dias"}
    vendedor = entrada["vendedor"]    # {"piso", "pedido", "pressa", "motivo_venda"}
    imovel = entrada.get("imovel") or {
        "tipo": "apartamento", "bairro": "Pinheiros", "area": 100, "quartos": 3, "vagas": 2,
    }
    max_rodadas = int(entrada.get("max_rodadas") or 3)

    historico: list[dict] = []
    custo_total = 0.0
    tokens_in_total = 0
    tokens_out_total = 0
    latencia_total = 0
    chamadas = 0
    erro_tipo = None
    acordo = False
    preco_final = None
    rodada_acordo = None

    for rodada in range(1, max_rodadas + 1):
        mensagens_c = prompt_lado_comprador(comprador, imovel, historico, rodada, max_rodadas)
        resultado_c = await neuralake_client.chamar(mensagens_c, capacidade=capacidade,
                                                    api_key=api_key, max_tokens=600, temperature=0.5)
        chamadas += 1
        custo_total += resultado_c.custo_usd or 0.0
        tokens_in_total += resultado_c.tokens_entrada or 0
        tokens_out_total += resultado_c.tokens_saida or 0
        latencia_total += resultado_c.latencia_ms
        if not resultado_c.ok:
            erro_tipo = erro_tipo or resultado_c.erro_tipo
            break
        bloco_c = neuralake_client.extrair_json(resultado_c.texto)
        jogada_c = None
        if bloco_c:
            try:
                jogada_c = json.loads(bloco_c)
            except json.JSONDecodeError:
                jogada_c = None
        if not isinstance(jogada_c, dict):
            erro_tipo = erro_tipo or "json_invalido"
            break
        historico.append({"rodada": rodada, "de": "comprador", **jogada_c})

        if jogada_c.get("acao") == "desistir":
            break
        if jogada_c.get("acao") == "aceitar":
            acordo = True
            preco_final = jogada_c.get("valor")
            rodada_acordo = rodada
            break

        mensagens_v = prompt_lado_vendedor(
            vendedor.get("piso"), vendedor.get("pedido"), vendedor.get("pressa", 0.5),
            vendedor.get("motivo_venda", ""), imovel, jogada_c.get("valor"),
            jogada_c.get("mensagem", ""), historico, rodada, max_rodadas)
        resultado_v = await neuralake_client.chamar(mensagens_v, capacidade=capacidade,
                                                    api_key=api_key, max_tokens=600, temperature=0.5)
        chamadas += 1
        custo_total += resultado_v.custo_usd or 0.0
        tokens_in_total += resultado_v.tokens_entrada or 0
        tokens_out_total += resultado_v.tokens_saida or 0
        latencia_total += resultado_v.latencia_ms
        if not resultado_v.ok:
            erro_tipo = erro_tipo or resultado_v.erro_tipo
            break
        bloco_v = neuralake_client.extrair_json(resultado_v.texto)
        jogada_v = None
        if bloco_v:
            try:
                jogada_v = json.loads(bloco_v)
            except json.JSONDecodeError:
                jogada_v = None
        if not isinstance(jogada_v, dict):
            erro_tipo = erro_tipo or "json_invalido"
            break
        historico.append({"rodada": rodada, "de": "vendedor", **jogada_v})

        if jogada_v.get("acao") == "aceita":
            acordo = True
            preco_final = jogada_v.get("valor")
            rodada_acordo = rodada
            break
        if jogada_v.get("acao") == "rejeita" and rodada == max_rodadas:
            break

    saida = {
        "acordo": acordo, "preco_final": preco_final, "rodada_acordo": rodada_acordo,
        "rodadas_rodadas": historico[-1]["rodada"] if historico else 0,
        "historico": historico, "chamadas": chamadas,
    }
    return {
        "saida": saida, "custo_usd": custo_total, "tokens_entrada": tokens_in_total,
        "tokens_saida": tokens_out_total, "latencia_ms": latencia_total,
        "erro_tipo": erro_tipo, "texto": json.dumps(saida, ensure_ascii=False),
        "modelo_usado": capacidade,
    }


MAX_CANDIDATOS_PROPERTY = 8


def build_property_busca(entrada: dict) -> tuple[list[dict], int, float]:
    """Adaptado de agentes/property/agente.py::executar (19/09/2026)."""
    pedido = entrada.get("pedido") or {}
    variante = entrada.get("variante") or "boa"
    quantidade = int(entrada.get("quantidade") or 4)
    evitar = set(entrada.get("evitar") or [])

    candidatos = [im for im in dados_base.imoveis()
                 if not dados_base.bate_com_filtros(im, pedido)
                 and im["property_id"] not in evitar][:MAX_CANDIDATOS_PROPERTY]

    ficha = FICHAS["property_boa"] if variante == "boa" else FICHAS["property_barata"]
    completo = variante == "boa"

    def visao_anuncio(im):
        campos = ("property_id", "tipo", "cidade", "bairro", "endereco", "preco", "area",
                  "quartos", "suites", "vagas", "andar", "condominio_mensal", "iptu_anual",
                  "ano_construcao", "aceita_financiamento", "caracteristicas", "seller_agent",
                  "texto_anuncio")
        return {c: im.get(c) for c in campos}

    def visao_completa(im):
        v = visao_anuncio(im)
        v["disponibilidade"] = im.get("disponibilidade")
        v["documentos"] = dados_base.documento(im["property_id"])
        return v

    visao = [visao_completa(c) if completo else visao_anuncio(c) for c in candidatos]

    instrucao_extra = (
        "Você abriu os documentos de cada candidato. Use o campo `documentos` para dizer o "
        "status de documentação: `basic_verified` quando matrícula, certidões, IPTU e "
        "condomínio estiverem limpos e dentro da validade; `pendencias` quando qualquer um "
        "deles tiver problema; `sem_documentos` quando não houver texto. Use o campo "
        "`disponibilidade` da base como está."
        if completo else
        "Você NÃO recebe documento nem campo de disponibilidade: a sua ficha diz que você "
        "trabalha com o anúncio. Preencha `disponibilidade` e `documentacao_status` com o "
        "que o anúncio te permite concluir. Valores possíveis: `available` ou `unavailable`; "
        "`basic_verified`, `pendencias` ou `sem_documentos`."
    )

    mensagens = [
        sistema(ficha),
        {"role": "user", "content": (
            f"Pedido do comprador:\n{json.dumps(pedido, ensure_ascii=False)}\n\n"
            f"Candidatos da base ({len(visao)}):\n"
            f"{json.dumps(visao, ensure_ascii=False, indent=1)}\n\n"
            f"{instrucao_extra}\n\n"
            f"Escolha até {quantidade} imóveis e responda SÓ com este JSON:\n"
            '{"itens":[{"property_id":"SP1234","preco":0,"area":0,"quartos":0,"vagas":0,'
            '"localizacao":"bairro e rua","seller_agent":"AGT000",'
            '"disponibilidade":"available","documentacao_status":"basic_verified",'
            '"motivo":"uma frase dizendo por que este imóvel serve para este comprador"}]}\n\n'
            "Regras: use só `property_id` que está na lista de candidatos. Copie preço, área, "
            "quartos e vagas exatamente como vieram. O motivo é para o comprador ler."
        )},
    ]
    return mensagens, 1600, 0.3


def build_orchestrator_escolha(entrada: dict) -> tuple[list[dict], int, float]:
    """Adaptado de orchestrator/motor.py::_avaliar_e_contratar (19/09/2026)."""
    capacidade = entrada.get("capacidade") or "buscar_imoveis"
    contexto = entrada.get("contexto") or ""
    criterios = entrada.get("criterios") or []
    orcamento_usd = float(entrada.get("orcamento_usd") or 1.0)
    resumo = entrada.get("candidatos") or []

    mensagens = [
        sistema(FICHAS["orchestrator"],
               "Você contrata agentes num marketplace. Você paga pelo que for "
               "PROVADO por verificação de código, e pode recontratar outro se a "
               "entrega for reprovada. Ninguém vai te aprovar nada: decida."),
        {"role": "user", "content": (
            f"Capacidade que você precisa contratar: {capacidade}\n"
            f"Contexto do trabalho: {contexto}\n"
            f"Critérios de aceite que você vai exigir:\n"
            + "\n".join(f"  - {c}" for c in criterios) + "\n"
            f"Orçamento para esta contratação: US$ {orcamento_usd:.2f}\n\n"
            f"Candidatos do marketplace:\n{json.dumps(resumo, ensure_ascii=False, indent=1)}\n\n"
            "`historico` com `entregas: 0` quer dizer que o agente ainda não tem entrega "
            "verificada nenhuma. `taxa_aprovacao` é a fração de itens que já passaram na "
            "verificação por código.\n\n"
            "Escolha UM e responda SÓ com este JSON:\n"
            '{"escolhido":"agente_id","motivo":"uma ou duas frases, em português simples, '
            'dizendo por que este e não o outro"}'
        )},
    ]
    return mensagens, 500, 0.3


def build_api_saude(entrada: dict) -> tuple[list[dict], int, float]:
    """Casos mínimos por capacidade, sem depender do sistema do projeto."""
    mensagens = [{"role": "user", "content": entrada.get("prompt") or ""}]
    max_tokens = int(entrada.get("max_tokens") or 500)
    temperature = float(entrada.get("temperature") or 0.3)
    return mensagens, max_tokens, temperature


BUILDERS = {
    "buyer_extracao": build_buyer_extracao,
    "buyer_negociacao": build_buyer_negociacao,
    "seller_negociacao": build_seller_negociacao,
    "property_busca": build_property_busca,
    "orchestrator_escolha": build_orchestrator_escolha,
    "api_saude": build_api_saude,
}


def construir_mensagens(suite_nome: str, entrada: dict) -> tuple[list[dict], int, float]:
    builder = BUILDERS.get(suite_nome)
    if builder is None:
        raise ValueError(f"suite sem builder de prompt: {suite_nome!r}")
    return builder(entrada)


# ------------------------------------------------------------------- HTTP

async def chamar_http(entrada: dict, base_url: str | None = None,
                      timeout: float | None = None) -> dict:
    """Chama `POST {base_url}{rota}` do servidor do projeto.

    `entrada` do caso precisa ter `rota` (ex.: "/agentes/buyer-porta-aberta/tarefas")
    e `corpo` (o JSON do pedido). Se o servidor não estiver de pé, devolve
    `{"ok": False, "erro_tipo": "alvo_fora_do_ar", ...}` em vez de lançar.
    """
    base_url = base_url or config.BASE_URL_PROJETO
    timeout = timeout if timeout is not None else config.TIMEOUT_S
    rota = entrada.get("rota") or "/"
    corpo = entrada.get("corpo") or {}
    import time as _time
    inicio = _time.monotonic()
    try:
        async with httpx.AsyncClient() as cliente:
            resposta = await cliente.post(f"{base_url}{rota}", json=corpo, timeout=timeout)
        latencia_ms = int((_time.monotonic() - inicio) * 1000)
        try:
            corpo_resposta = resposta.json()
        except ValueError:
            corpo_resposta = {"bruto_nao_json": resposta.text[:500]}
        return {"ok": resposta.status_code < 400, "http_status": resposta.status_code,
                "corpo": corpo_resposta, "latencia_ms": latencia_ms,
                "erro_tipo": None if resposta.status_code < 400 else "http_erro"}
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return {"ok": False, "erro_tipo": "alvo_fora_do_ar", "http_status": None,
                "corpo": {}, "latencia_ms": int((_time.monotonic() - inicio) * 1000)}
    except httpx.TimeoutException:
        return {"ok": False, "erro_tipo": "timeout", "http_status": None,
                "corpo": {}, "latencia_ms": int((_time.monotonic() - inicio) * 1000)}
    except httpx.HTTPError as erro:
        return {"ok": False, "erro_tipo": "rede", "http_status": None,
                "corpo": {"erro": str(erro)[:300]},
                "latencia_ms": int((_time.monotonic() - inicio) * 1000)}
