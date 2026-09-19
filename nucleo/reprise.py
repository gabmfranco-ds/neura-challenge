"""Gravação e reprise de rodada real.

Regras duras:

- gravação guarda SÓ evento, tempo relativo e resumo da rodada. Nunca cabeçalho
  HTTP, nunca chave, nunca corpo de request. Antes de escrever o arquivo, o
  conteúdo passa por uma varredura de segredo e o arquivo não sai se achar algo.
- reprise NÃO escreve no banco e NÃO toca em carteira: ela vive numa fila em
  memória, separada, e a tela mostra o rótulo de reprise o tempo todo.
- reprise nunca se passa por ao vivo: todo pacote de reprise carrega
  `reprise: true` e a data da gravação.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import uuid

from . import config, db

_RE_SEGREDO = re.compile(r"(bearer\s+[A-Za-z0-9._\-]{8,}|nlk-[A-Za-z0-9._\-]{6,}"
                         r"|NEURALAKE_API_KEY\s*[:=]\s*\S+)", re.IGNORECASE)

_SESSOES: dict[str, dict] = {}


class SegredoNaGravacao(RuntimeError):
    pass


def _conferir_segredo(texto: str) -> None:
    achado = _RE_SEGREDO.search(texto)
    if achado:
        raise SegredoNaGravacao(
            "a gravação tem algo com cara de segredo e não foi escrita. "
            f"Trecho suspeito na posição {achado.start()}."
        )


def gravar(rodada_id: str, resumo: dict) -> str:
    """Grava a rodada em `gravacoes/`. Devolve o nome do arquivo."""
    eventos = db.eventos_desde(0, rodada_id)
    if not eventos:
        raise RuntimeError("rodada sem eventos, nada a gravar")
    inicio = eventos[0]["ts"]
    pacote = {
        "rodada_id": rodada_id,
        "gravado_em": dt.datetime.now(dt.timezone.utc).isoformat(),
        "duracao_total_s": round(eventos[-1]["ts"] - inicio, 3),
        "resumo": resumo,
        "eventos": [{
            "t": round(e["ts"] - inicio, 3), "estado": e["estado"], "tipo": e["tipo"],
            "de": e["de"], "para": e["para"], "motivo": e["motivo"],
            "custo_usd": e["custo_usd"], "dados": e["dados"],
        } for e in eventos],
    }
    texto = json.dumps(pacote, ensure_ascii=False, indent=1)
    _conferir_segredo(texto)
    config.PASTA_GRAVACOES.mkdir(parents=True, exist_ok=True)
    nome = f"{rodada_id}-{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    (config.PASTA_GRAVACOES / nome).write_text(texto, encoding="utf-8")
    return nome


def _pastas() -> list:
    return [p for p in (config.PASTA_GRAVACOES, config.PASTA_REPRISE_EXEMPLO) if p.exists()]


def listar() -> list[dict]:
    saida = []
    for pasta in _pastas():
        for caminho in sorted(pasta.glob("*.json")):
            try:
                pacote = json.loads(caminho.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            saida.append({
                "arquivo": caminho.name,
                "pasta": "exemplo" if pasta == config.PASTA_REPRISE_EXEMPLO else "gravacoes",
                "gravado_em": pacote.get("gravado_em"),
                "duracao_total_s": pacote.get("duracao_total_s"),
                "estado_final": (pacote.get("resumo") or {}).get("estado"),
                "frase": (pacote.get("resumo") or {}).get("frase"),
                "eventos": len(pacote.get("eventos") or []),
            })
    return saida


def carregar(arquivo: str) -> dict:
    nome = arquivo.replace("\\", "/").split("/")[-1]
    for pasta in _pastas():
        caminho = pasta / nome
        if caminho.exists():
            return json.loads(caminho.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"gravação não encontrada: {nome}")


def iniciar_sessao(arquivo: str, velocidade: float = 1.0) -> dict:
    """Abre uma reprise. Nada disto entra no banco nem mexe em carteira."""
    pacote = carregar(arquivo)
    sessao_id = f"rep-{uuid.uuid4().hex[:10]}"
    _SESSOES[sessao_id] = {
        "id": sessao_id, "arquivo": arquivo, "pacote": pacote,
        "inicio": time.time(), "velocidade": max(0.1, float(velocidade)),
    }
    return {"sessao_id": sessao_id, "reprise": True, "arquivo": arquivo,
            "gravado_em": pacote.get("gravado_em"),
            "rotulo": _rotulo(pacote),
            "total_eventos": len(pacote.get("eventos") or []),
            "duracao_total_s": pacote.get("duracao_total_s")}


def _rotulo(pacote: dict) -> str:
    quando = pacote.get("gravado_em") or "data desconhecida"
    try:
        quando = dt.datetime.fromisoformat(quando).astimezone().strftime("%d/%m/%Y às %H:%M")
    except (ValueError, TypeError):
        pass
    return f"REPRISE de rodada real gravada em {quando}. Nada aqui está acontecendo agora."


def eventos(sessao_id: str, since: int = 0) -> dict:
    sessao = _SESSOES.get(sessao_id)
    if sessao is None:
        raise KeyError(f"sessão de reprise desconhecida: {sessao_id}")
    pacote = sessao["pacote"]
    decorrido = (time.time() - sessao["inicio"]) * sessao["velocidade"]
    todos = pacote.get("eventos") or []
    visiveis = [e for e in todos if e["t"] <= decorrido]
    novos = visiveis[since:]
    saida = [{"seq": since + i + 1, **evento} for i, evento in enumerate(novos)]
    estado = visiveis[-1]["estado"] if visiveis and visiveis[-1].get("estado") else None
    if not estado:
        for evento in reversed(visiveis):
            if evento.get("estado"):
                estado = evento["estado"]
                break
    return {
        "reprise": True, "rotulo": _rotulo(pacote), "sessao_id": sessao_id,
        "eventos": saida, "ultimo_seq": len(visiveis),
        "terminou": len(visiveis) >= len(todos),
        "estado": estado, "resumo": pacote.get("resumo"),
        "gravado_em": pacote.get("gravado_em"),
    }


def encerrar(sessao_id: str) -> None:
    _SESSOES.pop(sessao_id, None)
