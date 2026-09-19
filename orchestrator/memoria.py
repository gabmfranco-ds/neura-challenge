"""Memória de buscas do Orchestrator. Eficiência sem truque.

Uma busca que já foi feita E verificada fica guardada por assinatura do pedido.
Um segundo comprador com pedido parecido reaproveita o resultado verificado e
não gasta nenhuma chamada de modelo na busca. A tela mostra os dois custos lado
a lado.

Isto é memória NOSSA, do Orchestrator. Não é recurso da NeuraLake.
"""
from __future__ import annotations

_MEMORIA: dict[str, dict] = {}

FAIXA_PRECO = 250_000


def assinatura(pedido: dict) -> str:
    """Pedidos parecidos caem na mesma assinatura: mesma cidade, mesmos bairros,
    mesma faixa de preço (blocos de R$ 250 mil, pelo mais próximo) e mesmos
    mínimos."""
    bairros = ",".join(sorted(b.lower() for b in (pedido.get("bairros") or [])))
    preco = pedido.get("preco_max") or 0
    # Arredonda para a faixa mais PRÓXIMA, não para a de baixo: com corte duro,
    # R$ 1,95 milhão e R$ 2 milhões caíam em faixas diferentes e a memória
    # perdia um pedido que é o mesmo pedido.
    faixa = int(round(preco / FAIXA_PRECO))
    return "|".join([
        str(pedido.get("tipo") or ""),
        str(pedido.get("cidade") or "").lower(),
        bairros,
        f"faixa{faixa}",
        f"q{pedido.get('quartos_min') or 0}",
        f"v{pedido.get('vagas_min') or 0}",
        f"a{int((pedido.get('area_min') or 0) // 20)}",
    ])


def guardar(pedido: dict, shortlist: list[dict], custo_usd: float, rodada_id: str) -> None:
    _MEMORIA[assinatura(pedido)] = {
        "shortlist": shortlist, "custo_original_usd": round(custo_usd, 6),
        "rodada_id": rodada_id, "pedido": pedido,
    }


def buscar(pedido: dict) -> dict | None:
    return _MEMORIA.get(assinatura(pedido))


def limpar() -> None:
    _MEMORIA.clear()


def tamanho() -> int:
    return len(_MEMORIA)
