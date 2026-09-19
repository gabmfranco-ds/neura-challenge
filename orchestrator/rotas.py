"""Rotas do Orchestrator. É o que a tela chama.

O humano só toca em três destas rotas: criar a rodada com a frase, escolher um
imóvel da shortlist e autorizar a oferta com um teto. O resto é leitura.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from nucleo import db, estados, reprise
from orchestrator import memoria, motor

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


def _rodada(rodada_id: str) -> motor.Rodada:
    rodada = motor.obter(rodada_id)
    if rodada is None:
        raise HTTPException(status_code=404, detail=f"rodada {rodada_id} não existe")
    return rodada


@router.post("/rodadas")
async def criar_rodada(corpo: dict) -> dict:
    frase = (corpo.get("frase") or "").strip()
    if not frase:
        raise HTTPException(status_code=400, detail="mande a frase do comprador")
    rodada = await motor.iniciar(frase)
    return {"rodada_id": rodada.id, "estado": rodada.estado}


@router.get("/rodadas")
async def listar_rodadas() -> dict:
    return {"rodadas": [motor.rodada_json(r) for r in motor.RODADAS.values()]}


@router.get("/rodadas/{rodada_id}")
async def obter_rodada(rodada_id: str) -> dict:
    return motor.rodada_json(_rodada(rodada_id))


@router.post("/rodadas/{rodada_id}/escolha")
async def escolher(rodada_id: str, corpo: dict) -> dict:
    """Segundo ato do humano. Também serve para escolher OUTRO imóvel quando a
    negociação do anterior terminou sem acordo."""
    rodada = _rodada(rodada_id)
    property_id = (corpo.get("property_id") or "").strip()
    try:
        motor.escolher(rodada, property_id)
    except (ValueError, estados.TransicaoInvalida) as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from erro
    return motor.rodada_json(rodada)


@router.post("/rodadas/{rodada_id}/oferta")
async def ofertar(rodada_id: str, corpo: dict) -> dict:
    rodada = _rodada(rodada_id)
    if rodada.estado != "PROPERTY_SELECTED":
        raise HTTPException(status_code=400,
                            detail=f"a rodada está em {rodada.estado}, não dá para ofertar")
    try:
        teto = int(corpo.get("teto_preco"))
    except (TypeError, ValueError) as erro:
        raise HTTPException(status_code=400, detail="mande teto_preco em reais") from erro
    oferta_min = corpo.get("oferta_min")
    try:
        oferta_min = int(oferta_min) if oferta_min not in (None, "") else None
    except (TypeError, ValueError) as erro:
        raise HTTPException(status_code=400,
                            detail="oferta_min, se vier, é número em reais") from erro
    if oferta_min is not None and oferta_min > teto:
        raise HTTPException(status_code=400,
                            detail="a oferta mínima não pode ser maior que o teto")
    await motor.ofertar(rodada, teto, int(corpo.get("prazo_dias") or 60), oferta_min)
    return motor.rodada_json(rodada)


@router.get("/eventos")
async def eventos(since: int = 0, rodada_id: str | None = None) -> dict:
    lista = db.eventos_desde(since, rodada_id)
    return {"ao_vivo": True, "eventos": lista,
            "ultimo_seq": lista[-1]["seq"] if lista else since}


@router.get("/carteiras")
async def carteiras() -> dict:
    return {"carteiras": db.carteiras(), "memoria_buscas": memoria.tamanho()}


@router.get("/trilho")
async def trilho() -> dict:
    return {"trilho": estados.TRILHO, "falhas": estados.FALHAS}


# ------------------------------------------------------------------ reprise

@router.get("/reprises")
async def listar_reprises() -> dict:
    return {"gravacoes": reprise.listar()}


@router.post("/reprises")
async def abrir_reprise(corpo: dict) -> dict:
    arquivo = (corpo.get("arquivo") or "").strip()
    if not arquivo:
        raise HTTPException(status_code=400, detail="mande o nome do arquivo da gravação")
    try:
        return reprise.iniciar_sessao(arquivo, float(corpo.get("velocidade") or 1.0))
    except FileNotFoundError as erro:
        raise HTTPException(status_code=404, detail=str(erro)) from erro


@router.get("/reprises/{sessao_id}/eventos")
async def eventos_reprise(sessao_id: str, since: int = 0) -> dict:
    try:
        return reprise.eventos(sessao_id, since)
    except KeyError as erro:
        raise HTTPException(status_code=404, detail=str(erro)) from erro


@router.delete("/reprises/{sessao_id}")
async def fechar_reprise(sessao_id: str) -> dict:
    reprise.encerrar(sessao_id)
    return {"encerrada": sessao_id}
