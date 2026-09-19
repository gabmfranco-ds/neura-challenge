"""Executor da bateria de avaliações.

Uso:
    python -m evals.rodar --suite buyer_extracao --capacidade auto --repeticoes 5 \
        --paralelo 8 --rotulo "baseline"

    python -m evals.rodar --suite api_saude --capacidade auto,text,code,reasoning \
        --repeticoes 3 --rotulo "saude"

    python -m evals.rodar --suite property_busca --alvo http --rotulo "http-smoke"

Cada combinação (capacidade) vira uma linha em `execucoes`; cada tentativa
(caso x repetição) vira uma linha em `resultados`. Erro de chamada é um
RESULTADO gravado (erro_tipo preenchido), nunca uma exceção que derruba a
bateria inteira.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time

from evals import alvos, checagens, config, db, loader, neuralake_client


def _git_ref() -> str:
    try:
        saida = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.RAIZ_REPO,
                               capture_output=True, text=True, timeout=5)
        return saida.stdout.strip() or "desconhecido"
    except Exception:
        return "desconhecido"


def _limpar_entrada(entrada: dict) -> tuple[dict, str]:
    entrada = dict(entrada)
    alvo = entrada.pop("_alvo", "prompt")
    entrada.pop("_prompt_ref", None)
    return entrada, alvo


async def _tentativa_negociacao_completa(caso: sqlite3.Row, capacidade: str, api_key: str,
                                         semaforo: asyncio.Semaphore) -> dict:
    """`negociacao_completa` não é uma chamada só: são até `max_rodadas` idas
    e vindas entre Buyer e Seller. `alvos.simular_negociacao_completa` já
    devolve o agregado (custo somado, tokens somados, `saida` com o
    histórico e o resultado); aqui só falta rodar as checagens em cima
    desse agregado, do mesmo jeito que uma chamada simples."""
    entrada_bruta = db.load_json(caso["entrada_json"], {})
    entrada, _ = _limpar_entrada(entrada_bruta)
    esperado = db.load_json(caso["esperado_json"], {}) or {}
    checagens_caso = db.load_json(caso["checagens_json"], []) or []

    async with semaforo:
        agregado = await alvos.simular_negociacao_completa(entrada, capacidade, api_key)

    ctx = checagens.Contexto(saida=agregado["saida"], texto=agregado["texto"], entrada=entrada,
                             esperado=esperado, modelo_usado=agregado["modelo_usado"],
                             capacidade_pedida=capacidade, capacidade_usada=capacidade)
    passou, nota, falhas = checagens.rodar_checagens(checagens_caso, ctx)
    if agregado["erro_tipo"]:
        passou = False
        falhas = [{"checagem": "simulacao", "motivo": f"parou com erro_tipo={agregado['erro_tipo']}"}] + falhas

    return {
        "passou": passou, "nota": nota, "falhas": falhas, "saida": agregado["saida"],
        "resposta_bruta": agregado["texto"][:4000], "modelo_usado": agregado["modelo_usado"],
        "latencia_ms": agregado["latencia_ms"], "tokens_entrada": agregado["tokens_entrada"],
        "tokens_saida": agregado["tokens_saida"], "custo_usd": agregado["custo_usd"],
        "erro_tipo": agregado["erro_tipo"], "http_status": None,
    }


async def _tentativa_prompt(caso: sqlite3.Row, suite_nome: str, capacidade: str,
                            repeticao: int, api_key: str, semaforo: asyncio.Semaphore) -> dict:
    if suite_nome == "negociacao_completa":
        return await _tentativa_negociacao_completa(caso, capacidade, api_key, semaforo)

    entrada_bruta = db.load_json(caso["entrada_json"], {})
    entrada, _ = _limpar_entrada(entrada_bruta)
    esperado = db.load_json(caso["esperado_json"], {}) or {}
    checagens_caso = db.load_json(caso["checagens_json"], []) or []

    mensagens, max_tokens, temperature = alvos.construir_mensagens(suite_nome, entrada)

    async with semaforo:
        resultado = await neuralake_client.chamar(
            mensagens, capacidade=capacidade, api_key=api_key,
            max_tokens=max_tokens, temperature=temperature,
        )

    if not resultado.ok:
        return {
            "passou": False, "nota": 0.0,
            "falhas": [{"checagem": "chamada_api", "motivo": f"{resultado.erro_tipo}: {resultado.texto[:200]}"}],
            "saida": None, "resposta_bruta": db.dump_json(resultado.resposta_bruta)[:4000],
            "modelo_usado": None, "latencia_ms": resultado.latencia_ms,
            "tokens_entrada": None, "tokens_saida": None, "custo_usd": 0.0,
            "erro_tipo": resultado.erro_tipo, "http_status": resultado.http_status,
        }

    texto_bruto = resultado.texto
    vazio = not neuralake_client.remover_think(texto_bruto).strip()
    bloco = neuralake_client.extrair_json(texto_bruto)
    saida = None
    if bloco:
        try:
            saida = json.loads(bloco)
        except json.JSONDecodeError:
            saida = None

    erro_tipo = "corpo_vazio" if vazio else ("json_invalido" if saida is None else None)

    ctx = checagens.Contexto(
        saida=saida, texto=texto_bruto, entrada=entrada, esperado=esperado,
        modelo_usado=resultado.modelo_usado, capacidade_pedida=capacidade,
        capacidade_usada=resultado.modelo_usado,
    )
    passou, nota, falhas = checagens.rodar_checagens(checagens_caso, ctx)

    return {
        "passou": passou, "nota": nota, "falhas": falhas, "saida": saida,
        "resposta_bruta": texto_bruto[:4000],
        "modelo_usado": resultado.modelo_usado, "latencia_ms": resultado.latencia_ms,
        "tokens_entrada": resultado.tokens_entrada, "tokens_saida": resultado.tokens_saida,
        "custo_usd": resultado.custo_usd, "erro_tipo": erro_tipo,
        "http_status": resultado.http_status,
    }


async def _tentativa_http(caso: sqlite3.Row, capacidade: str, semaforo: asyncio.Semaphore) -> dict:
    entrada_bruta = db.load_json(caso["entrada_json"], {})
    entrada, _ = _limpar_entrada(entrada_bruta)
    esperado = db.load_json(caso["esperado_json"], {}) or {}
    checagens_caso = db.load_json(caso["checagens_json"], []) or []

    async with semaforo:
        resposta = await alvos.chamar_http(entrada)

    if resposta["erro_tipo"] == "alvo_fora_do_ar":
        return {
            "passou": False, "nota": 0.0,
            "falhas": [{"checagem": "http", "motivo": "servidor do projeto fora do ar (8787)"}],
            "saida": None, "resposta_bruta": "", "modelo_usado": None,
            "latencia_ms": resposta["latencia_ms"], "tokens_entrada": None, "tokens_saida": None,
            "custo_usd": 0.0, "erro_tipo": "alvo_fora_do_ar", "http_status": None,
        }
    if not resposta["ok"]:
        return {
            "passou": False, "nota": 0.0,
            "falhas": [{"checagem": "http", "motivo": f"{resposta['erro_tipo']}: {str(resposta['corpo'])[:200]}"}],
            "saida": None, "resposta_bruta": db.dump_json(resposta["corpo"])[:4000],
            "modelo_usado": None, "latencia_ms": resposta["latencia_ms"],
            "tokens_entrada": None, "tokens_saida": None, "custo_usd": 0.0,
            "erro_tipo": resposta["erro_tipo"], "http_status": resposta["http_status"],
        }

    corpo = resposta["corpo"]
    ctx = checagens.Contexto(saida=corpo, texto=db.dump_json(corpo), entrada=entrada, esperado=esperado)
    passou, nota, falhas = checagens.rodar_checagens(checagens_caso, ctx)
    return {
        "passou": passou, "nota": nota, "falhas": falhas, "saida": corpo,
        "resposta_bruta": db.dump_json(corpo)[:4000], "modelo_usado": None,
        "latencia_ms": resposta["latencia_ms"], "tokens_entrada": None, "tokens_saida": None,
        "custo_usd": float(corpo.get("custo_usd") or 0.0) if isinstance(corpo, dict) else 0.0,
        "erro_tipo": None, "http_status": resposta["http_status"],
    }


class _Progresso:
    def __init__(self, total: int, rotulo: str):
        self.total = total
        self.feito = 0
        self.ok = 0
        self.rotulo = rotulo
        self._lock = asyncio.Lock()
        self._inicio = time.monotonic()

    async def marcar(self, passou: bool) -> None:
        async with self._lock:
            self.feito += 1
            self.ok += int(passou)
            if self.feito % 5 == 0 or self.feito == self.total:
                decorrido = time.monotonic() - self._inicio
                print(f"\r[{self.rotulo}] {self.feito}/{self.total} "
                      f"(ok {self.ok}, {decorrido:.0f}s)".ljust(70), end="", flush=True)


async def _rodar_capacidade(conexao: sqlite3.Connection, suites: list[str], capacidade: str,
                            repeticoes: int, paralelo: int, rotulo: str, alvo_filtro: str | None,
                            api_key: str | None) -> None:
    agora = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cursor = conexao.execute(
        "INSERT INTO execucoes (iniciada_em, rotulo, alvo, capacidade, git_ref, observacao) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (agora, rotulo, alvo_filtro or "misto", capacidade, _git_ref(),
         f"suites={','.join(suites)}"),
    )
    execucao_id = cursor.lastrowid
    conexao.commit()

    tarefas_por_alvo: dict[str, list[tuple[sqlite3.Row, str, int]]] = {"prompt": [], "http": []}
    for suite_nome in suites:
        for caso in loader.casos_ativos(conexao, suite_nome):
            entrada_bruta = db.load_json(caso["entrada_json"], {})
            alvo_caso = entrada_bruta.get("_alvo", "prompt")
            if alvo_filtro and alvo_caso != alvo_filtro:
                continue
            for repeticao in range(1, repeticoes + 1):
                tarefas_por_alvo.setdefault(alvo_caso, []).append((caso, suite_nome, repeticao))

    total = sum(len(v) for v in tarefas_por_alvo.values())
    if total == 0:
        print(f"[{rotulo}/{capacidade}] nenhum caso ativo para rodar (alvo={alvo_filtro})")
        conexao.execute("UPDATE execucoes SET terminada_em = ? WHERE id = ?",
                        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), execucao_id))
        conexao.commit()
        return

    semaforo = asyncio.Semaphore(paralelo)
    progresso = _Progresso(total, f"{rotulo}/{capacidade}")

    async def executar_uma(caso, suite_nome, repeticao, alvo_caso):
        if alvo_caso == "http":
            resultado = await _tentativa_http(caso, capacidade, semaforo)
        else:
            if not api_key:
                resultado = {"passou": False, "nota": 0.0,
                            "falhas": [{"checagem": "config", "motivo": "NEURALAKE_API_KEY ausente"}],
                            "saida": None, "resposta_bruta": "", "modelo_usado": None,
                            "latencia_ms": 0, "tokens_entrada": None, "tokens_saida": None,
                            "custo_usd": 0.0, "erro_tipo": "sem_chave", "http_status": None}
            else:
                resultado = await _tentativa_prompt(caso, suite_nome, capacidade, repeticao,
                                                    api_key, semaforo)
        await progresso.marcar(resultado["passou"])
        return caso, repeticao, resultado

    tarefas = [
        executar_uma(caso, suite_nome, repeticao, alvo_caso)
        for alvo_caso, lista in tarefas_por_alvo.items()
        for caso, suite_nome, repeticao in lista
    ]
    resultados = await asyncio.gather(*tarefas)
    print()  # fecha a linha de progresso

    for caso, repeticao, r in resultados:
        conexao.execute(
            "INSERT INTO resultados (execucao_id, caso_id, repeticao, passou, nota, "
            "falhas_json, saida_json, resposta_bruta, modelo_usado, capacidade_pedida, "
            "latencia_ms, tokens_entrada, tokens_saida, custo_usd, erro_tipo, http_status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (execucao_id, caso["id"], repeticao, int(r["passou"]), r["nota"],
             db.dump_json(r["falhas"]), db.dump_json(r["saida"]), r["resposta_bruta"],
             r["modelo_usado"], capacidade, r["latencia_ms"], r["tokens_entrada"],
             r["tokens_saida"], r["custo_usd"], r["erro_tipo"], r["http_status"]),
        )
    conexao.execute("UPDATE execucoes SET terminada_em = ? WHERE id = ?",
                    (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), execucao_id))
    conexao.commit()

    total_passou = sum(r["passou"] for _, _, r in resultados)
    custo_total = sum(r["custo_usd"] or 0 for _, _, r in resultados)
    print(f"[{rotulo}/{capacidade}] execucao_id={execucao_id} "
         f"{total_passou}/{total} passou, custo US$ {custo_total:.4f}")


def _todas_as_suites(conexao: sqlite3.Connection) -> list[str]:
    return [r["nome"] for r in conexao.execute(
        "SELECT DISTINCT s.nome FROM suites s JOIN casos c ON c.suite_id = s.id "
        "WHERE c.ativo = 1 ORDER BY s.nome").fetchall()]


async def main_async(args: argparse.Namespace) -> None:
    loader.sincronizar_tudo(caminho_db=args.db)
    api_key = os.environ.get("NEURALAKE_API_KEY")
    if not api_key and args.alvo != "http":
        print("AVISO: NEURALAKE_API_KEY não está no ambiente. Casos de alvo 'prompt' "
             "serão registrados com erro_tipo=sem_chave.", file=sys.stderr)

    with db.abrir(args.db) as conexao:
        suites = args.suite.split(",") if args.suite else _todas_as_suites(conexao)
        capacidades = [c.strip() for c in args.capacidade.split(",") if c.strip()]
        for capacidade in capacidades:
            await _rodar_capacidade(conexao, suites, capacidade, args.repeticoes,
                                    args.paralelo, args.rotulo, args.alvo, api_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Roda uma bateria de avaliações contra a NeuraLake.")
    parser.add_argument("--suite", default=None,
                       help="suites separadas por vírgula (padrão: todas as suites com caso ativo)")
    parser.add_argument("--capacidade", default="auto",
                       help="capacidades separadas por vírgula: auto,text,code,reasoning,...")
    parser.add_argument("--repeticoes", type=int, default=1)
    parser.add_argument("--paralelo", type=int, default=config.MAX_PARALELO)
    parser.add_argument("--rotulo", default="sem-rotulo")
    parser.add_argument("--alvo", default=None, choices=[None, "prompt", "http"],
                       help="filtra só os casos deste alvo (padrão: roda o alvo que cada caso declarar)")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
