"""Um processo, todos os agentes, cada um com URL própria.

Sobe em `http://127.0.0.1:8787`:

  /                     a tela
  /registry/...         o marketplace
  /orchestrator/...     o orquestrador (é o que a tela chama)
  /agentes/{slug}/...   cada agente, com ficha em /.well-known/agent-card.json

No boot, cada agente se cadastra sozinho no Registry por HTTP, exatamente como
um agente de fora faria. Se a rede local falhar, cai para o cadastro direto e
diz isso no log.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agentes import catalogo
from agentes.rotas import router as router_agentes
from nucleo import config, db
from orchestrator.rotas import router as router_orchestrator
from registry.rotas import router as router_registry

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("neura.servidor")

app = FastAPI(title="Neura Challenge - Agent Marketplace de imóveis", version="1.0")
app.include_router(router_registry)
app.include_router(router_orchestrator)
app.include_router(router_agentes)


@app.get("/saude")
async def saude() -> dict:
    return {"ok": True, "agentes_no_registry": len(db.cards()),
            "chave_no_ambiente": bool(os.environ.get("NEURALAKE_API_KEY"))}


@app.get("/dados/medianas")
async def medianas() -> dict:
    from nucleo import dados
    return {"medianas_por_bairro_m2": dados.medianas(),
            "total_imoveis": len(dados.imoveis()),
            "aviso": "base de demonstração inventada, ver dados/LEIAME.md"}


async def _cadastrar_agentes() -> None:
    """Cada agente publica a própria ficha no Registry. Sozinho, por HTTP."""
    await asyncio.sleep(0.4)  # deixa o uvicorn terminar de abrir a porta
    fichas = catalogo.todas_as_fichas()
    cadastrados = 0
    async with httpx.AsyncClient(timeout=10.0) as cliente:
        for ficha in fichas:
            try:
                resposta = await cliente.post(f"{config.BASE_URL}/registry/agentes", json=ficha)
                resposta.raise_for_status()
                cadastrados += 1
            except Exception:
                db.cadastrar_card(ficha["agente_id"], ficha)
                db.abrir_carteira(ficha["agente_id"], ficha["name"], config.ORCAMENTO_PADRAO_USD)
                logger.warning("agente %s não conseguiu se cadastrar por HTTP; cadastrei direto",
                               ficha["agente_id"])
    logger.info("%s de %s agentes se cadastraram sozinhos no Registry", cadastrados, len(fichas))


@app.on_event("startup")
async def ao_subir() -> None:
    if not os.environ.get("NEURA_MANTER_BANCO"):
        db.resetar()
    db.abrir_carteira("orchestrator", "Orquestrador", config.ORCAMENTO_PADRAO_USD * 4)
    if not os.environ.get("NEURALAKE_API_KEY"):
        logger.warning("NEURALAKE_API_KEY não está no ambiente: os agentes vão falhar ao "
                       "chamar a NeuraLake. Veja o README.")
    asyncio.create_task(_cadastrar_agentes())


@app.exception_handler(Exception)
async def erro_geral(request, erro: Exception) -> JSONResponse:
    logger.exception("erro não tratado em %s", request.url.path)
    return JSONResponse(status_code=500, content={"erro": str(erro)})


app.mount("/", StaticFiles(directory=str(config.RAIZ / "tela"), html=True), name="tela")
