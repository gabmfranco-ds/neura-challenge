"""Transaction Agents. Dois concorrentes na mesma capacidade.

SIMULADO e DETERMINÍSTICO de ponta a ponta: KYC, contrato e escritura aqui são
carimbos, não atos jurídicos, e a tela diz isso em todo lugar. Nenhum LLM
redige contrato neste projeto (decisão do time: contrato escrito por modelo não
é valor de negócio, é risco).

A diferença entre os dois está na ficha:

- `Cartório Digital` confere as condições documentais contra os documentos do
  imóvel, uma a uma, e marca só o que o documento sustenta.
- `Fecha Rápido` declarou que não confere documentação: marca KYC, contrato e
  preço, e deixa o resto pendente. Quem contrata sabe o que está comprando.
"""
from __future__ import annotations

import datetime as dt

from nucleo import dados, db, verificacao

FONTES_DOCUMENTAIS = {"matricula", "certidao_distribuicao", "certidao_iptu", "condominio"}


async def executar(ficha: dict, skill: str, entrada: dict, rodada_id: str | None) -> dict:
    if skill != "conduzir_transacao":
        raise ValueError(f"skill desconhecida para o transaction: {skill!r}")

    property_id = entrada.get("property_id")
    preco_acordado = entrada.get("preco_acordado")
    mandato = entrada.get("mandato") or {}
    imovel = dados.imovel(property_id)
    if imovel is None:
        raise ValueError(f"imóvel desconhecido: {property_id!r}")

    # A ficha DIZ se este agente confere documentação. Quem contratou leu isso
    # antes de pagar.
    confere_documentos = bool(ficha.get("confere_documentos"))
    analise = verificacao.status_documentacao(property_id)
    catalogo = dados.criterios_fechamento()
    hoje = dt.date.today().strftime("%d/%m/%Y")

    condicoes = []
    for criterio in catalogo["condicoes"]:
        condicoes.append(_avaliar(criterio, analise=analise, mandato=mandato,
                                  preco_acordado=preco_acordado,
                                  confere_documentos=confere_documentos, hoje=hoje))

    custos = _custos(preco_acordado or imovel["preco"], catalogo.get("custos_estimados") or {})
    contrato = {
        "id": db.novo_id("ctr-"),
        "property_id": property_id,
        "preco_acordado": preco_acordado,
        "resumo": (f"Promessa de compra e venda do imóvel {property_id}, "
                   f"{imovel['tipo']} em {imovel['bairro']}, por R$ {preco_acordado:,.0f}"
                   .replace(",", ".") if preco_acordado else "sem preço acordado"),
        "assinado_em": hoje,
        "simulado": True,
        "conduzido_por": ficha["name"],
    }
    kyc = {
        "comprador": "aprovado",
        "vendedor": "aprovado",
        "simulado": True,
        "observacao": "KYC simulado: nenhum documento de identidade real foi checado.",
    }
    return {
        "kyc": kyc,
        "contrato": contrato,
        "condicoes": condicoes,
        "custos_estimados": custos,
        "analise_documental": analise if confere_documentos else
                              {"status": "nao_conferido",
                               "pendencias": ["o agente contratado não confere documentação"]},
        "simulado": True,
        "custo_usd": 0.0,
    }


def _avaliar(criterio: dict, *, analise: dict, mandato: dict, preco_acordado,
             confere_documentos: bool, hoje: str) -> dict:
    base = {"id": criterio["id"], "nome": criterio["nome"], "fase": criterio["fase"],
            "obrigatoria": criterio["obrigatoria"], "prova": criterio["prova"],
            "simulado": criterio["prova"] == "simulado"}
    fonte = criterio.get("fonte")

    if fonte in FONTES_DOCUMENTAIS:
        if not confere_documentos:
            return {**base, "status": "pendente",
                    "motivo": "fora do escopo contratado: este agente não confere documentação"}
        if analise["status"] == verificacao.STATUS_SEM_DOCUMENTOS:
            return {**base, "status": "pendente", "motivo": "não há documentos na base"}
        pendencias = (analise.get("pendencias_por_fonte") or {}).get(fonte) or []
        if pendencias:
            return {**base, "status": "pendente", "motivo": pendencias[0]}
        return {**base, "status": "atendida",
                "motivo": f"conferido no documento do imóvel em {hoje}"}

    if criterio["id"] == "preco_dentro_do_mandato":
        conferencia = verificacao.conferir_mandato(preco_acordado, mandato)
        if conferencia["aprovado"]:
            return {**base, "status": "atendida",
                    "motivo": f"preço acordado cabe no teto autorizado pelo comprador"}
        return {**base, "status": "pendente", "motivo": conferencia["motivos"][0]}

    if criterio["id"] == "financiamento_aprovado":
        return {**base, "status": "atendida",
                "motivo": "carta de crédito simulada, sem banco real"}

    if criterio["id"] in ("kyc_comprador", "kyc_vendedor", "contrato_assinado"):
        return {**base, "status": "atendida", "motivo": f"{criterio['nome']} (simulado) em {hoje}"}

    if not confere_documentos:
        return {**base, "status": "pendente",
                "motivo": "fora do escopo contratado: este agente só fecha o mínimo"}
    return {**base, "status": "atendida", "motivo": f"etapa simulada e carimbada em {hoje}"}


def _custos(preco: float, tabela: dict) -> dict:
    itbi = round(preco * float(tabela.get("itbi_percentual") or 0.03), 2)
    escritura = round(preco * float(tabela.get("escritura_percentual") or 0.012), 2)
    registro = round(preco * float(tabela.get("registro_percentual") or 0.009), 2)
    return {"itbi": itbi, "escritura": escritura, "registro": registro,
            "total": round(itbi + escritura + registro, 2),
            "observacao": "percentuais aproximados, a conferir com o especialista do time"}
