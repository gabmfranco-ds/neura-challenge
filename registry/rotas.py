"""Registry: o marketplace de agentes.

É a ÚNICA URL que o Orchestrator conhece. Ele procura por CAPACIDADE (o `id` de
uma skill), nunca por nome de agente, e recebe de volta a ficha de cada
concorrente junto com o histórico de entregas verificadas.

Agente novo entra sozinho: basta um `POST /registry/agentes` com a ficha. É
assim que os agentes deste repositório se cadastram no boot, e é assim que um
agente de fora entraria sem ninguém mexer em código.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from nucleo import db

router = APIRouter(prefix="/registry", tags=["registry"])


@router.post("/agentes")
async def cadastrar(card: dict) -> dict:
    agente_id = card.get("agente_id") or card.get("name")
    if not agente_id:
        raise HTTPException(status_code=400, detail="ficha sem agente_id")
    if not card.get("skills"):
        raise HTTPException(status_code=400, detail="ficha sem skills: ninguém acharia esse agente")
    if not card.get("url"):
        raise HTTPException(status_code=400, detail="ficha sem url: ninguém conseguiria contratar")
    db.cadastrar_card(agente_id, card)
    db.abrir_carteira(agente_id, card.get("name") or agente_id, 5.0)
    return {"cadastrado": agente_id, "capacidades": [s["id"] for s in card["skills"]]}


@router.get("/agentes")
async def listar(capacidade: str | None = None, property_id: str | None = None) -> dict:
    saida = []
    for card in db.cards():
        skills = card.get("skills") or []
        if capacidade and not any(s.get("id") == capacidade for s in skills):
            continue
        if property_id and card.get("property_id") != property_id:
            continue
        saida.append({**card, "historico": db.historico(card["agente_id"])})
    return {"capacidade": capacidade, "total": len(saida), "agentes": saida}


@router.get("/agentes/{agente_id}")
async def obter(agente_id: str) -> dict:
    card = db.card(agente_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"agente {agente_id} não está no registry")
    return {**card, "historico": db.historico(agente_id)}


@router.post("/recibos")
async def publicar_recibo(recibo: dict) -> dict:
    """O Orchestrator publica aqui o resultado verificado de cada entrega.

    É isto, e só isto, que forma o histórico que os próximos contratantes leem.
    Recibo ruim derruba o histórico do agente na hora.
    """
    for campo in ("id", "agente_id", "skill", "itens_pedidos", "itens_provados",
                  "preco_usd", "pago_usd", "retido_usd"):
        if campo not in recibo:
            raise HTTPException(status_code=400, detail=f"recibo sem campo {campo}")
    db.salvar_recibo(recibo)
    return {"publicado": recibo["id"], "historico": db.historico(recibo["agente_id"])}


@router.get("/recibos")
async def listar_recibos(agente_id: str | None = None) -> dict:
    return {"recibos": db.recibos(agente_id)}
