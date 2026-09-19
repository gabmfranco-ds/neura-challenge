"""O Orchestrator: descobre, avalia, contrata, delega e verifica. Sozinho.

O que este arquivo NÃO faz, de propósito:

- não conhece nome de agente: pergunta ao Registry por CAPACIDADE;
- não confia em nota de LLM para aceitar entrega: quem aprova é `nucleo.verificacao`;
- não pede aprovação humana no meio: o humano age em três momentos e pronto
  (escreve a frase, escolhe um imóvel, autoriza a oferta com um teto).

Toda decisão vira um evento com o motivo escrito em português simples.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

import httpx

from agentes import comum
from nucleo import config, dados, db, estados, reprise, verificacao
from orchestrator import memoria

logger = logging.getLogger("neura.orchestrator")

URL_REGISTRY = f"{config.BASE_URL}/registry"
TIMEOUT_AGENTE = 120.0
MAX_RODADAS_NEGOCIACAO = 4
ALVO_SHORTLIST = 4
MINIMO_SHORTLIST = 3

FICHA = {
    "agente_id": "orchestrator",
    "name": "Orquestrador",
    "description": "Contrata agentes no marketplace para atender o comprador.",
    "estrategia": "Paga pelo que for provado. Sem histórico, testa e verifica. "
                  "Reprovou, retém, publica o recibo e contrata outro.",
    "capacidade_neuralake": config.capacidade("orchestrator"),
}

RODADAS: dict[str, "Rodada"] = {}


@dataclass
class Rodada:
    id: str
    frase: str
    estado: str = estados.INICIAL
    criada_em: float = field(default_factory=time.time)
    pedido: dict | None = None
    suposicoes: list = field(default_factory=list)
    shortlist: list = field(default_factory=list)
    escolha: str | None = None
    mandato: dict | None = None
    negociacao: list = field(default_factory=list)
    preco_acordado: int | None = None
    pacote: dict | None = None
    contratos: list = field(default_factory=list)
    memoria_usada: dict | None = None
    reprovados: list = field(default_factory=list)
    custo_busca_usd: float = 0.0
    erro: str | None = None
    concluida_em: float | None = None
    trabalhando: bool = False
    gravacao: str | None = None

    def para_json(self) -> dict:
        return {
            "rodada_id": self.id, "frase": self.frase, "estado": self.estado,
            "pedido": self.pedido, "suposicoes": self.suposicoes,
            "shortlist": self.shortlist, "escolha": self.escolha, "mandato": self.mandato,
            "negociacao": self.negociacao, "preco_acordado": self.preco_acordado,
            "pacote": self.pacote, "contratos": self.contratos,
            "memoria_usada": self.memoria_usada, "custo_busca_usd": round(self.custo_busca_usd, 6),
            "erro": self.erro, "trabalhando": self.trabalhando,
            "duracao_s": round((self.concluida_em or time.time()) - self.criada_em, 1),
            "concluida": self.estado in estados.TERMINAIS,
            "gravacao": self.gravacao,
            "escrow": {"saldo_brl": db.saldo_escrow(self.id),
                       "lancamentos": db.razao_escrow(self.id)},
            "placar": placar(self.id),
        }


# ------------------------------------------------------------------ eventos

def _evento(rodada: Rodada, tipo: str, de: str | None, para: str | None, motivo: str,
            custo_usd: float = 0.0, dados_extra: dict | None = None) -> None:
    db.inserir_evento(rodada.id, rodada.estado, tipo, de, para, motivo, custo_usd, dados_extra)


def _transitar(rodada: Rodada, novo: str, motivo: str) -> None:
    estados.exigir(rodada.estado, novo)
    anterior = rodada.estado
    rodada.estado = novo
    db.inserir_evento(rodada.id, novo, "estado", anterior, novo, motivo)


def placar(rodada_id: str) -> dict:
    contagem = {"decisoes_sem_humano": 0, "repasses": 0, "intervencoes_humanas": 0,
                "verificacoes": 0, "chamadas_auto": 0, "chamadas_total": 0,
                "custo_total_usd": 0.0}
    for evento in db.eventos_desde(0, rodada_id):
        tipo = evento["tipo"]
        contagem["custo_total_usd"] += float(evento["custo_usd"] or 0.0)
        if tipo == "decisao":
            contagem["decisoes_sem_humano"] += 1
        elif tipo == "repasse":
            contagem["repasses"] += 1
        elif tipo == "humano":
            contagem["intervencoes_humanas"] += 1
        elif tipo == "verificacao":
            contagem["verificacoes"] += 1
        elif tipo == "chamada":
            contagem["chamadas_total"] += 1
            if (evento.get("dados") or {}).get("capacidade_pedida") == "auto":
                contagem["chamadas_auto"] += 1
    contagem["custo_total_usd"] = round(contagem["custo_total_usd"], 6)
    return contagem


# --------------------------------------------------------------------- HTTP

async def _get(url: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient() as cliente:
        resposta = await cliente.get(url, params=params, timeout=TIMEOUT_AGENTE)
        resposta.raise_for_status()
        return resposta.json()


async def _post(url: str, corpo: dict) -> dict:
    async with httpx.AsyncClient() as cliente:
        resposta = await cliente.post(url, json=corpo, timeout=TIMEOUT_AGENTE)
        resposta.raise_for_status()
        return resposta.json()


# ---------------------------------------------- descobrir, avaliar, contratar

async def _descobrir(rodada: Rodada, capacidade: str, property_id: str | None = None) -> list[dict]:
    params = {"capacidade": capacidade}
    if property_id:
        params["property_id"] = property_id
    resposta = await _get(f"{URL_REGISTRY}/agentes", params)
    candidatos = resposta.get("agentes") or []
    nomes = ", ".join(f"{c['name']} (US$ {c.get('preco_usd', 0):.2f})" for c in candidatos[:6])
    _evento(rodada, "repasse", "Orquestrador", "Registry",
            f"perguntei ao marketplace quem faz \"{capacidade}\": {len(candidatos)} agente(s). {nomes}",
            dados_extra={"capacidade": capacidade,
                         "candidatos": [c["agente_id"] for c in candidatos]})
    return candidatos


async def _avaliar_e_contratar(rodada: Rodada, capacidade: str, candidatos: list[dict],
                               contexto: str, criterios: list[str],
                               orcamento_usd: float) -> dict | None:
    if not candidatos:
        _evento(rodada, "decisao", "Orquestrador", None,
                f"ninguém no marketplace publica a capacidade \"{capacidade}\"")
        return None
    if len(candidatos) == 1:
        escolhido = candidatos[0]
        _evento(rodada, "decisao", "Orquestrador", escolhido["name"],
                f"contratei {escolhido['name']}: era o único candidato para \"{capacidade}\" "
                f"nesta contratação. Preço US$ {escolhido.get('preco_usd', 0):.2f}.",
                dados_extra={"capacidade": capacidade, "escolhido": escolhido["agente_id"]})
        return escolhido

    resumo = [{
        "agente_id": c["agente_id"], "nome": c["name"], "preco_usd": c.get("preco_usd"),
        "estrategia": c.get("estrategia"), "descricao": c.get("description"),
        "acesso_a_dados": c.get("acesso_a_dados"), "faz_escrow": c.get("escrow"),
        "historico": c.get("historico"),
    } for c in candidatos]

    mensagens = [
        comum.sistema(FICHA, "Você contrata agentes num marketplace. Você paga pelo que for "
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
    objeto, resultado = await comum.pedir_json(FICHA, mensagens, etapa=f"avaliar:{capacidade}",
                                               rodada_id=rodada.id, max_tokens=500)
    validos = {c["agente_id"]: c for c in candidatos}
    escolhido = None
    motivo = ""
    if isinstance(objeto, dict):
        escolhido = validos.get(str(objeto.get("escolhido") or "").strip())
        motivo = str(objeto.get("motivo") or "")[:400]
    if escolhido is None:
        escolhido = min(candidatos, key=lambda c: c.get("preco_usd") or 0)
        motivo = (f"o modelo não devolveu uma escolha válida; fiquei com o mais barato "
                  f"({escolhido['name']}) porque pago só pelo que for provado")
    _evento(rodada, "decisao", "Orquestrador", escolhido["name"],
            f"contratei {escolhido['name']} por US$ {escolhido.get('preco_usd', 0):.2f}: {motivo}",
            resultado.custo_usd,
            dados_extra={"capacidade": capacidade, "escolhido": escolhido["agente_id"],
                         "candidatos": list(validos), "orcamento_usd": orcamento_usd,
                         "criterios_de_aceite": criterios})
    return escolhido


async def _delegar(rodada: Rodada, card: dict, skill: str, entrada: dict,
                   criterios: list[str], orcamento_usd: float, resumo: str) -> dict:
    _evento(rodada, "repasse", "Orquestrador", card["name"],
            f"deleguei \"{skill}\" para {card['name']}: {resumo}",
            dados_extra={"skill": skill, "orcamento_usd": orcamento_usd,
                         "criterios_de_aceite": criterios})
    resposta = await _post(f"{card['url']}/tarefas", {
        "skill": skill, "entrada": entrada, "criterios_de_aceite": criterios,
        "orcamento_usd": orcamento_usd, "rodada_id": rodada.id,
    })
    _evento(rodada, "repasse", card["name"], "Orquestrador",
            f"{card['name']} devolveu a entrega de \"{skill}\"",
            dados_extra={"skill": skill})
    return resposta


async def _pagar(rodada: Rodada, card: dict, skill: str, pedidos: int, provados: int,
                 motivo: str) -> dict:
    preco = float(card.get("preco_usd") or 0.0)
    pago, retido = verificacao.pagamento_proporcional(preco, pedidos, provados)
    recibo = {
        "id": db.novo_id("rec-"), "rodada_id": rodada.id, "agente_id": card["agente_id"],
        "skill": skill, "itens_pedidos": pedidos, "itens_provados": provados,
        "preco_usd": preco, "pago_usd": pago, "retido_usd": retido, "motivo": motivo,
    }
    await _post(f"{URL_REGISTRY}/recibos", recibo)
    db.creditar_honorario(card["agente_id"], pago)
    db.debitar_honorario("orchestrator", pago)
    if retido > 0:
        db.registrar_retido(card["agente_id"], retido)
    rodada.contratos.append({**recibo, "agente_nome": card["name"]})
    _evento(rodada, "decisao", "Orquestrador", card["name"],
            f"paguei US$ {pago:.2f} de US$ {preco:.2f} a {card['name']} "
            f"({provados} de {pedidos} itens provados). Retido: US$ {retido:.2f}. "
            f"Recibo publicado no marketplace.",
            dados_extra={"recibo": recibo})
    return recibo


# -------------------------------------------------------------- fluxo 1

async def iniciar(frase: str) -> Rodada:
    rodada = Rodada(id=db.novo_id("rod-"), frase=frase)
    RODADAS[rodada.id] = rodada
    db.abrir_carteira("orchestrator", "Orquestrador", config.ORCAMENTO_PADRAO_USD * 4)
    _evento(rodada, "humano", "Comprador", "Buyer Agent",
            f"o comprador escreveu: \"{frase}\"")
    asyncio.create_task(_fluxo_busca(rodada))
    return rodada


async def _fluxo_busca(rodada: Rodada) -> None:
    rodada.trabalhando = True
    inicio = time.time()
    try:
        candidatos_busca_task = asyncio.create_task(_descobrir(rodada, "buscar_imoveis"))
        pedido_task = asyncio.create_task(_entender(rodada))
        candidatos_busca, _ = await asyncio.gather(candidatos_busca_task, pedido_task)

        if not rodada.pedido:
            raise RuntimeError("não consegui transformar a frase em um pedido")

        lembranca = memoria.buscar(rodada.pedido)
        if lembranca:
            rodada.shortlist = lembranca["shortlist"]
            rodada.memoria_usada = {
                "rodada_origem": lembranca["rodada_id"],
                "custo_original_usd": lembranca["custo_original_usd"],
                "custo_agora_usd": 0.0,
            }
            _evento(rodada, "decisao", "Orquestrador", "memória",
                    f"pedido parecido com o da rodada {lembranca['rodada_id']}: reaproveitei a "
                    f"busca já verificada e não contratei ninguém para buscar. "
                    f"A primeira custou US$ {lembranca['custo_original_usd']:.4f}; esta custou "
                    f"US$ 0,0000 em busca.",
                    dados_extra={"memoria": rodada.memoria_usada})
        else:
            await _buscar_com_marketplace(rodada, candidatos_busca)

        if not rodada.shortlist:
            _transitar(rodada, "ABORTED", "nenhum imóvel passou na verificação")
            rodada.erro = "nenhum imóvel aprovado"
            return

        _transitar(rodada, "SHORTLIST",
                   f"{len(rodada.shortlist)} imóveis verificados prontos para o comprador escolher")
        if not rodada.memoria_usada:
            memoria.guardar(rodada.pedido, rodada.shortlist, rodada.custo_busca_usd, rodada.id)
    except Exception as erro:
        logger.exception("fluxo de busca falhou")
        rodada.erro = str(erro)
        if rodada.estado not in estados.TERMINAIS:
            _transitar(rodada, "ABORTED", f"a busca parou: {erro}")
    finally:
        rodada.trabalhando = False
        logger.info("fluxo de busca terminou em %.1fs", time.time() - inicio)


async def _entender(rodada: Rodada) -> None:
    candidatos = await _descobrir(rodada, "entender_pedido")
    contratado = await _avaliar_e_contratar(
        rodada, "entender_pedido", candidatos,
        contexto=f"transformar em pedido estruturado a frase: \"{rodada.frase}\"",
        criterios=["devolver pedido com cidade, bairros, preço máximo e mínimos",
                   "declarar o que assumiu"],
        orcamento_usd=0.50)
    if contratado is None:
        raise RuntimeError("nenhum agente sabe entender o pedido do comprador")
    resposta = await _delegar(rodada, contratado, "entender_pedido", {"frase": rodada.frase},
                              criterios=["pedido estruturado"], orcamento_usd=0.50,
                              resumo="transformar a frase do comprador em filtros")
    saida = resposta.get("saida") or {}
    rodada.pedido = saida.get("pedido")
    rodada.suposicoes = saida.get("suposicoes") or []
    rodada.custo_busca_usd += float(resposta.get("custo_usd") or 0.0)
    faltando = [c for c in ("cidade", "preco_max") if not (rodada.pedido or {}).get(c)]
    aprovado = bool(rodada.pedido) and not faltando
    _evento(rodada, "verificacao", "Orquestrador", contratado["name"],
            (f"conferi o pedido por código: {json.dumps(rodada.pedido, ensure_ascii=False)}"
             if aprovado else
             f"o pedido veio incompleto (falta {', '.join(faltando)})"),
            dados_extra={"aprovado": aprovado, "fonte": saida.get("fonte")})
    await _pagar(rodada, contratado, "entender_pedido", 1, 1 if aprovado else 0,
                 "pedido estruturado conferido por código" if aprovado else "pedido incompleto")


async def _buscar_com_marketplace(rodada: Rodada, candidatos: list[dict]) -> None:
    contexto = (f"buscar imóveis para o pedido {json.dumps(rodada.pedido, ensure_ascii=False)}. "
                f"Cada imóvel devolvido vai passar por verificação de código contra a base: "
                f"existência, filtros, disponibilidade real e documentação real.")
    criterios = [
        "todo imóvel devolvido existe na base e bate com os filtros do pedido",
        "a disponibilidade afirmada bate com a da base",
        "o status de documentação afirmado bate com o que os documentos dizem",
        f"pelo menos {MINIMO_SHORTLIST} imóveis aprovados",
    ]
    restantes = list(candidatos)
    aprovados: list[dict] = []
    ultimo_nome = ""
    # Enquanto faltar imóvel aprovado E existir concorrente que ainda não tentou,
    # o Orchestrator contrata outro. Sozinho, sem perguntar a ninguém.
    while len(aprovados) < MINIMO_SHORTLIST and restantes:
        if aprovados or ultimo_nome:
            contexto_agora = (f"a entrega de {ultimo_nome} foi reprovada em parte pela "
                              f"verificação por código e sobraram {len(aprovados)} imóveis "
                              f"aprovados. Preciso de mais, sem repetir os que já reprovaram.")
        else:
            contexto_agora = contexto
        contratado = await _avaliar_e_contratar(rodada, "buscar_imoveis", restantes,
                                                contexto_agora, criterios, orcamento_usd=1.20)
        if contratado is None:
            break
        restantes = [c for c in restantes if c["agente_id"] != contratado["agente_id"]]
        ultimo_nome = contratado["name"]
        faltam = ALVO_SHORTLIST - len(aprovados)
        evitar = {i["property_id"] for i in aprovados} | set(rodada.reprovados)
        aprovados += await _rodar_busca(rodada, contratado, criterios, faltam, evitar)

    if not aprovados and not candidatos:
        raise RuntimeError("nenhum agente publica a capacidade de buscar imóveis")
    rodada.shortlist = aprovados[:ALVO_SHORTLIST]


async def _rodar_busca(rodada: Rodada, card: dict, criterios: list[str], quantidade: int,
                       evitar: set[str]) -> list[dict]:
    resposta = await _delegar(
        rodada, card, "buscar_imoveis",
        {"pedido": rodada.pedido, "quantidade": quantidade, "evitar": sorted(evitar)},
        criterios=criterios, orcamento_usd=float(card.get("preco_usd") or 0),
        resumo=f"achar até {quantidade} imóveis que atendam ao pedido")
    rodada.custo_busca_usd += float(resposta.get("custo_usd") or 0.0)
    itens = (resposta.get("saida") or {}).get("itens") or []

    conferencia = verificacao.conferir_busca(itens, rodada.pedido)
    linhas = []
    for item in conferencia["itens"]:
        if item["aprovado"]:
            linhas.append(f"{item['property_id']}: passou")
        else:
            linhas.append(f"{item['property_id']}: REPROVADO ({item['motivos'][0]})")
    _evento(rodada, "verificacao", "Orquestrador", card["name"],
            f"conferi por código os {conferencia['pedidos']} imóveis de {card['name']}: "
            f"{conferencia['provados']} passaram. " + " | ".join(linhas),
            dados_extra={"conferencia": conferencia})

    await _pagar(rodada, card, "buscar_imoveis", conferencia["pedidos"], conferencia["provados"],
                 f"{conferencia['provados']} de {conferencia['pedidos']} imóveis passaram na "
                 f"verificação por código")

    for reprovado in conferencia["reprovados"]:
        if reprovado["property_id"] not in rodada.reprovados:
            rodada.reprovados.append(reprovado["property_id"])

    aprovados = []
    por_id = {i.get("property_id"): i for i in itens}
    for conferido in conferencia["itens"]:
        if not conferido["aprovado"]:
            continue
        base = dados.imovel(conferido["property_id"])
        entregue = por_id.get(conferido["property_id"]) or {}
        aprovados.append({
            "property_id": base["property_id"], "preco": base["preco"], "area": base["area"],
            "quartos": base["quartos"], "vagas": base["vagas"],
            "localizacao": f"{base['endereco']}, {base['bairro']}",
            "seller_agent": base["seller_agent"],
            "disponibilidade": base["disponibilidade"],
            "documentacao_status": conferido["conferido"]["documentacao_status"],
            "motivo": str(entregue.get("motivo") or "")[:300],
            "indicado_por": card["name"],
            "comparacao_preco": conferido["conferido"]["comparacao_preco"],
        })
    return aprovados


# -------------------------------------------------------------- fluxo 2

def escolher(rodada: Rodada, property_id: str) -> None:
    if not any(i["property_id"] == property_id for i in rodada.shortlist):
        raise ValueError(f"{property_id} não está na shortlist desta rodada")
    rodada.escolha = property_id
    _evento(rodada, "humano", "Comprador", "Buyer Agent",
            f"o comprador escolheu o imóvel {property_id} da shortlist")
    _transitar(rodada, "PROPERTY_SELECTED", f"comprador escolheu {property_id}")


async def ofertar(rodada: Rodada, teto_preco: int, prazo_dias: int = 60) -> None:
    rodada.mandato = {"teto_preco": int(teto_preco), "prazo_dias": int(prazo_dias)}
    _evento(rodada, "humano", "Comprador", "Buyer Agent",
            f"o comprador autorizou a oferta com teto de R$ {teto_preco:,.0f} e prazo de "
            f"{prazo_dias} dias. A partir daqui ninguém mais consulta o comprador."
            .replace(",", "."))
    asyncio.create_task(_fluxo_compra(rodada))


async def _fluxo_compra(rodada: Rodada) -> None:
    rodada.trabalhando = True
    try:
        await _negociar(rodada)
        if rodada.estado != "OFFER_ACCEPTED":
            return
        await _transacionar(rodada)
        if rodada.estado in estados.TERMINAIS:
            return
        await _pagar_imovel(rodada)
    except Exception as erro:
        logger.exception("fluxo de compra falhou")
        rodada.erro = str(erro)
        if rodada.estado not in estados.TERMINAIS:
            _transitar(rodada, "ABORTED", f"a compra parou: {erro}")
    finally:
        rodada.trabalhando = False
        rodada.concluida_em = time.time()
        if rodada.estado == "COMPLETED":
            try:
                rodada.gravacao = reprise.gravar(rodada.id, rodada.para_json())
                _evento(rodada, "decisao", "Orquestrador", "gravação",
                        f"rodada gravada para reprise em {rodada.gravacao}")
            except Exception:
                logger.exception("falhei ao gravar a reprise")


async def _negociar(rodada: Rodada) -> None:
    imovel = dados.imovel(rodada.escolha)
    publico = dados.visao_anuncio(imovel)

    compradores = await _descobrir(rodada, "negociar_compra")
    buyer = await _avaliar_e_contratar(
        rodada, "negociar_compra", compradores,
        contexto=f"negociar a compra do imóvel {rodada.escolha} dentro do mandato do comprador",
        criterios=["nunca oferecer acima do teto do mandato",
                   f"fechar em no máximo {MAX_RODADAS_NEGOCIACAO} rodadas"],
        orcamento_usd=0.60)
    vendedores = await _descobrir(rodada, "negociar_venda", property_id=rodada.escolha)
    vendedor = await _avaliar_e_contratar(
        rodada, "negociar_venda", vendedores,
        contexto=f"o agente que responde pelo imóvel {rodada.escolha}",
        criterios=["responder aceita, contraproposta ou rejeita"], orcamento_usd=0.0)
    if buyer is None or vendedor is None:
        _transitar(rodada, "ABORTED", "faltou agente para negociar")
        return

    _transitar(rodada, "OFFER_CREATED", f"{buyer['name']} vai montar a primeira oferta")

    for numero in range(1, MAX_RODADAS_NEGOCIACAO + 1):
        jogada = (await _delegar(
            rodada, buyer, "negociar_compra",
            {"imovel": publico, "mandato": rodada.mandato, "historico": rodada.negociacao,
             "rodada": numero, "max_rodadas": MAX_RODADAS_NEGOCIACAO},
            criterios=["valor dentro do teto"], orcamento_usd=0.0,
            resumo=f"rodada {numero} da negociação"))["saida"]
        rodada.negociacao.append({"rodada": numero, "de": buyer["name"], **jogada})
        _evento(rodada, "repasse", buyer["name"], vendedor["name"],
                f"rodada {numero}: {jogada['acao']} de {comum.dinheiro(jogada.get('valor'))}. "
                f"{jogada.get('mensagem', '')} Motivo: {jogada.get('motivo', '')}",
                dados_extra={"jogada": jogada})

        if jogada["acao"] == "desistir":
            if rodada.estado == "OFFER_CREATED":
                _transitar(rodada, "OFFER_SENT", "última jogada do agente do comprador")
            _transitar(rodada, "OFFER_REJECTED",
                       f"o agente do comprador desistiu: {jogada.get('motivo', '')}")
            await _pagar_negociacao(rodada, buyer)
            return
        if jogada["acao"] == "aceitar":
            rodada.preco_acordado = jogada["valor"]
            if rodada.estado == "OFFER_CREATED":
                _transitar(rodada, "OFFER_SENT", "aceite da contraproposta do vendedor")
            _transitar(rodada, "OFFER_ACCEPTED",
                       f"acordo em {comum.dinheiro(jogada['valor'])} na rodada {numero}")
            break

        if rodada.estado in ("OFFER_CREATED", "COUNTER_OFFER"):
            _transitar(rodada, "OFFER_SENT", f"oferta {numero} enviada ao vendedor")

        resposta = (await _delegar(
            rodada, vendedor, "negociar_venda",
            {"property_id": rodada.escolha, "oferta": jogada.get("valor"),
             "mensagem": jogada.get("mensagem"), "historico": rodada.negociacao,
             "rodada": numero, "max_rodadas": MAX_RODADAS_NEGOCIACAO},
            criterios=["aceita, contraproposta ou rejeita"], orcamento_usd=0.0,
            resumo=f"responder à oferta {numero}"))["saida"]
        rodada.negociacao.append({"rodada": numero, "de": vendedor["name"], **resposta})
        _evento(rodada, "repasse", vendedor["name"], buyer["name"],
                f"rodada {numero}: {resposta['acao']} de {comum.dinheiro(resposta.get('valor'))}. "
                f"{resposta.get('mensagem', '')} Motivo: {resposta.get('motivo', '')}",
                dados_extra={"jogada": resposta})

        if resposta["acao"] == "aceita":
            rodada.preco_acordado = resposta["valor"]
            _transitar(rodada, "OFFER_ACCEPTED",
                       f"vendedor aceitou {comum.dinheiro(resposta['valor'])} na rodada {numero}")
            break
        if resposta["acao"] == "rejeita" and numero == MAX_RODADAS_NEGOCIACAO:
            _transitar(rodada, "OFFER_REJECTED", "vendedor rejeitou na última rodada")
            break
        _transitar(rodada, "COUNTER_OFFER",
                   f"contraproposta de {comum.dinheiro(resposta.get('valor'))}")

    if rodada.estado not in ("OFFER_ACCEPTED", "OFFER_REJECTED"):
        _transitar(rodada, "OFFER_REJECTED",
                   f"acabaram as {MAX_RODADAS_NEGOCIACAO} rodadas sem acordo dentro do mandato")
    await _pagar_negociacao(rodada, buyer)


async def _pagar_negociacao(rodada: Rodada, buyer: dict) -> None:
    """O Buyer Agent é pago pela negociação se tiver respeitado o mandato.

    Conta de código: nenhuma jogada dele pode ter passado do teto, e se houve
    acordo, o acordo tem que caber no teto.
    """
    teto = (rodada.mandato or {}).get("teto_preco")
    ofertas = [j.get("valor") for j in rodada.negociacao
               if j.get("de") == buyer["name"] and j.get("valor")]
    estourou = [v for v in ofertas if teto is not None and v > teto]
    conferencia = verificacao.conferir_mandato(rodada.preco_acordado, rodada.mandato) \
        if rodada.preco_acordado else {"aprovado": True, "motivos": []}
    respeitou = not estourou and conferencia["aprovado"]
    _evento(rodada, "verificacao", "Orquestrador", buyer["name"],
            (f"conferi por código as {len(ofertas)} jogadas do agente do comprador: nenhuma "
             f"passou do teto de {comum.dinheiro(teto)}" if respeitou else
             f"o agente do comprador furou o mandato em {len(estourou)} jogada(s)"),
            dados_extra={"ofertas": ofertas, "teto": teto})
    await _pagar(rodada, buyer, "negociar_compra", 1, 1 if respeitou else 0,
                 "negociou dentro do mandato" if respeitou else "furou o mandato do comprador")


async def _transacionar(rodada: Rodada) -> None:
    conferencia = verificacao.conferir_mandato(rodada.preco_acordado, rodada.mandato)
    _evento(rodada, "verificacao", "Orquestrador", "Buyer Agent",
            (f"conferi por código: R$ {rodada.preco_acordado:,.0f} cabe no teto de "
             f"R$ {rodada.mandato['teto_preco']:,.0f}".replace(",", ".")
             if conferencia["aprovado"] else
             f"o acordo furou o mandato: {conferencia['motivos'][0]}"),
            dados_extra={"conferencia": conferencia})
    if not conferencia["aprovado"]:
        _transitar(rodada, "ABORTED", conferencia["motivos"][0])
        return

    _transitar(rodada, "KYC_PENDING", "acordo fechado, começa a papelada (simulada)")

    candidatos = await _descobrir(rodada, "conduzir_transacao")
    criterios = ["todas as condições precedentes obrigatórias atendidas antes do pagamento",
                 "condições documentais conferidas contra os documentos do imóvel"]
    contexto = (f"conduzir a transação do imóvel {rodada.escolha} por "
                f"R$ {rodada.preco_acordado}. Vou conferir por código quantas condições "
                f"precedentes obrigatórias ficaram atendidas e pagar proporcional.")
    contratado = await _avaliar_e_contratar(rodada, "conduzir_transacao", candidatos, contexto,
                                            criterios, orcamento_usd=1.50)
    if contratado is None:
        _transitar(rodada, "ABORTED", "nenhum agente conduz transação")
        return

    pacote, faltando = await _rodar_transacao(rodada, contratado, criterios)

    if faltando:
        outros = [c for c in candidatos if c["agente_id"] != contratado["agente_id"]]
        substituto = await _avaliar_e_contratar(
            rodada, "conduzir_transacao", outros,
            contexto=(f"{contratado['name']} deixou {len(faltando)} condições obrigatórias "
                      f"pendentes: {', '.join(f['nome'] for f in faltando[:4])}. Preciso de "
                      f"alguém que feche essas condições."),
            criterios=criterios, orcamento_usd=1.50) if outros else None
        if substituto is not None:
            pacote, faltando = await _rodar_transacao(rodada, substituto, criterios)

    rodada.pacote = pacote
    if faltando:
        _transitar(rodada, "ABORTED",
                   f"condições obrigatórias continuam pendentes: "
                   f"{', '.join(f['nome'] for f in faltando[:3])}")
        return

    _transitar(rodada, "DOCUMENTS_VERIFIED", "documentação conferida por código")
    _transitar(rodada, "CONTRACT_SIGNED", "contrato assinado (SIMULADO)")


async def _rodar_transacao(rodada: Rodada, card: dict, criterios: list[str]) -> tuple[dict, list]:
    resposta = await _delegar(
        rodada, card, "conduzir_transacao",
        {"property_id": rodada.escolha, "preco_acordado": rodada.preco_acordado,
         "mandato": rodada.mandato, "comprador": {"nome": "comprador da demo"}},
        criterios=criterios, orcamento_usd=float(card.get("preco_usd") or 0),
        resumo="montar KYC, contrato e a lista de condições precedentes")
    pacote = resposta.get("saida") or {}
    condicoes = pacote.get("condicoes") or []
    conferencia = verificacao.conferir_condicoes(condicoes, ate_fase="CONTRACT_SIGNED")
    pendentes = conferencia["pendentes"]
    _evento(rodada, "verificacao", "Orquestrador", card["name"],
            (f"conferi por código as condições até a assinatura: "
             f"{conferencia['atendidas']} de {conferencia['total']} atendidas, "
             f"{conferencia['obrigatorias']} obrigatórias."
             + (f" Pendentes: {', '.join(p['nome'] for p in pendentes[:4])}." if pendentes else
                " Nenhuma pendência.")),
            dados_extra={"conferencia": conferencia})
    await _pagar(rodada, card, "conduzir_transacao", conferencia["obrigatorias"],
                 conferencia["obrigatorias"] - len(pendentes),
                 f"{len(pendentes)} condições obrigatórias pendentes" if pendentes
                 else "todas as condições obrigatórias desta fase atendidas")
    return pacote, pendentes


async def _pagar_imovel(rodada: Rodada) -> None:
    candidatos = await _descobrir(rodada, "custodia_pagamento")
    criterios = ["reservar os fundos antes de qualquer liberação",
                 "não liberar nada sem todas as condições obrigatórias conferidas"]
    contratado = await _avaliar_e_contratar(
        rodada, "custodia_pagamento", candidatos,
        contexto=(f"guardar R$ {rodada.preco_acordado} até as condições ficarem prontas. "
                  f"O mandato do comprador exige custódia: dinheiro não sai antes da "
                  f"conferência."),
        criterios=criterios, orcamento_usd=1.00)
    if contratado is None:
        _transitar(rodada, "ABORTED", "nenhum agente faz custódia de pagamento")
        return

    resposta = await _delegar(
        rodada, contratado, "custodia_pagamento",
        {"acao": "reservar", "rodada_id": rodada.id, "property_id": rodada.escolha,
         "valor_brl": rodada.preco_acordado},
        criterios=criterios, orcamento_usd=float(contratado.get("preco_usd") or 0),
        resumo=f"reservar R$ {rodada.preco_acordado} em escrow")
    reserva = resposta.get("saida") or {}
    reservou = bool(reserva.get("reservado")) and db.saldo_escrow(rodada.id) > 0
    _evento(rodada, "verificacao", "Orquestrador", contratado["name"],
            (f"conferi o razão de escrow: R$ {db.saldo_escrow(rodada.id):,.0f} reservados"
             .replace(",", ".") if reservou else
             f"nada foi reservado: {reserva.get('observacao')}"),
            dados_extra={"reserva": reserva})

    if not reservou:
        await _pagar(rodada, contratado, "custodia_pagamento", 1, 0,
                     "não reservou os fundos, como a ficha dele já dizia")
        outros = [c for c in candidatos if c["agente_id"] != contratado["agente_id"]]
        contratado = await _avaliar_e_contratar(
            rodada, "custodia_pagamento", outros,
            contexto=("o contratado anterior não reservou nada. Preciso de um agente que "
                      "faça custódia de verdade."),
            criterios=criterios, orcamento_usd=1.00) if outros else None
        if contratado is None:
            _transitar(rodada, "ABORTED", "ninguém reservou os fundos")
            return
        resposta = await _delegar(
            rodada, contratado, "custodia_pagamento",
            {"acao": "reservar", "rodada_id": rodada.id, "property_id": rodada.escolha,
             "valor_brl": rodada.preco_acordado},
            criterios=criterios, orcamento_usd=float(contratado.get("preco_usd") or 0),
            resumo=f"reservar R$ {rodada.preco_acordado} em escrow")
        if not (resposta.get("saida") or {}).get("reservado"):
            _transitar(rodada, "ABORTED", "o segundo agente de custódia também não reservou")
            return
        _evento(rodada, "verificacao", "Orquestrador", contratado["name"],
                f"conferi o razão de escrow: R$ {db.saldo_escrow(rodada.id):,.0f} reservados"
                .replace(",", "."))

    _transitar(rodada, "FUNDS_LOCKED", "fundos reservados no escrow (SIMULADO)")

    condicoes = (rodada.pacote or {}).get("condicoes") or []
    conferencia = verificacao.conferir_condicoes(condicoes, ate_fase="CONDITIONS_MET")
    _evento(rodada, "verificacao", "Orquestrador", "condições precedentes",
            f"conferi por código as condições precedentes até a liberação: "
            f"{conferencia['atendidas']} de {conferencia['total']} atendidas, sendo "
            f"{conferencia['obrigatorias']} obrigatórias e "
            f"{len(conferencia['pendentes'])} delas pendentes.",
            dados_extra={"conferencia": conferencia})
    if not conferencia["aprovado"]:
        _transitar(rodada, "ABORTED",
                   f"não libero pagamento com condição pendente: "
                   f"{conferencia['pendentes'][0]['nome']}")
        return

    _transitar(rodada, "CONDITIONS_MET", "todas as condições obrigatórias conferidas por código")

    resposta = await _delegar(
        rodada, contratado, "custodia_pagamento",
        {"acao": "conferir_e_liberar", "rodada_id": rodada.id, "property_id": rodada.escolha,
         "valor_brl": rodada.preco_acordado, "condicoes": condicoes},
        criterios=criterios, orcamento_usd=float(contratado.get("preco_usd") or 0),
        resumo="conferir as condições e liberar o pagamento")
    liberacao = resposta.get("saida") or {}
    liberou = bool(liberacao.get("liberado"))
    _evento(rodada, "verificacao", "Orquestrador", contratado["name"],
            (f"pagamento liberado (SIMULADO). Saldo do escrow: "
             f"R$ {db.saldo_escrow(rodada.id):,.0f}".replace(",", ".") if liberou else
             f"o agente não liberou: {liberacao.get('observacao')}"),
            dados_extra={"liberacao": liberacao})
    await _pagar(rodada, contratado, "custodia_pagamento", 2, 2 if liberou else 1,
                 "reservou e liberou com conferência" if liberou else "reservou mas não liberou")
    if not liberou:
        _transitar(rodada, "ABORTED", str(liberacao.get("observacao") or "pagamento não liberado"))
        return

    _transitar(rodada, "PAYMENT_RELEASED", "dinheiro liberado ao vendedor (SIMULADO)")
    _transitar(rodada, "PROPERTY_TRANSFERRED",
               "registro do título na matrícula (SIMULADO): o imóvel passa para o comprador")
    _transitar(rodada, "COMPLETED",
               f"compra concluída por {comum.dinheiro(rodada.preco_acordado)}")
