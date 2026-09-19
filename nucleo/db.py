"""Banco sqlite: eventos, carteiras, retido, razão do escrow, registry e recibos.

Um arquivo só (`neura.db` na raiz, ignorado pelo git). Conexão única com trava,
porque o FastAPI atende em várias tarefas ao mesmo tempo.

NADA que entre aqui pode conter cabeçalho HTTP, chave ou token: a gravação da
rodada é lida deste banco e vai para o repositório.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from . import config

_conn: sqlite3.Connection | None = None
_trava = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    rodada_id  TEXT,
    ts         REAL NOT NULL,
    estado     TEXT,
    tipo       TEXT NOT NULL,
    de         TEXT,
    para       TEXT,
    motivo     TEXT,
    custo_usd  REAL NOT NULL DEFAULT 0,
    dados      TEXT
);
CREATE INDEX IF NOT EXISTS idx_eventos_rodada ON eventos(rodada_id);

CREATE TABLE IF NOT EXISTS carteiras (
    agente_id            TEXT PRIMARY KEY,
    nome                 TEXT NOT NULL,
    saldo_usd            REAL NOT NULL DEFAULT 0,
    gasto_inferencia_usd REAL NOT NULL DEFAULT 0,
    honorario_usd        REAL NOT NULL DEFAULT 0,
    retido_usd           REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS escrow (
    id        TEXT PRIMARY KEY,
    rodada_id TEXT NOT NULL,
    ts        REAL NOT NULL,
    tipo      TEXT NOT NULL,
    valor_brl REAL NOT NULL,
    motivo    TEXT
);
CREATE INDEX IF NOT EXISTS idx_escrow_rodada ON escrow(rodada_id);

CREATE TABLE IF NOT EXISTS registry_agentes (
    agente_id  TEXT PRIMARY KEY,
    card       TEXT NOT NULL,
    cadastrado_em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS recibos (
    id              TEXT PRIMARY KEY,
    rodada_id       TEXT,
    agente_id       TEXT NOT NULL,
    skill           TEXT NOT NULL,
    itens_pedidos   INTEGER NOT NULL,
    itens_provados  INTEGER NOT NULL,
    preco_usd       REAL NOT NULL,
    pago_usd        REAL NOT NULL,
    retido_usd      REAL NOT NULL,
    custo_inferencia_usd REAL NOT NULL DEFAULT 0,
    motivo          TEXT,
    ts              REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recibos_agente ON recibos(agente_id);
"""


def novo_id(prefixo: str = "") -> str:
    return f"{prefixo}{uuid.uuid4().hex[:12]}"


def conectar() -> sqlite3.Connection:
    global _conn
    with _trava:
        if _conn is None:
            config.CAMINHO_BANCO.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(config.CAMINHO_BANCO), check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def resetar() -> None:
    """Zera o banco inteiro. Usado no boot do servidor e nos testes."""
    global _conn
    with _trava:
        conn = conectar()
        for tabela in ("eventos", "carteiras", "escrow", "registry_agentes", "recibos"):
            conn.execute(f"DELETE FROM {tabela}")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='eventos'")
        conn.commit()


def _exec(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    with _trava:
        conn = conectar()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur


def _linhas(sql: str, params: tuple = ()) -> list[dict]:
    with _trava:
        conn = conectar()
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------- eventos

def inserir_evento(rodada_id: str | None, estado: str | None, tipo: str, de: str | None,
                   para: str | None, motivo: str, custo_usd: float = 0.0,
                   dados: dict | None = None) -> int:
    cur = _exec(
        "INSERT INTO eventos (rodada_id, ts, estado, tipo, de, para, motivo, custo_usd, dados)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (rodada_id, time.time(), estado, tipo, de, para, motivo, float(custo_usd),
         json.dumps(dados, ensure_ascii=False) if dados else None),
    )
    return int(cur.lastrowid or 0)


def eventos_desde(since: int, rodada_id: str | None = None) -> list[dict]:
    if rodada_id:
        linhas = _linhas("SELECT * FROM eventos WHERE seq > ? AND rodada_id = ? ORDER BY seq",
                         (since, rodada_id))
    else:
        linhas = _linhas("SELECT * FROM eventos WHERE seq > ? ORDER BY seq", (since,))
    for linha in linhas:
        linha["dados"] = json.loads(linha["dados"]) if linha.get("dados") else None
    return linhas


def ultimo_seq() -> int:
    linhas = _linhas("SELECT COALESCE(MAX(seq), 0) AS s FROM eventos")
    return int(linhas[0]["s"]) if linhas else 0


# -------------------------------------------------------------- carteiras

def abrir_carteira(agente_id: str, nome: str, saldo_usd: float) -> None:
    _exec("INSERT OR IGNORE INTO carteiras (agente_id, nome, saldo_usd) VALUES (?,?,?)",
          (agente_id, nome, float(saldo_usd)))


