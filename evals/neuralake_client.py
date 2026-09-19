"""Cliente mínimo da API da NeuraLake, para o alvo "prompt" das avaliações.

Diferença de propósito em relação a `nucleo/neuralake.py` (repo `neura-challenge`):
aquele cliente existe para o SISTEMA funcionar bem em produção, então ele
esconde falha de `auto` caindo para `text` (plano B) e repete corpo vazio.
Este cliente existe para MEDIR `auto` (e as outras capacidades) sem essa
rede de proteção: uma chamada lógica = uma chamada HTTP, sem retry escondido.
Repetição faz parte do desenho do avaliador (`--repeticoes N`), não deste
módulo -- é assim que "casos instáveis" aparecem de verdade.

A chave NUNCA é registrada: só entra no cabeçalho `Authorization` da chamada e
não é devolvida em nenhum campo do resultado.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from evals import config

_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)


def remover_think(texto: str) -> str:
    if not texto:
        return texto
    return _THINK_RE.sub("", texto).strip()


def extrair_json(texto: str) -> str | None:
    """Maior bloco JSON equilibrado dentro de um texto sujo. Copiado (mesma
    lógica) de `nucleo/neuralake.py::extrair_json`, lido em 19/09/2026."""
    if not texto:
        return None
    melhor: str | None = None
    tamanho = len(texto)
    i = 0
    while i < tamanho:
        if texto[i] in "{[":
            profundidade = 0
            dentro_string = False
            escapando = False
            j = i
            while j < tamanho:
                c = texto[j]
                if dentro_string:
                    if escapando:
                        escapando = False
                    elif c == "\\":
                        escapando = True
                    elif c == '"':
                        dentro_string = False
                else:
                    if c == '"':
                        dentro_string = True
                    elif c in "{[":
                        profundidade += 1
                    elif c in "}]":
                        profundidade -= 1
                        if profundidade == 0:
                            candidato = texto[i:j + 1]
                            if melhor is None or len(candidato) > len(melhor):
                                melhor = candidato
                            break
                j += 1
        i += 1
    return melhor


@dataclass
class ResultadoBruto:
    ok: bool
    texto: str = ""
    modelo_usado: str = ""
    custo_usd: float = 0.0
    tokens_entrada: int | None = None
    tokens_saida: int | None = None
    latencia_ms: int = 0
    http_status: int | None = None
    erro_tipo: str | None = None       # None | timeout | http_erro | rede | corpo_nao_json
    resposta_bruta: dict = field(default_factory=dict)  # já sem cabeçalhos, nunca tem a chave


async def chamar(mensagens: list[dict], *, capacidade: str, api_key: str,
                 max_tokens: int = 1200, temperature: float = 0.3,
                 timeout: float | None = None) -> ResultadoBruto:
    timeout = timeout if timeout is not None else config.TIMEOUT_S
    inicio = time.monotonic()
    corpo = {"model": capacidade, "messages": mensagens,
             "max_tokens": max_tokens, "temperature": temperature}
    try:
        async with httpx.AsyncClient() as cliente:
            resposta = await cliente.post(
                config.BASE_URL_NEURALAKE,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=corpo, timeout=timeout,
            )
    except httpx.TimeoutException:
        return ResultadoBruto(ok=False, erro_tipo="timeout",
                              latencia_ms=int((time.monotonic() - inicio) * 1000))
    except httpx.HTTPError as erro:
        return ResultadoBruto(ok=False, erro_tipo="rede",
                              texto=str(erro)[:300],
                              latencia_ms=int((time.monotonic() - inicio) * 1000))

    latencia_ms = int((time.monotonic() - inicio) * 1000)

    if resposta.status_code >= 400:
        # A NeuraLake devolve erro em 3 formatos: string, objeto, HTML. Nunca
        # confiar em .json() sem checar o Content-Type antes.
        content_type = resposta.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                corpo_erro = resposta.json()
            except ValueError:
                corpo_erro = {"bruto": resposta.text[:500]}
        else:
            corpo_erro = {"bruto_nao_json": resposta.text[:500]}
        return ResultadoBruto(ok=False, erro_tipo="http_erro", http_status=resposta.status_code,
                              texto=str(corpo_erro)[:500], latencia_ms=latencia_ms,
                              resposta_bruta=corpo_erro if isinstance(corpo_erro, dict) else {})

    try:
        bruto = resposta.json()
    except ValueError:
        return ResultadoBruto(ok=False, erro_tipo="corpo_nao_json", http_status=resposta.status_code,
                              texto=resposta.text[:500], latencia_ms=latencia_ms)

    escolha = (bruto.get("choices") or [{}])[0]
    texto_bruto = (escolha.get("message") or {}).get("content") or ""
    uso = bruto.get("usage") or {}
    return ResultadoBruto(
        ok=True, texto=texto_bruto, modelo_usado=str(bruto.get("model") or capacidade),
        custo_usd=float(uso.get("estimated_cost") or 0.0),
        tokens_entrada=uso.get("prompt_tokens"), tokens_saida=uso.get("completion_tokens"),
        latencia_ms=latencia_ms, http_status=resposta.status_code, resposta_bruta=bruto,
    )
