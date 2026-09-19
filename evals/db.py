"""Conexão sqlite e aplicação do esquema. Sem dependência externa."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from evals import config


def conectar(caminho=None) -> sqlite3.Connection:
    caminho = str(caminho or config.CAMINHO_DB)
    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    return conexao


def aplicar_esquema(conexao: sqlite3.Connection) -> None:
    sql = config.CAMINHO_ESQUEMA.read_text(encoding="utf-8")
    conexao.executescript(sql)
    conexao.commit()


@contextmanager
def abrir(caminho=None) -> Iterator[sqlite3.Connection]:
    conexao = conectar(caminho)
    try:
        aplicar_esquema(conexao)
        yield conexao
    finally:
        conexao.close()


def obter_ou_criar_suite(conexao: sqlite3.Connection, nome: str, descricao: str = "") -> int:
    linha = conexao.execute("SELECT id FROM suites WHERE nome = ?", (nome,)).fetchone()
    if linha:
        if descricao:
            conexao.execute("UPDATE suites SET descricao = ? WHERE id = ?", (descricao, linha["id"]))
            conexao.commit()
        return linha["id"]
    cursor = conexao.execute(
        "INSERT INTO suites (nome, descricao) VALUES (?, ?)", (nome, descricao)
    )
    conexao.commit()
    return cursor.lastrowid


def dump_json(objeto) -> str:
    return json.dumps(objeto, ensure_ascii=False, sort_keys=True)


def load_json(texto: str | None, padrao=None):
    if not texto:
        return padrao
    try:
        return json.loads(texto)
    except (json.JSONDecodeError, TypeError):
        return padrao
