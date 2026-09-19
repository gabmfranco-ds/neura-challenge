"""Fichas de todos os agentes, no formato do Agent Card do A2A.

Cada agente publica a sua em `GET {url}/.well-known/agent-card.json` e se
cadastra sozinho no Registry no boot. O Orchestrator NUNCA lê este arquivo: ele
só conhece a URL do Registry e descobre por capacidade.

Para cada capacidade que importa há pelo menos dois concorrentes com preço e
estratégia DIFERENTES. A estratégia é declarada na ficha, e é dela que sai o
comportamento do agente: o prompt do agente é montado a partir da própria ficha.
"""
from __future__ import annotations

from nucleo import config, dados

# Capacidades do marketplace (é por isto que o Orchestrator procura).
ENTENDER_PEDIDO = "entender_pedido"
NEGOCIAR_COMPRA = "negociar_compra"
BUSCAR_IMOVEIS = "buscar_imoveis"
NEGOCIAR_VENDA = "negociar_venda"
CONDUZIR_TRANSACAO = "conduzir_transacao"
CUSTODIA_PAGAMENTO = "custodia_pagamento"


def _url(slug: str) -> str:
    return f"{config.BASE_URL}/agentes/{slug}"


ENTRADA_BUSCA = {"pedido": "objeto com tipo, cidade, bairros, preco_max, quartos_min, "
                           "vagas_min, area_min, financiamento"}
SAIDA_BUSCA = {"itens": "lista de {property_id, preco, area, quartos, vagas, localizacao, "
                        "seller_agent, disponibilidade, documentacao_status, motivo}"}

FICHAS_FIXAS: list[dict] = [
    {
        "agente_id": "buyer-porta-aberta",
        "name": "Porta Aberta",
        "description": "Agente do comprador. Transforma a frase em pedido estruturado e "
                       "negocia pelo comprador dentro do mandato recebido, sem voltar a "
                       "pedir aprovação a cada rodada.",
        "papel": "buyer",
        "preco_usd": 0.30,
        "estrategia": "Assume o que falta na frase e declara a suposição. Na negociação, "
                      "começa abaixo do anúncio e sobe devagar, nunca passando do teto.",
        "skills": [
            {"id": ENTENDER_PEDIDO,
             "description": "Transforma a frase do comprador em pedido estruturado.",
             "entrada": {"frase": "texto livre do comprador"},
             "saida": {"pedido": "objeto estruturado", "suposicoes": "lista de texto"}},
            {"id": NEGOCIAR_COMPRA,
             "description": "Decide a próxima jogada da negociação dentro do mandato.",
             "entrada": {"imovel": "visão pública", "mandato": "{teto_preco, prazo_dias}",
                         "historico": "rodadas anteriores", "rodada": "número"},
             "saida": {"acao": "oferta | aceitar | desistir", "valor": "número",
                       "mensagem": "texto para o vendedor", "motivo": "texto curto"}},
        ],
    },
    {
        "agente_id": "property-casa-verificada",
        "name": "Casa Verificada",
        "description": "Busca imóveis e confere cada candidato antes de indicar: abre os "
                       "documentos (matrícula, certidões, IPTU, condomínio) e confere a "
                       "disponibilidade na base.",
        "papel": "property",
        "preco_usd": 0.90,
        "estrategia": "Só indica imóvel com documentação lida e disponibilidade conferida. "
                      "Custa mais e demora mais.",
        "acesso_a_dados": "anuncio + disponibilidade + texto dos documentos",
        "skills": [{"id": BUSCAR_IMOVEIS,
                    "description": "Devolve de 3 a 5 imóveis que atendem ao pedido, com o "
                                   "motivo de cada um, disponibilidade e status de documentação.",
                    "entrada": ENTRADA_BUSCA, "saida": SAIDA_BUSCA}],
    },
    {
        "agente_id": "property-busca-relampago",
        "name": "Busca Relâmpago",
        "description": "Busca imóveis rápido e barato. ESTRATÉGIA DECLARADA: trabalha só "
                       "com o texto do anúncio. NÃO abre documentos e NÃO confere a "
                       "disponibilidade na base.",
        "papel": "property",
        "preco_usd": 0.35,
        "estrategia": "Velocidade e preço acima de conferência. O que o anúncio diz é o "
                      "que vai na resposta. Quem contratar sabe que está comprando isso.",
        "acesso_a_dados": "somente o anuncio (sem disponibilidade, sem documentos)",
        "skills": [{"id": BUSCAR_IMOVEIS,
                    "description": "Devolve de 3 a 5 imóveis que atendem ao pedido, a partir "
                                   "do anúncio.",
                    "entrada": ENTRADA_BUSCA, "saida": SAIDA_BUSCA}],
    },
    {
        "agente_id": "transaction-cartorio-digital",
        "name": "Cartório Digital",
        "description": "Conduz a transação: KYC, conferência documental, contrato e a lista "
                       "completa de condições precedentes. SIMULADO.",
        "papel": "transaction",
        "preco_usd": 1.20,
        "simulado": True,
        "estrategia": "Marca condição só quando o documento sustenta. Confere as condições "
                      "documentais uma a uma contra os documentos do imóvel.",
        "skills": [{"id": CONDUZIR_TRANSACAO,
                    "description": "Monta o pacote de fechamento com todas as condições "
                                   "precedentes da lista do time.",
                    "entrada": {"property_id": "str", "preco_acordado": "número",
                                "mandato": "objeto", "comprador": "objeto"},
                    "saida": {"kyc": "objeto", "condicoes": "lista", "contrato": "objeto"}}],
    },
    {
        "agente_id": "transaction-fecha-rapido",
        "name": "Fecha Rápido",
        "description": "Conduz a transação pelo mínimo: KYC e contrato. ESTRATÉGIA "
                       "DECLARADA: não confere certidão, IPTU nem condomínio. SIMULADO.",
        "papel": "transaction",
        "preco_usd": 0.55,
        "simulado": True,
        "estrategia": "Fecha rápido com as condições mínimas. As condições documentais "
                      "ficam pendentes para o comprador resolver depois.",
        "skills": [{"id": CONDUZIR_TRANSACAO,
                    "description": "Monta o pacote de fechamento com as condições mínimas.",
                    "entrada": {"property_id": "str", "preco_acordado": "número",
                                "mandato": "objeto", "comprador": "objeto"},
                    "saida": {"kyc": "objeto", "condicoes": "lista", "contrato": "objeto"}}],
    },
    {
        "agente_id": "payment-escrow-guardiao",
        "name": "Escrow Guardião",
        "description": "Custódia do pagamento: reserva os fundos, mantém um razão e só "
                       "libera com todas as condições obrigatórias conferidas. SIMULADO.",
        "papel": "payment",
        "preco_usd": 0.80,
        "simulado": True,
        "escrow": True,
        "estrategia": "Nenhuma liberação sem conferência de condição. Razão em sqlite, "
                      "lançamento a lançamento.",
        "skills": [{"id": CUSTODIA_PAGAMENTO,
                    "description": "Reserva, confere condições e libera o pagamento.",
                    "entrada": {"rodada_id": "str", "property_id": "str",
                                "valor_brl": "número", "condicoes": "lista"},
                    "saida": {"escrow_id": "str", "lancamentos": "lista", "liberado": "bool"}}],
    },
    {
        "agente_id": "payment-liquida-ja",
        "name": "Liquida Já",
        "description": "Pagamento direto ao vendedor, sem custódia. ESTRATÉGIA DECLARADA: "
                       "não faz escrow, manda o dinheiro assim que o contrato é assinado. "
                       "SIMULADO.",
        "papel": "payment",
        "preco_usd": 0.45,
        "simulado": True,
        "escrow": False,
        "estrategia": "Mais barato porque não segura o dinheiro. Quem contratar assume o "
                      "risco de pagar antes das condições.",
        "skills": [{"id": CUSTODIA_PAGAMENTO,
                    "description": "Paga direto o vendedor, sem reserva.",
                    "entrada": {"rodada_id": "str", "property_id": "str",
                                "valor_brl": "número", "condicoes": "lista"},
                    "saida": {"escrow_id": "str", "lancamentos": "lista", "liberado": "bool"}}],
    },
]


