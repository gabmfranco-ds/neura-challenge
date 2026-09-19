"""Toda a suíte roda SEM REDE e sem chave.

Nenhum teste daqui chama a NeuraLake. O que precisa de modelo usa dublê, e o
dublê é explícito sobre o que devolve: teste que finge chamar a API e na
verdade não chama esconde justamente o defeito que interessa.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Banco de teste próprio, longe do banco da demo.
os.environ.setdefault("NEURA_DB", str(RAIZ / "tests" / ".teste.db"))
os.environ.setdefault("NEURA_DB_AGNO", str(RAIZ / "tests" / ".teste-agno.db"))
os.environ.setdefault("NEURA_GRAVACOES", str(RAIZ / "tests" / ".gravacoes"))
# A chave NUNCA é lida nos testes. Este valor existe só para o import de
# `nucleo.modelo` não explodir; nenhuma chamada HTTP sai daqui.
os.environ.setdefault("NEURALAKE_API_KEY", "chave-de-teste-nao-usada")


@pytest.fixture(autouse=True)
def banco_limpo():
    from nucleo import db
    db.resetar()
    yield
    db.resetar()


@pytest.fixture
def pedido():
    return {
        "tipo": "apartamento", "cidade": "São Paulo",
        "bairros": ["Pinheiros", "Vila Madalena"], "preco_max": 2000000,
        "quartos_min": 3, "vagas_min": 2, "area_min": 120,
        "objetivo": "moradia", "financiamento": True,
    }
