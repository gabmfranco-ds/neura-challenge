"""Gera evals/relatorios/<data>-<rotulo>.md a partir de uma ou mais execuções.

Uso:
    python -m evals.relatorio --execucao ultimo
    python -m evals.relatorio --execucao 7
    python -m evals.relatorio --execucao baseline
    python -m evals.relatorio --comparar baseline pos-agno
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import time
from pathlib import Path

from evals import config, db


def _resolver_grupo(conexao: sqlite3.Connection, alvo: str) -> tuple[str, list[int]]:
    """`alvo` pode ser 'ultimo' (rótulo mais recente), um id de execução, ou um rótulo."""
    if alvo == "ultimo":
        linha = conexao.execute(
            "SELECT rotulo FROM execucoes ORDER BY iniciada_em DESC LIMIT 1"
        ).fetchone()
        if not linha:
            raise SystemExit("não há nenhuma execução no banco ainda")
        rotulo = linha["rotulo"]
        ids = [r["id"] for r in conexao.execute(
            "SELECT id FROM execucoes WHERE rotulo = ?", (rotulo,)).fetchall()]
        return rotulo, ids
    if alvo.isdigit():
        linha = conexao.execute("SELECT id, rotulo FROM execucoes WHERE id = ?",
                                (int(alvo),)).fetchone()
        if not linha:
            raise SystemExit(f"execução {alvo} não existe")
        return linha["rotulo"], [linha["id"]]
    ids = [r["id"] for r in conexao.execute(
        "SELECT id FROM execucoes WHERE rotulo = ?", (alvo,)).fetchall()]
    if not ids:
        raise SystemExit(f"nenhuma execução com rótulo {alvo!r}")
    return alvo, ids


def _percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    k = (len(ordenados) - 1) * p
    f = int(k)
    c = min(f + 1, len(ordenados) - 1)
    if f == c:
        return ordenados[f]
    return ordenados[f] + (ordenados[c] - ordenados[f]) * (k - f)


def _linhas_resultados(conexao: sqlite3.Connection, ids_execucao: list[int]) -> list[sqlite3.Row]:
    marcadores = ",".join("?" * len(ids_execucao))
    sql = (f"SELECT r.*, c.nome AS caso_nome, c.checagens_json, s.nome AS suite_nome, "
          f"e.capacidade, e.rotulo, e.alvo "
          f"FROM resultados r JOIN casos c ON c.id = r.caso_id JOIN suites s ON s.id = c.suite_id "
          f"JOIN execucoes e ON e.id = r.execucao_id WHERE r.execucao_id IN ({marcadores})")
    return conexao.execute(sql, ids_execucao).fetchall()


def _tabela(cabecalho: list[str], linhas: list[list[str]]) -> str:
    saida = ["| " + " | ".join(cabecalho) + " |",
            "|" + "|".join(["---"] * len(cabecalho)) + "|"]
    for linha in linhas:
        saida.append("| " + " | ".join(str(x) for x in linha) + " |")
    return "\n".join(saida)


def gerar_markdown(conexao: sqlite3.Connection, rotulo: str, ids_execucao: list[int]) -> str:
    linhas = _linhas_resultados(conexao, ids_execucao)
    partes = [f"# Relatório de avaliação: {rotulo}",
             f"\nGerado em {time.strftime('%Y-%m-%d %H:%M:%S')} UTC. "
             f"Execuções incluídas: {ids_execucao}. Total de tentativas: {len(linhas)}.\n"]

    if not linhas:
        partes.append("Nenhum resultado encontrado para este rótulo.")
        return "\n".join(partes)

    # ---- resumo por suite x capacidade
    chaves = sorted({(l["suite_nome"], l["capacidade"]) for l in linhas})
    tabela_resumo = []
    for suite, capacidade in chaves:
        subset = [l for l in linhas if l["suite_nome"] == suite and l["capacidade"] == capacidade]
        total = len(subset)
        passou = sum(l["passou"] for l in subset)
        custo_total = sum(l["custo_usd"] or 0 for l in subset)
        latencias = [l["latencia_ms"] for l in subset if l["latencia_ms"] is not None]
        tabela_resumo.append([
            suite, capacidade, total, f"{passou}/{total}",
            f"{100 * passou / total:.0f}%" if total else "-",
            f"{_percentil(latencias, 0.5):.0f}" if latencias else "-",
            f"{_percentil(latencias, 0.95):.0f}" if latencias else "-",
            f"{custo_total:.4f}",
        ])
    partes.append("## Acerto, latência e custo por suite x capacidade\n")
    partes.append(_tabela(
        ["suite", "capacidade", "tentativas", "passou", "taxa", "p50 ms", "p95 ms", "custo US$"],
        tabela_resumo))

    # ---- modelos que "auto" escolheu
    escolhidos = [l["modelo_usado"] for l in linhas if l["modelo_usado"]]
    contagem_modelos: dict[str, int] = {}
    for m in escolhidos:
        contagem_modelos[m] = contagem_modelos.get(m, 0) + 1
    if contagem_modelos:
        partes.append("\n## Modelos que a NeuraLake devolveu em `model` (todas as capacidades pedidas)\n")
        partes.append(_tabela(["modelo_usado", "total"],
                              sorted(([m, c] for m, c in contagem_modelos.items()),
                                    key=lambda x: -x[1])))

    # ---- taxas de defeito conhecido
    def _pede_json(linha) -> bool:
        checagens_caso = db.load_json(linha["checagens_json"], []) or []
        return any(ck.get("tipo") == "json_valido" for ck in checagens_caso)

    total_prompt = [l for l in linhas if l["alvo"] != "http"]
    total_json = [l for l in total_prompt if _pede_json(l)]
    corpo_vazio = len([l for l in total_prompt if l["erro_tipo"] == "corpo_vazio"])
    json_invalido = len([l for l in total_json if l["erro_tipo"] == "json_invalido"])
    partes.append("\n## Armadilhas conhecidas da API, medidas nesta bateria\n")
    if total_prompt:
        partes.append(f"- Corpo vazio (queima de raciocínio), em todas as tentativas de "
                      f"alvo prompt: {corpo_vazio}/{len(total_prompt)} "
                      f"({100 * corpo_vazio / len(total_prompt):.1f}%)")
    else:
        partes.append("- (sem tentativas de alvo prompt nesta seleção)")
    if total_json:
        partes.append(f"- JSON inválido/impossível de extrair, só nos casos que EXIGEM JSON: "
                      f"{json_invalido}/{len(total_json)} ({100 * json_invalido / len(total_json):.1f}%)")
    else:
        partes.append("- (nenhum caso desta seleção exige JSON)")

    # ---- erro por tipo
    erros: dict[str, int] = {}
    for l in linhas:
        if l["erro_tipo"]:
            erros[l["erro_tipo"]] = erros.get(l["erro_tipo"], 0) + 1
    if erros:
        partes.append("\n## Erro por tipo\n")
        partes.append(_tabela(["erro_tipo", "total"],
                              sorted(([k, v] for k, v in erros.items()), key=lambda x: -x[1])))

    # ---- casos instáveis (mesma execução, passa às vezes e falha às vezes)
    marcadores = ",".join("?" * len(ids_execucao))
    instaveis = conexao.execute(
        f"SELECT * FROM v_casos_instaveis WHERE execucao_id IN ({marcadores}) "
        f"ORDER BY vezes_falhou DESC", ids_execucao).fetchall()
    if instaveis:
        partes.append("\n## Casos instáveis (passam em algumas repetições, falham em outras)\n")
        partes.append(_tabela(
            ["suite", "caso", "repetições", "passou", "falhou"],
            [[i["suite"], i["caso"], i["repeticoes"], i["vezes_passou"], i["vezes_falhou"]]
             for i in instaveis]))

    # ---- 10 piores casos
    piores = sorted(linhas, key=lambda l: l["nota"])[:10]
    partes.append("\n## Os 10 piores resultados (menor nota primeiro)\n")
    for l in piores:
        falhas = db.load_json(l["falhas_json"], []) or []
        motivos = "; ".join(f"{f.get('checagem')}: {f.get('motivo')}" for f in falhas[:3])
        trecho = (l["resposta_bruta"] or "")[:200].replace("\n", " ")
        partes.append(f"- **{l['suite_nome']}/{l['caso_nome']}** (rep {l['repeticao']}, "
                      f"{l['capacidade']}, nota {l['nota']:.2f}): {motivos or '(sem detalhe)'}\n"
                      f"  trecho da saída: `{trecho}`")

    return "\n".join(partes)


def gerar_comparacao(conexao: sqlite3.Connection, rotulo_a: str, rotulo_b: str) -> str:
    _, ids_a = _resolver_grupo(conexao, rotulo_a)
    _, ids_b = _resolver_grupo(conexao, rotulo_b)
    linhas_a = _linhas_resultados(conexao, ids_a)
    linhas_b = _linhas_resultados(conexao, ids_b)

    def resumo(linhas):
        total = len(linhas)
        passou = sum(l["passou"] for l in linhas)
        custo = sum(l["custo_usd"] or 0 for l in linhas)
        latencias = [l["latencia_ms"] for l in linhas if l["latencia_ms"] is not None]
        return {
            "total": total, "taxa": (passou / total) if total else 0.0, "custo": custo,
            "p50": _percentil(latencias, 0.5), "p95": _percentil(latencias, 0.95),
        }

    ra, rb = resumo(linhas_a), resumo(linhas_b)
    partes = [f"# Comparação: {rotulo_a} vs {rotulo_b}\n"]
    partes.append(_tabela(
        ["métrica", rotulo_a, rotulo_b, "diferença"],
        [
            ["tentativas", ra["total"], rb["total"], rb["total"] - ra["total"]],
            ["taxa de acerto", f"{100*ra['taxa']:.1f}%", f"{100*rb['taxa']:.1f}%",
             f"{100*(rb['taxa']-ra['taxa']):+.1f}pp"],
            ["custo total US$", f"{ra['custo']:.4f}", f"{rb['custo']:.4f}",
             f"{rb['custo']-ra['custo']:+.4f}"],
            ["latência p50 ms", ra["p50"], rb["p50"],
             (rb["p50"] - ra["p50"]) if ra["p50"] and rb["p50"] else "-"],
            ["latência p95 ms", ra["p95"], rb["p95"],
             (rb["p95"] - ra["p95"]) if ra["p95"] and rb["p95"] else "-"],
        ]))
    return "\n".join(partes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execucao", default="ultimo",
                       help="'ultimo', um id numérico, ou um rótulo")
    parser.add_argument("--comparar", nargs=2, metavar=("ROTULO_A", "ROTULO_B"), default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--saida", default=None, help="caminho do .md de saída (opcional)")
    args = parser.parse_args()

    with db.abrir(args.db) as conexao:
        if args.comparar:
            rotulo_a, rotulo_b = args.comparar
            markdown = gerar_comparacao(conexao, rotulo_a, rotulo_b)
            nome = f"{time.strftime('%Y-%m-%d')}-comparacao-{rotulo_a}-vs-{rotulo_b}.md"
        else:
            rotulo, ids_execucao = _resolver_grupo(conexao, args.execucao)
            markdown = gerar_markdown(conexao, rotulo, ids_execucao)
            nome = f"{time.strftime('%Y-%m-%d')}-{rotulo}.md"

    caminho = Path(args.saida) if args.saida else (config.PASTA_RELATORIOS / nome)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(markdown, encoding="utf-8")
    print(f"relatório escrito em {caminho}")


if __name__ == "__main__":
    main()
