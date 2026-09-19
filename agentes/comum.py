"""Ajudas que todo agente usa: o prompt de sistema sai da PRÓPRIA FICHA.

Isso é regra dura do projeto: o comportamento de um agente vem da ficha que ele
publicou no Registry, não de um atalho no código. Trocar a estratégia declarada
troca o comportamento; nenhum `if` decide por ele o que ele vai responder.
"""
from __future__ import annotations

from nucleo import config, db, neuralake


def sistema(ficha: dict, extra: str = "") -> dict:
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


def abrir_carteira(ficha: dict) -> None:
    db.abrir_carteira(ficha["agente_id"], ficha["name"], config.ORCAMENTO_PADRAO_USD)


async def pedir_json(ficha: dict, mensagens: list[dict], *, etapa: str,
                     rodada_id: str | None, max_tokens: int = 1200,
                     temperature: float = 0.3):
    abrir_carteira(ficha)
    return await neuralake.pedir_json(
        mensagens, agente_id=ficha["agente_id"], agente_nome=ficha["name"], etapa=etapa,
        rodada_id=rodada_id, capacidade=ficha.get("capacidade_neuralake", "auto"),
        max_tokens=max_tokens, temperature=temperature,
    )


def dinheiro(valor: float | int | None) -> str:
    if valor is None:
        return "-"
    return f"R$ {valor:,.0f}".replace(",", ".")