def debitar_inferencia(agente_id: str, valor_usd: float) -> None:
    if valor_usd <= 0:
        return
    _exec("UPDATE carteiras SET saldo_usd = saldo_usd - ?, gasto_inferencia_usd = gasto_inferencia_usd + ?"
          " WHERE agente_id = ?", (float(valor_usd), float(valor_usd), agente_id))


def creditar_honorario(agente_id: str, valor_usd: float) -> None:
    _exec("UPDATE carteiras SET saldo_usd = saldo_usd + ?, honorario_usd = honorario_usd + ?"
          " WHERE agente_id = ?", (float(valor_usd), float(valor_usd), agente_id))


def debitar_honorario(agente_id: str, valor_usd: float) -> None:
    _exec("UPDATE carteiras SET saldo_usd = saldo_usd - ? WHERE agente_id = ?",
          (float(valor_usd), agente_id))


def registrar_retido(agente_id: str, valor_usd: float) -> None:
    _exec("UPDATE carteiras SET retido_usd = retido_usd + ? WHERE agente_id = ?",
          (float(valor_usd), agente_id))


def carteiras() -> list[dict]:
    return _linhas("SELECT * FROM carteiras ORDER BY agente_id")


def carteira(agente_id: str) -> dict | None:
    linhas = _linhas("SELECT * FROM carteiras WHERE agente_id = ?", (agente_id,))
    return linhas[0] if linhas else None


# ----------------------------------------------------------------- escrow

def lancar_escrow(rodada_id: str, tipo: str, valor_brl: float, motivo: str) -> str:
    lid = novo_id("esc-")
    _exec("INSERT INTO escrow (id, rodada_id, ts, tipo, valor_brl, motivo) VALUES (?,?,?,?,?,?)",
          (lid, rodada_id, time.time(), tipo, float(valor_brl), motivo))
    return lid


def razao_escrow(rodada_id: str | None = None) -> list[dict]:
    if rodada_id:
        return _linhas("SELECT * FROM escrow WHERE rodada_id = ? ORDER BY ts", (rodada_id,))
    return _linhas("SELECT * FROM escrow ORDER BY ts")


def saldo_escrow(rodada_id: str) -> float:
    saldo = 0.0
    for linha in razao_escrow(rodada_id):
        if linha["tipo"] == "reserva":
            saldo += linha["valor_brl"]
        elif linha["tipo"] in ("liberacao", "devolucao"):
            saldo -= linha["valor_brl"]
    return round(saldo, 2)


# --------------------------------------------------------------- registry

def cadastrar_card(agente_id: str, card: dict[str, Any]) -> None:
    _exec("INSERT OR REPLACE INTO registry_agentes (agente_id, card, cadastrado_em) VALUES (?,?,?)",
          (agente_id, json.dumps(card, ensure_ascii=False), time.time()))


def cards() -> list[dict]:
    return [json.loads(linha["card"]) for linha in
            _linhas("SELECT card FROM registry_agentes ORDER BY cadastrado_em")]


def card(agente_id: str) -> dict | None:
    linhas = _linhas("SELECT card FROM registry_agentes WHERE agente_id = ?", (agente_id,))
    return json.loads(linhas[0]["card"]) if linhas else None


# ---------------------------------------------------------------- recibos

def salvar_recibo(recibo: dict) -> None:
    _exec(
        "INSERT INTO recibos (id, rodada_id, agente_id, skill, itens_pedidos, itens_provados,"
        " preco_usd, pago_usd, retido_usd, custo_inferencia_usd, motivo, ts)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (recibo["id"], recibo.get("rodada_id"), recibo["agente_id"], recibo["skill"],
         int(recibo["itens_pedidos"]), int(recibo["itens_provados"]), float(recibo["preco_usd"]),
         float(recibo["pago_usd"]), float(recibo["retido_usd"]),
         float(recibo.get("custo_inferencia_usd") or 0.0), recibo.get("motivo"), time.time()),
    )


def recibos(agente_id: str | None = None) -> list[dict]:
    if agente_id:
        return _linhas("SELECT * FROM recibos WHERE agente_id = ? ORDER BY ts", (agente_id,))
    return _linhas("SELECT * FROM recibos ORDER BY ts")


def historico(agente_id: str) -> dict:
    """Histórico que o Registry publica: é isto que o Orchestrator lê para avaliar."""
    linhas = recibos(agente_id)
    if not linhas:
        return {"entregas": 0, "itens_provados": 0, "itens_pedidos": 0, "taxa_aprovacao": None,
                "pago_usd": 0.0, "retido_usd": 0.0}
    pedidos = sum(int(linha["itens_pedidos"]) for linha in linhas)
    provados = sum(int(linha["itens_provados"]) for linha in linhas)
    return {
        "entregas": len(linhas),
        "itens_provados": provados,
        "itens_pedidos": pedidos,
        "taxa_aprovacao": round(provados / pedidos, 3) if pedidos else None,
        "pago_usd": round(sum(float(linha["pago_usd"]) for linha in linhas), 6),
        "retido_usd": round(sum(float(linha["retido_usd"]) for linha in linhas), 6),
    }
