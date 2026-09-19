"""Configuração de um lugar só para o banco de avaliações.

Nada de chave aqui. `NEURALAKE_API_KEY` vem sempre do ambiente e este módulo
nunca lê nem expõe essa variável (quem chama a API é `neuralake_client.py`).
"""
from __future__ import annotations

import os
import pathlib

RAIZ_EVALS = pathlib.Path(__file__).resolve().parent          # .../neura-evals/evals
RAIZ_REPO = RAIZ_EVALS.parent                                   # .../neura-evals

CAMINHO_ESQUEMA = RAIZ_EVALS / "esquema.sql"
CAMINHO_DB = pathlib.Path(os.environ.get("EVALS_DB") or (RAIZ_EVALS / "evals.db"))
PASTA_CASOS = RAIZ_EVALS / "casos"
PASTA_RELATORIOS = RAIZ_EVALS / "relatorios"

BASE_URL_NEURALAKE = "https://api.neuralake.cloud/v1/chat/completions"

# URL do servidor do projeto (alvo "http"). Pode não estar de pé; nesse caso os
# casos http viram resultado com erro_tipo="alvo_fora_do_ar", não exceção.
BASE_URL_PROJETO = os.environ.get("NEURA_BASE_URL", "http://127.0.0.1:8787")

# Onde ler dados/imoveis.json para as checagens offline (ids_existem_na_base,
# respeita_filtros). O worktree `evals` nasceu de `main`, que é só o esqueleto
# do projeto (sem dados/ ainda) -- por isso o padrão aponta para o worktree
# irmão `neura-challenge` (branch v1, onde o outro agente está construindo o
# sistema). Depois que `evals` for mesclado em `v1`, ou quando os dados forem
# copiados para dentro deste repo, basta setar EVALS_DADOS_PATH ou deixar que o
# fallback local (`<repo>/dados`) seja encontrado primeiro.
_CANDIDATOS_DADOS = [
    RAIZ_REPO / "dados",
    RAIZ_REPO.parent / "neura-challenge" / "dados",
]


def pasta_dados() -> pathlib.Path:
    se_env = os.environ.get("EVALS_DADOS_PATH")
    if se_env:
        return pathlib.Path(se_env)
    for candidata in _CANDIDATOS_DADOS:
        if (candidata / "imoveis.json").exists():
            return candidata
    # Nenhuma encontrada: devolve a primeira mesmo assim, quem for ler que
    # trate o FileNotFoundError (os testes usam fixtures próprias, não isto).
    return _CANDIDATOS_DADOS[0]


TIMEOUT_S = float(os.environ.get("EVALS_TIMEOUT_S", "30.0"))
MAX_PARALELO = int(os.environ.get("EVALS_MAX_PARALELO", "8"))
