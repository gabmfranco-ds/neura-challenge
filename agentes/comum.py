"""Um `agno.agent.Agent` por papel, e o prompt de sistema sai da PRÓPRIA FICHA.

Regra dura do projeto: o comportamento de um agente vem da ficha que ele
publicou no Registry, não de um atalho no código. Trocar a estratégia declarada
troca o comportamento; nenhum `if` decide por ele o que responder.

Por que o Agno entra aqui e não no caminho de ferramenta: na NeuraLake `auto`
roteia para `text`, e `text` FALHA no turno `role:"tool"` (medido, ver
`docs/neuralake-api.md`). Então não existe tool calling no caminho crítico. O
que usamos do Agno é o agente com saída estruturada (`output_schema` mais
`use_json_mode`), e a orquestração continua sendo passo de Python.

As defesas do cliente antigo sobreviveram ao porte, agora em volta do Agno:
timeout de 25 s (no cliente httpx), uma repetição em corpo vazio, plano B em
`text` quando `auto` não cola, remoção de `<think>` e extrator tolerante de
JSON como rede de segurança.
"""
from __future__ import annotations

import json
import logging
import re

from agno.agent import Agent
from pydantic import BaseModel

from nucleo import config, db, modelo

logger = logging.getLogger("neura.agentes")

CAPACIDADE_PLANO_B = "text"
_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)
_AGENTES: dict[tuple, Agent] = {}


class FalhaDoAgente(RuntimeError):
    pass


def remover_think(texto: str) -> str:
    if not texto:
        return texto
    return _THINK_RE.sub("", texto).strip()


def instrucoes(ficha: dict, extra: str = "") -> list[str]:
    linhas = [
        f"Você é o agente \"{ficha['name']}\" de um marketplace de agentes de imóveis no Brasil.",
        f"Descrição da sua ficha pública: {ficha['description']}",
        f"Estratégia que você declarou no marketplace: {ficha.get('estrategia', '')}",
        "Você trabalha em português do Brasil. Nunca use travessão.",
        "Cumpra a sua estratégia declarada. Quem te contratou pagou por ela.",
    ]
    if extra:
        linhas.append(extra)
    return linhas


def sistema(ficha: dict, extra: str = "") -> dict:
    """Mantido para quem já montava mensagem à mão: vira instrução do Agno."""
    return {"role": "system", "content": "\n".join(instrucoes(ficha, extra))}


def agente(ficha: dict, esquema: type[BaseModel] | None, extra: str = "",
           capacidade: str | None = None) -> Agent:
    """Um Agent do Agno por (agente, skill, capacidade). Reaproveitado entre rodadas."""
    capacidade = capacidade or ficha.get("capacidade_neuralake") or "auto"
    chave = (ficha["agente_id"], esquema.__name__ if esquema else "texto", capacidade, extra[:40])
    if chave not in _AGENTES:
        _AGENTES[chave] = Agent(
            name=ficha["name"],
            id=ficha["agente_id"],
            model=modelo.modelo(capacidade),
            instructions=instrucoes(ficha, extra),
            output_schema=esquema,
            use_json_mode=True,
            markdown=False,
            telemetry=False,
            store_events=False,
            debug_mode=False,
        )
    return _AGENTES[chave]


def abrir_carteira(ficha: dict) -> None:
    db.abrir_carteira(ficha["agente_id"], ficha["name"], config.ORCAMENTO_PADRAO_USD)


def extrair_json(texto: str) -> str | None:
    """Maior bloco JSON equilibrado dentro de um texto sujo. Rede de segurança
    para quando o modelo ignora o schema e escreve prosa em volta."""
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


def _conteudo(resposta) -> tuple[object | None, str]:
    """Devolve (objeto, texto). Com schema, o Agno já entrega o modelo pronto."""
    conteudo = getattr(resposta, "content", None)
    if isinstance(conteudo, BaseModel):
        return conteudo.model_dump(), ""
    texto = remover_think(str(conteudo or ""))
    if not texto:
        return None, ""
    bloco = extrair_json(texto)
    if bloco:
        try:
            return json.loads(bloco), texto
        except json.JSONDecodeError:
            pass
    return None, texto


class Resultado:
    """O que o Orchestrator precisa saber de uma chamada lógica."""

    def __init__(self, objeto, custo_usd, capacidade_pedida, capacidade_usada,
                 modelo_roteado, plano_b=False, motivo_plano_b="", tentativas=1):
        self.objeto = objeto
        self.custo_usd = custo_usd
        self.capacidade_pedida = capacidade_pedida
        self.capacidade_usada = capacidade_usada
        self.modelo_roteado = modelo_roteado
        self.plano_b = plano_b
        self.motivo_plano_b = motivo_plano_b
        self.tentativas = tentativas


