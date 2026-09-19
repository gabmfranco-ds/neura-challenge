"""Leitura da base de demonstração em `dados/`. Roda sem rede.

Duas visões diferentes do mesmo imóvel, de propósito:

- `visao_anuncio`  : o que o anúncio diz. Sem `disponibilidade`, sem documentos.
- `visao_completa` : o anúncio mais o campo de disponibilidade da base e o texto
                     dos documentos.

Qual visão cada Property Agent recebe é **decisão de negócio declarada na ficha
dele**, não um atalho de código: o agente barato vende justamente não abrir
documento nem conferir disponibilidade, e é por isso que ele custa menos.

`_privado_vendedor` (piso de preço, pressa) não aparece em nenhuma das duas: só
o Seller Agent daquele imóvel enxerga.
"""
from __future__ import annotations

import json
import statistics
from functools import lru_cache
from typing import Any

from . import config

CAMPOS_ANUNCIO = (
    "property_id", "tipo", "cidade", "bairro", "endereco", "preco", "area", "quartos",
    "suites", "vagas", "andar", "condominio_mensal", "iptu_anual", "ano_construcao",
    "aceita_financiamento", "caracteristicas", "seller_agent", "texto_anuncio",
)


@lru_cache(maxsize=1)
def imoveis() -> list[dict[str, Any]]:
    caminho = config.PASTA_DADOS / "imoveis.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _por_id() -> dict[str, dict]:
    return {im["property_id"]: im for im in imoveis()}


def imovel(property_id: str) -> dict | None:
    return _por_id().get(property_id)


def imovel_do_seller(seller_agent: str) -> dict | None:
    for im in imoveis():
        if im["seller_agent"] == seller_agent:
            return im
    return None


@lru_cache(maxsize=1)
def criterios_fechamento() -> dict:
    caminho = config.PASTA_DADOS / "criterios-fechamento.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


def documento(property_id: str) -> str | None:
    caminho = config.PASTA_DADOS / "documentos" / f"{property_id}.txt"
    if not caminho.exists():
        return None
    return caminho.read_text(encoding="utf-8")


def visao_anuncio(im: dict) -> dict:
    return {campo: im.get(campo) for campo in CAMPOS_ANUNCIO}


def visao_completa(im: dict) -> dict:
    visao = visao_anuncio(im)
    visao["disponibilidade"] = im.get("disponibilidade")
    visao["documentos"] = documento(im["property_id"])
    return visao


def mediana_bairro(bairro: str) -> float | None:
    """Mediana do preço por m2 do bairro na base. É contra isto que o
    Orchestrator confere a afirmação de preço do Property Agent."""
    valores = [im["preco"] / im["area"] for im in imoveis()
               if im["bairro"].lower() == (bairro or "").lower() and im["area"]]
    if not valores:
        return None
    return round(statistics.median(valores), 2)


def medianas() -> dict[str, float]:
    bairros = sorted({im["bairro"] for im in imoveis()})
    return {b: mediana_bairro(b) or 0.0 for b in bairros}


def filtrar(pedido: dict) -> list[dict]:
    """Filtro plano do pedido estruturado sobre a base. O Property Agent usa
    para não mandar a base inteira ao modelo; o verificador usa para conferir."""
    bairros = [b.lower() for b in (pedido.get("bairros") or [])]
    saida = []
    for im in imoveis():
        if pedido.get("tipo") and im["tipo"] != pedido["tipo"]:
            continue
        if pedido.get("cidade") and _sem_acento(im["cidade"]) != _sem_acento(pedido["cidade"]):
            continue
        if bairros and im["bairro"].lower() not in bairros:
            continue
        if pedido.get("preco_max") and im["preco"] > pedido["preco_max"]:
            continue
        if pedido.get("quartos_min") and im["quartos"] < pedido["quartos_min"]:
            continue
        if pedido.get("vagas_min") and im["vagas"] < pedido["vagas_min"]:
            continue
        if pedido.get("area_min") and im["area"] < pedido["area_min"]:
            continue
        if pedido.get("financiamento") and not im.get("aceita_financiamento"):
            continue
        saida.append(im)
    return saida


def _sem_acento(texto: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn").lower().strip()
