"""Superfície HTTP de todos os agentes.

Cada agente tem URL própria (`/agentes/{slug}`), ficha própria em
`/.well-known/agent-card.json` e recebe trabalho em `POST /tarefas`. Os agentes
conversam entre si por HTTP mesmo rodando no mesmo processo: mover um deles para
outra máquina muda a URL na ficha, não o código.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from agentes import catalogo
from agentes.buyer import agente as buyer
from agentes.payment import agente as payment
from agentes.property import agente as property_
from agentes.seller import agente as seller
from agentes.transaction import agente as transaction

logger = logging.getLogger("neura.agentes")

router = APIRouter(prefix="/agentes", tags=["agentes"])

EXECUTORES = {
    "buyer": buyer.executar,
    "property": property_.executar,
    "seller": seller.executar,
    "transaction": transaction.executar,
    "payment": payment.executar,
}


def _ficha(slug: str) -> dict:
    ficha = catalogo.ficha(slug)
    if ficha is None:
        raise HTTPException(status_code=404, detail=f"agente desconhecido: {slug}")
    return ficha


@router.get("/{slug}/.well-known/agent-card.json")
async def agent_card(slug: str) -> dict:
    return _ficha(slug)


@router.post("/{slug}/tarefas")
async def tarefas(slug: str, corpo: dict) -> dict:
    ficha = _ficha(slug)
    skill = corpo.get("skill")
    if not any(s["id"] == skill for s in ficha["skills"]):
        raise HTTPException(status_code=400,
                            detail=f"{ficha['name']} não publica a skill {skill!r}")
    executor = EXECUTORES.get(ficha["papel"])
    if executor is None:
        raise HTTPException(status_code=500, detail=f"papel sem executor: {ficha['papel']}")

    try:
        saida = await executor(ficha, skill, corpo.get("entrada") or {}, corpo.get("rodada_id"))
    except Exception as erro:  # a rodada não pode morrer por causa de um agente
        logger.exception("agente %s falhou na skill %s", slug, skill)
        raise HTTPException(status_code=502, detail=f"{ficha['name']} falhou: {erro}") from erro

    custo = float(saida.pop("custo_usd", 0.0) or 0.0)
    return {"agente_id": ficha["agente_id"], "agente_nome": ficha["name"],
            "skill": skill, "saida": saida, "custo_usd": custo,
            "simulado": bool(ficha.get("simulado"))}
