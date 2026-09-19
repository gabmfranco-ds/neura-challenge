"""Carregador idempotente: sincroniza evals/casos/<suite>.jsonl -> tabela `casos`.

Cada arquivo `.jsonl` é uma suíte (nome = nome do arquivo sem extensão). Rodar
de novo sobre os mesmos arquivos não duplica nada: casos existentes (mesma
suíte + nome) são atualizados no lugar; casos que saíram do arquivo viram
`ativo=0` (nunca apagados, para não perder histórico de resultados antigos).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from evals import config, db


def _ler_jsonl(caminho: Path) -> list[dict]:
    casos = []
    for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), start=1):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        try:
            casos.append(json.loads(linha))
        except json.JSONDecodeError as erro:
            raise ValueError(f"{caminho.name}:{numero}: JSON inválido: {erro}") from erro
    return casos


def sincronizar_arquivo(conexao: sqlite3.Connection, caminho: Path) -> dict:
    suite_nome = caminho.stem
    linhas = _ler_jsonl(caminho)
    suite_id = db.obter_ou_criar_suite(conexao, suite_nome)

    vistos = set()
    novos = atualizados = 0
    for linha in linhas:
        nome = linha.get("nome")
        if not nome:
            raise ValueError(f"{caminho.name}: caso sem 'nome': {linha!r}")
        vistos.add(nome)
        entrada = linha.get("entrada") or {}
        entrada = {**entrada, "_alvo": linha.get("alvo", "prompt")}
        if "prompt_ref" in linha:
            entrada["_prompt_ref"] = linha["prompt_ref"]
        esperado = linha.get("esperado")
        checagens = linha.get("checagens") or []
        tags = ",".join(linha.get("tags") or [])

        existente = conexao.execute(
            "SELECT id FROM casos WHERE suite_id = ? AND nome = ?", (suite_id, nome)
        ).fetchone()
        if existente:
            conexao.execute(
                "UPDATE casos SET entrada_json=?, esperado_json=?, checagens_json=?, "
                "tags=?, ativo=1 WHERE id=?",
                (db.dump_json(entrada), db.dump_json(esperado), db.dump_json(checagens),
                 tags, existente["id"]),
            )
            atualizados += 1
        else:
            conexao.execute(
                "INSERT INTO casos (suite_id, nome, entrada_json, esperado_json, "
                "checagens_json, tags, ativo) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (suite_id, nome, db.dump_json(entrada), db.dump_json(esperado),
                 db.dump_json(checagens), tags),
            )
            novos += 1

    # Casos que saíram do arquivo: desativa (não apaga, preserva resultados antigos).
    desativados = 0
    for linha_bd in conexao.execute(
        "SELECT id, nome FROM casos WHERE suite_id = ? AND ativo = 1", (suite_id,)
    ).fetchall():
        if linha_bd["nome"] not in vistos:
            conexao.execute("UPDATE casos SET ativo = 0 WHERE id = ?", (linha_bd["id"],))
            desativados += 1

    conexao.commit()
    return {"suite": suite_nome, "novos": novos, "atualizados": atualizados,
            "desativados": desativados, "total_no_arquivo": len(linhas)}


def sincronizar_tudo(pasta: Path | None = None, caminho_db=None) -> list[dict]:
    pasta = pasta or config.PASTA_CASOS
    resultados = []
    with db.abrir(caminho_db) as conexao:
        for caminho in sorted(pasta.glob("*.jsonl")):
            resultados.append(sincronizar_arquivo(conexao, caminho))
    return resultados


def casos_ativos(conexao: sqlite3.Connection, suite_nome: str) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT c.* FROM casos c JOIN suites s ON s.id = c.suite_id "
        "WHERE s.nome = ? AND c.ativo = 1 ORDER BY c.id", (suite_nome,)
    ).fetchall()


if __name__ == "__main__":
    for resumo in sincronizar_tudo():
        print(f"{resumo['suite']}: {resumo['total_no_arquivo']} casos no arquivo "
              f"({resumo['novos']} novos, {resumo['atualizados']} atualizados, "
              f"{resumo['desativados']} desativados)")
