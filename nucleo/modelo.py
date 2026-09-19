"""O modelo da NeuraLake visto pelo Agno, com o que o Agno não entrega sozinho.

O Agno fala com a NeuraLake por `OpenAILike` (formato OpenAI, `base_url` da
NeuraLake, `id="auto"`). Duas coisas que a gente precisa e o Agno 3.0.10 NÃO
devolve, medido em 19/09:

1. **`usage.estimated_cost`**: o `RunMetrics` do Agno vem com `cost=None` e
   `provider_metrics=None`. Sem esse número não existe carteira em dólar real.
2. **qual modelo a NeuraLake escolheu**: o Agno repete o `id` que a gente
   mandou (`auto`), não o campo `model` que veio na resposta.

A saída é um `httpx.AsyncClient` com gancho de resposta, entregue ao Agno pelo
parâmetro `http_client`. O gancho lê o corpo cru de cada chamada e guarda custo
e modelo roteado numa caixa por contexto. Nada de chave, nada de cabeçalho: o
gancho só olha `usage` e `model`.

O mesmo cliente carrega o timeout de 25 s que o time combinou.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os

import httpx
from agno.models.openai.like import OpenAILike

logger = logging.getLogger("neura.modelo")

BASE_URL = "https://api.neuralake.cloud/v1"
TIMEOUT_S = 25.0

# Lista mutável por contexto. Quem vai chamar cria a caixa ANTES da chamada e lê
# depois; o gancho só acrescenta. Como é a mesma lista, a leitura funciona mesmo
# se o httpx copiar o contexto.
_CAIXA: contextvars.ContextVar[list | None] = contextvars.ContextVar("neura_caixa", default=None)


class ErroNeuraLake(RuntimeError):
    pass


def chave_api() -> str:
    chave = os.environ.get("NEURALAKE_API_KEY")
    if not chave:
        raise ErroNeuraLake(
            "NEURALAKE_API_KEY não está definida no ambiente. "
            "Defina a variável antes de subir o servidor (veja o README)."
        )
    return chave


def abrir_caixa() -> list:
    caixa: list = []
    _CAIXA.set(caixa)
    return caixa


async def _gancho(resposta: httpx.Response) -> None:
    caixa = _CAIXA.get()
    if caixa is None:
        return
    try:
        await resposta.aread()
        if not resposta.headers.get("content-type", "").startswith("application/json"):
            return
        corpo = json.loads(resposta.text)
    except Exception:
        # Erro da NeuraLake vem em três formatos, um deles é página HTML.
        # Falha de leitura aqui não pode derrubar a chamada.
        return
    uso = corpo.get("usage") or {}
    caixa.append({
        "custo_usd": float(uso.get("estimated_cost") or 0.0),
        "modelo_roteado": str(corpo.get("model") or ""),
        "finish_reason": ((corpo.get("choices") or [{}])[0] or {}).get("finish_reason"),
        "status": resposta.status_code,
    })


_CLIENTE: httpx.AsyncClient | None = None


def cliente_http() -> httpx.AsyncClient:
    global _CLIENTE
    if _CLIENTE is None or _CLIENTE.is_closed:
        _CLIENTE = httpx.AsyncClient(timeout=TIMEOUT_S, event_hooks={"response": [_gancho]})
    return _CLIENTE


_MODELOS: dict[str, OpenAILike] = {}


def modelo(capacidade: str = "auto") -> OpenAILike:
    """Um modelo por capacidade, reaproveitado. `auto` é o padrão em tudo."""
    if capacidade not in _MODELOS:
        _MODELOS[capacidade] = OpenAILike(
            id=capacidade,
            api_key=chave_api(),
            base_url=BASE_URL,
            timeout=TIMEOUT_S,
            http_client=cliente_http(),
        )
    return _MODELOS[capacidade]


def resumo_da_caixa(caixa: list) -> dict:
    """Soma o custo de todas as chamadas HTTP que uma chamada lógica precisou."""
    custo = round(sum(c["custo_usd"] for c in caixa), 8)
    modelos = [c["modelo_roteado"] for c in caixa if c["modelo_roteado"]]
    return {
        "custo_usd": custo,
        "modelo_roteado": modelos[-1] if modelos else "",
        "chamadas_http": len(caixa),
    }
