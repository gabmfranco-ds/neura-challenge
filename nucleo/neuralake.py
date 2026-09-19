"""Cliente da API da NeuraLake, com as defesas que já custaram tempo antes.

Formato OpenAI em `POST /v1/chat/completions`. A chave vem SÓ do ambiente
(`NEURALAKE_API_KEY`) e nunca é escrita em evento, gravação, log ou resposta.

Regras desta casa (orientação do mentor da NeuraLake, 19/09):

- **`auto` é o padrão em todas as chamadas de todos os agentes.** Outra
  capacidade só entra como PLANO B, quando `auto` falha de verdade: timeout,
  5xx, ou corpo vazio depois de uma repetição. O plano B fica registrado no
  evento, junto com o motivo.
- Cada chamada registra qual capacidade foi PEDIDA, qual foi USADA, qual modelo
  a NeuraLake devolveu no campo `model` e quanto custou.

Armadilhas já medidas (ver `docs/neuralake-api.md`):

1. `reasoning`/`reasoning-pro`/`multimodal` gastam o teto de tokens pensando e
   devolvem corpo vazio. Subir o teto não resolve sozinho: a defesa é repetir.
2. Corpo vazio às vezes vem com `finish_reason == "stop"` — não dá para gatear
   só em `"length"`.
3. `<think>` vaza dentro do `content` e precisa sair antes de qualquer parsing,
   inclusive quando o fechamento nunca chega.
4. Erro vem em três formatos (string, objeto, página HTML). Nunca fazer
   `.json()` sem checar o status antes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field

import httpx

from . import db

logger = logging.getLogger("neura.neuralake")

BASE_URL = "https://api.neuralake.cloud/v1/chat/completions"
CAPACIDADES_VALIDAS = {"auto", "text", "code", "reasoning", "reasoning-pro", "multimodal"}
CAPACIDADES_QUE_PENSAM = {"reasoning", "reasoning-pro", "multimodal"}
CAPACIDADE_PLANO_B = "text"

TIMEOUT_S = 25.0
TIMEOUT_PENSANTE_S = 90.0
MAX_TOKENS_PADRAO = 1200
MAX_TOKENS_PENSANTE = 3000
TENTATIVAS = 2  # 1 chamada + no máximo 1 repetição, como o time combinou
ERROS_TRANSITORIOS = {500, 502, 503, 504}

_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)


class ErroNeuraLake(RuntimeError):
    pass


def _chave_api() -> str:
    chave = os.environ.get("NEURALAKE_API_KEY")
    if not chave:
        raise ErroNeuraLake(
            "NEURALAKE_API_KEY não está definida no ambiente. "
            "Defina a variável antes de subir o servidor (veja o README)."
        )
    return chave


def remover_think(texto: str) -> str:
    """Tira o bloco <think>...</think>, tolerando abertura sem fechamento."""
    if not texto:
        return texto
    return _THINK_RE.sub("", texto).strip()


def _corpo_vazio(texto_bruto: str) -> bool:
    return len(remover_think(texto_bruto or "").strip()) == 0


@dataclass
class ResultadoChamada:
    texto: str
    custo_usd: float
    capacidade_pedida: str
    capacidade_usada: str
    modelo_roteado: str
    plano_b: bool = False
    motivo_plano_b: str = ""
    tentativas: int = 1
    bruto: dict = field(default_factory=dict)


async def _post(cliente: httpx.AsyncClient, capacidade: str, mensagens: list[dict],
                max_tokens: int, temperature: float, timeout: float) -> dict:
    resposta = await cliente.post(
        BASE_URL,
        headers={"Authorization": f"Bearer {_chave_api()}", "Content-Type": "application/json"},
        json={"model": capacidade, "messages": mensagens,
              "max_tokens": max_tokens, "temperature": temperature},
        timeout=timeout,
    )
    resposta.raise_for_status()
    try:
        return resposta.json()
    except ValueError as erro:
        # 200 com corpo não-JSON: a API já devolveu página HTML em erro de corpo.
        raise ErroNeuraLake(
            f"NeuraLake devolveu 200 com corpo que não é JSON: {resposta.text[:200]!r}"
        ) from erro


async def chamar(
    mensagens: list[dict],
    *,
    agente_id: str,
    agente_nome: str,
    etapa: str,
    rodada_id: str | None = None,
    capacidade: str = "auto",
    max_tokens: int = MAX_TOKENS_PADRAO,
    temperature: float = 0.3,
) -> ResultadoChamada:
    """Uma chamada lógica à NeuraLake. Registra o evento e debita a carteira.

    Ninguém monta a request na mão: quem pular por aqui pula a contabilidade.
    """
    if capacidade not in CAPACIDADES_VALIDAS:
        raise ErroNeuraLake(f"capacidade inválida: {capacidade!r}")

    fases = [capacidade] if capacidade == CAPACIDADE_PLANO_B else [capacidade, CAPACIDADE_PLANO_B]
    custo_total = 0.0
    tentativas_feitas = 0
    ultimo_erro: Exception | None = None
    motivo_plano_b = ""
    resultado: ResultadoChamada | None = None

    for indice_fase, cap in enumerate(fases):
        ultima_fase = indice_fase == len(fases) - 1
        teto = max(max_tokens, MAX_TOKENS_PENSANTE if cap in CAPACIDADES_QUE_PENSAM else 0)
        timeout = TIMEOUT_PENSANTE_S if cap in CAPACIDADES_QUE_PENSAM else TIMEOUT_S
        for tentativa in range(TENTATIVAS):
            ultima_tentativa = tentativa == TENTATIVAS - 1
            tentativas_feitas += 1
            try:
                async with httpx.AsyncClient() as cliente:
                    bruto = await _post(cliente, cap, mensagens, teto, temperature, timeout)
            except httpx.HTTPStatusError as erro:
                status = erro.response.status_code
                motivo_plano_b = f"HTTP {status} em {cap}"
                ultimo_erro = ErroNeuraLake(f"NeuraLake respondeu {status} em {cap}")
                if status in ERROS_TRANSITORIOS and not ultima_tentativa:
                    await asyncio.sleep(0.5 * (tentativa + 1))
                    continue
                break
            except httpx.HTTPError as erro:
                motivo_plano_b = f"falha de rede em {cap} (timeout {timeout:.0f}s)"
                ultimo_erro = ErroNeuraLake(f"falha de rede ao chamar a NeuraLake em {cap}: {erro}")
                if not ultima_tentativa:
                    await asyncio.sleep(0.5 * (tentativa + 1))
                    continue
                break

            custo_total += float((bruto.get("usage") or {}).get("estimated_cost") or 0.0)
            escolha = (bruto.get("choices") or [{}])[0]
            texto_bruto = (escolha.get("message") or {}).get("content") or ""
            modelo_roteado = str(bruto.get("model") or cap)

            if _corpo_vazio(texto_bruto):
                motivo_plano_b = f"corpo vazio em {cap} (queima de raciocínio)"
                logger.warning("corpo vazio (capacidade=%s, tentativa %s) — repetindo",
                               cap, tentativa + 1)
                if not ultima_tentativa:
                    continue
                if not ultima_fase:
                    break
                # Não tem mais para onde cair: devolve o que sobrou.

            resultado = ResultadoChamada(
                texto=remover_think(texto_bruto), custo_usd=custo_total,
                capacidade_pedida=capacidade, capacidade_usada=cap,
                modelo_roteado=modelo_roteado, plano_b=cap != capacidade,
                motivo_plano_b=motivo_plano_b if cap != capacidade else "",
                tentativas=tentativas_feitas, bruto=bruto,
            )
            break
        if resultado is not None:
            break

    if resultado is None:
        if custo_total:
            db.debitar_inferencia(agente_id, custo_total)
        db.inserir_evento(rodada_id, None, "falha", agente_nome, "NeuraLake",
                          f"chamada de {etapa} falhou: {motivo_plano_b or ultimo_erro}",
                          custo_total, {"etapa": etapa, "capacidade_pedida": capacidade})
        raise ultimo_erro or ErroNeuraLake(f"chamada de {etapa} falhou sem resposta utilizável")

    db.debitar_inferencia(agente_id, resultado.custo_usd)
    if resultado.plano_b:
        motivo = (f"chamou a NeuraLake em {resultado.capacidade_usada} (PLANO B, pedido era "
                  f"{resultado.capacidade_pedida}): {resultado.motivo_plano_b}")
    else:
        motivo = (f"chamou a NeuraLake em {resultado.capacidade_pedida} "
                  f"(a NeuraLake roteou para {resultado.modelo_roteado})")
    db.inserir_evento(
        rodada_id, None, "chamada", agente_nome, "NeuraLake", motivo, resultado.custo_usd,
        {"etapa": etapa, "capacidade_pedida": resultado.capacidade_pedida,
         "capacidade_usada": resultado.capacidade_usada,
         "modelo_roteado": resultado.modelo_roteado, "plano_b": resultado.plano_b,
         "motivo_plano_b": resultado.motivo_plano_b, "tentativas": resultado.tentativas,
         "agente_id": agente_id},
    )
    return resultado


def extrair_json(texto: str) -> str | None:
    """Maior bloco JSON equilibrado dentro de um texto sujo (crase, prosa em
    volta). Respeita aspas para não contar chave dentro de string."""
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


async def pedir_json(
    mensagens: list[dict],
    *,
    agente_id: str,
    agente_nome: str,
    etapa: str,
    rodada_id: str | None = None,
    capacidade: str = "auto",
    max_tokens: int = MAX_TOKENS_PADRAO,
    temperature: float = 0.3,
) -> tuple[object | None, ResultadoChamada]:
    """Pede JSON e tolera resposta suja. Se falhar o parsing, repete UMA vez com
    instrução mais dura. Devolve (objeto_ou_None, último resultado)."""
    resultado = await chamar(mensagens, agente_id=agente_id, agente_nome=agente_nome,
                             etapa=etapa, rodada_id=rodada_id, capacidade=capacidade,
                             max_tokens=max_tokens, temperature=temperature)
    bloco = extrair_json(resultado.texto)
    if bloco:
        try:
            return json.loads(bloco), resultado
        except json.JSONDecodeError:
            pass

    logger.warning("JSON malformado em %s — repetindo com instrução mais dura", etapa)
    mensagens_duras = list(mensagens) + [
        {"role": "assistant", "content": resultado.texto[:600]},
        {"role": "user", "content": (
            "Sua resposta não era um JSON válido. Responda de novo com SOMENTE o JSON pedido: "
            "sem crase, sem markdown, sem texto antes ou depois. Comece em '{' ou '['."
        )},
    ]
    resultado2 = await chamar(mensagens_duras, agente_id=agente_id, agente_nome=agente_nome,
                              etapa=f"{etapa}:retry-json", rodada_id=rodada_id,
                              capacidade=capacidade, max_tokens=max_tokens,
                              temperature=temperature)
    resultado2.custo_usd += resultado.custo_usd
    bloco2 = extrair_json(resultado2.texto)
    if bloco2:
        try:
            return json.loads(bloco2), resultado2
        except json.JSONDecodeError:
            logger.error("JSON continua malformado em %s: %.200s", etapa, resultado2.texto)
    return None, resultado2
