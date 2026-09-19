"""Payment Agents. Dois concorrentes, com estratégias opostas declaradas.

SIMULADO: nenhum dinheiro de verdade se move, não existe banco, não existe
blockchain. O que existe é um razão de escrow em sqlite, lançamento a
lançamento, que a tela mostra.

- `Escrow Guardião` reserva os fundos e só libera depois de conferir as
  condições precedentes POR CÓDIGO.
- `Liquida Já` declarou na ficha que não faz custódia. Ele é mais barato e o
  Orchestrator sabe disso antes de contratar: quem exige escrow no mandato do
  comprador não contrata ele.
"""
from __future__ import annotations

from nucleo import db, verificacao


async def executar(ficha: dict, skill: str, entrada: dict, rodada_id: str | None) -> dict:
    if skill != "custodia_pagamento":
        raise ValueError(f"skill desconhecida para o payment: {skill!r}")

    acao = (entrada.get("acao") or "reservar").strip().lower()
    faz_escrow = bool(ficha.get("escrow"))
    valor_brl = float(entrada.get("valor_brl") or 0)
    rodada = entrada.get("rodada_id") or rodada_id or "sem-rodada"

    if acao == "reservar":
        if not faz_escrow:
            return {"escrow_id": None, "reservado": False, "simulado": True,
                    "observacao": "este agente não faz custódia: nada foi reservado",
                    "saldo_escrow": 0.0, "custo_usd": 0.0}
        lancamento = db.lancar_escrow(rodada, "reserva", valor_brl,
                                      f"fundos reservados para o imóvel {entrada.get('property_id')}")
        return {"escrow_id": lancamento, "reservado": True, "simulado": True,
                "saldo_escrow": db.saldo_escrow(rodada),
                "observacao": "reserva SIMULADA, registrada no razão de escrow",
                "custo_usd": 0.0}

    if acao == "conferir_e_liberar":
        condicoes = entrada.get("condicoes") or []
        conferencia = verificacao.conferir_condicoes(condicoes, ate_fase="CONDITIONS_MET")
        if not faz_escrow:
            db.lancar_escrow(rodada, "liberacao", valor_brl,
                             "pagamento direto ao vendedor, sem conferência (estratégia declarada)")
            return {"liberado": True, "conferencia": conferencia, "simulado": True,
                    "saldo_escrow": db.saldo_escrow(rodada),
                    "observacao": "liberado sem conferir condições, como a ficha declara",
                    "custo_usd": 0.0}
        if not conferencia["aprovado"]:
            nomes = ", ".join(p["nome"] for p in conferencia["pendentes"][:3])
            return {"liberado": False, "conferencia": conferencia, "simulado": True,
                    "saldo_escrow": db.saldo_escrow(rodada),
                    "observacao": f"pagamento NÃO liberado: condição pendente ({nomes})",
                    "custo_usd": 0.0}
        db.lancar_escrow(rodada, "liberacao", valor_brl,
                         f"todas as {conferencia['obrigatorias']} condições obrigatórias conferidas")
        return {"liberado": True, "conferencia": conferencia, "simulado": True,
                "saldo_escrow": db.saldo_escrow(rodada),
                "observacao": "pagamento SIMULADO liberado após conferência por código",
                "custo_usd": 0.0}

    raise ValueError(f"ação desconhecida para o payment: {acao!r}")
