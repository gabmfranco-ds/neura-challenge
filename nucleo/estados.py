"""Máquina de estados da compra. Os nomes são os que o time congelou, em inglês.

Quem tenta um salto inválido leva `TransicaoInvalida`. Isso é de propósito: o
trilho da tela é esta tabela, e um estado que aparece fora de ordem seria um
defeito escondido.
"""
from __future__ import annotations

INICIAL = "SEARCH"

# Caminho feliz, na ordem em que a tela desenha o trilho.
TRILHO = [
    "SEARCH", "SHORTLIST", "PROPERTY_SELECTED", "OFFER_CREATED", "OFFER_SENT",
    "COUNTER_OFFER", "OFFER_ACCEPTED", "KYC_PENDING", "DOCUMENTS_VERIFIED",
    "CONTRACT_SIGNED", "FUNDS_LOCKED", "CONDITIONS_MET", "PAYMENT_RELEASED",
    "PROPERTY_TRANSFERRED", "COMPLETED",
]

# Saídas de falha. Sempre com motivo.
FALHAS = ["OFFER_REJECTED", "ABORTED"]

TERMINAIS = {"COMPLETED", "ABORTED"}

TRANSICOES: dict[str, set[str]] = {
    "SEARCH": {"SHORTLIST", "ABORTED"},
    # SHORTLIST volta para SEARCH quando a verificação reprova a entrega inteira
    # e o Orchestrator precisa contratar outro agente e buscar de novo.
    "SHORTLIST": {"PROPERTY_SELECTED", "SEARCH", "ABORTED"},
    "PROPERTY_SELECTED": {"OFFER_CREATED", "ABORTED"},
    "OFFER_CREATED": {"OFFER_SENT", "ABORTED"},
    "OFFER_SENT": {"COUNTER_OFFER", "OFFER_ACCEPTED", "OFFER_REJECTED", "ABORTED"},
    "COUNTER_OFFER": {"OFFER_SENT", "OFFER_ACCEPTED", "OFFER_REJECTED", "ABORTED"},
    "OFFER_ACCEPTED": {"KYC_PENDING", "ABORTED"},
    "KYC_PENDING": {"DOCUMENTS_VERIFIED", "ABORTED"},
    "DOCUMENTS_VERIFIED": {"CONTRACT_SIGNED", "ABORTED"},
    "CONTRACT_SIGNED": {"FUNDS_LOCKED", "ABORTED"},
    "FUNDS_LOCKED": {"CONDITIONS_MET", "ABORTED"},
    "CONDITIONS_MET": {"PAYMENT_RELEASED", "ABORTED"},
    "PAYMENT_RELEASED": {"PROPERTY_TRANSFERRED", "ABORTED"},
    "PROPERTY_TRANSFERRED": {"COMPLETED"},
    "COMPLETED": set(),
    # Recusa não é fim de jogo: o comprador pode escolher outro imóvel da shortlist.
    "OFFER_REJECTED": {"SHORTLIST", "ABORTED"},
    "ABORTED": set(),
}

TODOS = set(TRILHO) | set(FALHAS)


class TransicaoInvalida(RuntimeError):
    pass


def pode(de: str, para: str) -> bool:
    return para in TRANSICOES.get(de, set())


def exigir(de: str, para: str) -> None:
    if de not in TRANSICOES:
        raise TransicaoInvalida(f"estado desconhecido: {de!r}")
    if para not in TODOS:
        raise TransicaoInvalida(f"estado desconhecido: {para!r}")
    if not pode(de, para):
        raise TransicaoInvalida(f"transição inválida: {de} -> {para}")