async def pedir_json(ficha: dict, mensagens: list[dict], *, etapa: str,
                     rodada_id: str | None, max_tokens: int = 1200,
                     temperature: float = 0.3, esquema: type[BaseModel] | None = None,
                     extra_sistema: str = "") -> tuple[object | None, Resultado]:
    """Uma chamada lógica à NeuraLake pelo Agno. Registra o evento e debita a carteira.

    `mensagens` é a lista antiga `[system, user]`: o texto do system vira
    instrução extra do Agent, o do user vira a entrada da vez.
    """
    abrir_carteira(ficha)
    entrada = "\n\n".join(m["content"] for m in mensagens if m.get("role") == "user")
    sistema_extra = "\n".join(m["content"] for m in mensagens
                              if m.get("role") == "system" and m.get("content"))
    # A ficha já entra em `instrucoes`; do system antigo só aproveitamos a
    # última linha, que é a orientação específica daquela skill.
    linha_extra = extra_sistema or (sistema_extra.split("\n")[-1] if sistema_extra else "")

    capacidade_pedida = ficha.get("capacidade_neuralake") or "auto"
    fases = ([capacidade_pedida] if capacidade_pedida == CAPACIDADE_PLANO_B
             else [capacidade_pedida, CAPACIDADE_PLANO_B])

    custo_total = 0.0
    modelo_roteado = ""
    tentativas = 0
    motivo_plano_b = ""
    objeto = None
    capacidade_usada = capacidade_pedida

    for indice, capacidade in enumerate(fases):
        ultima_fase = indice == len(fases) - 1
        for tentativa in range(2):  # 1 chamada + no máximo 1 repetição
            tentativas += 1
            caixa = modelo.abrir_caixa()
            try:
                resposta = await agente(ficha, esquema, linha_extra, capacidade).arun(entrada)
            except Exception as erro:
                custo_total += modelo.resumo_da_caixa(caixa)["custo_usd"]
                motivo_plano_b = f"{type(erro).__name__} em {capacidade}: {str(erro)[:120]}"
                logger.warning("chamada de %s falhou em %s: %s", etapa, capacidade, erro)
                if tentativa == 0:
                    continue
                break
            resumo = modelo.resumo_da_caixa(caixa)
            custo_total += resumo["custo_usd"]
            modelo_roteado = resumo["modelo_roteado"] or modelo_roteado
            objeto, texto = _conteudo(resposta)
            if objeto is not None:
                capacidade_usada = capacidade
                break
            motivo_plano_b = (f"corpo vazio em {capacidade}" if not texto
                              else f"resposta sem JSON utilizável em {capacidade}")
            logger.warning("%s em %s (tentativa %s)", motivo_plano_b, etapa, tentativa + 1)
            if tentativa == 0:
                continue
            if ultima_fase:
                capacidade_usada = capacidade
        if objeto is not None:
            break

    db.debitar_inferencia(ficha["agente_id"], custo_total)
    plano_b = capacidade_usada != capacidade_pedida
    if plano_b:
        motivo = (f"chamou a NeuraLake em {capacidade_usada} (PLANO B, pedido era "
                  f"{capacidade_pedida}): {motivo_plano_b}")
    else:
        motivo = (f"chamou a NeuraLake em {capacidade_pedida} "
                  f"(a NeuraLake roteou para {modelo_roteado or 'desconhecido'})")
    db.inserir_evento(
        rodada_id, None, "chamada", ficha["name"], "NeuraLake", motivo, custo_total,
        {"etapa": etapa, "capacidade_pedida": capacidade_pedida,
         "capacidade_usada": capacidade_usada, "modelo_roteado": modelo_roteado,
         "plano_b": plano_b, "motivo_plano_b": motivo_plano_b if plano_b else "",
         "tentativas": tentativas, "agente_id": ficha["agente_id"],
         "motor": "agno", "esquema": esquema.__name__ if esquema else None},
    )
    return objeto, Resultado(objeto, custo_total, capacidade_pedida, capacidade_usada,
                             modelo_roteado, plano_b, motivo_plano_b, tentativas)


def dinheiro(valor: float | int | None) -> str:
    if valor is None:
        return "-"
    return f"R$ {valor:,.0f}".replace(",", ".")