def ficha_do_seller(imovel: dict) -> dict:
    seller = imovel["seller_agent"]
    return {
        "agente_id": f"seller-{seller}",
        "name": f"Vendedor {seller}",
        "description": f"Agente do vendedor do imóvel {imovel['property_id']} "
                       f"({imovel['tipo']} em {imovel['bairro']}). Negocia em nome do "
                       f"proprietário e tem piso de preço e pressa próprios, que não revela.",
        "papel": "seller",
        "preco_usd": 0.0,
        "estrategia": "Defende o piso do proprietário. Aceita, contrapropõe ou rejeita.",
        "property_id": imovel["property_id"],
        "skills": [{"id": NEGOCIAR_VENDA,
                    "description": f"Responde a uma oferta pelo imóvel {imovel['property_id']}.",
                    "entrada": {"oferta": "número", "mensagem": "texto", "rodada": "número",
                                "historico": "lista"},
                    "saida": {"acao": "aceita | contraproposta | rejeita", "valor": "número",
                              "mensagem": "texto", "motivo": "texto"},
                    "property_id": imovel["property_id"]}],
    }


def todas_as_fichas() -> list[dict]:
    fichas = []
    for ficha in FICHAS_FIXAS:
        ficha = dict(ficha)
        ficha["url"] = _url(ficha["agente_id"])
        ficha["capacidade_neuralake"] = config.capacidade(ficha["agente_id"])
        fichas.append(ficha)
    for imovel in dados.imoveis():
        ficha = ficha_do_seller(imovel)
        ficha["url"] = _url(ficha["agente_id"])
        ficha["capacidade_neuralake"] = config.capacidade("seller")
        fichas.append(ficha)
    return fichas


def ficha(agente_id: str) -> dict | None:
    for f in todas_as_fichas():
        if f["agente_id"] == agente_id:
            return f
    return None
