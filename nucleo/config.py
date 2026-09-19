"""Configuração de um lugar só. Nada de caminho pessoal, nada de chave.

A chave da NeuraLake vem SEMPRE do ambiente (`NEURALAKE_API_KEY`), nunca daqui.
"""
from __future__ import annotations

import os
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "dados"
PASTA_GRAVACOES = pathlib.Path(os.environ.get("NEURA_GRAVACOES") or (RAIZ / "gravacoes"))
PASTA_REPRISE_EXEMPLO = PASTA_DADOS / "reprise-exemplo"
CAMINHO_BANCO = pathlib.Path(os.environ.get("NEURA_DB") or (RAIZ / "neura.db"))
# Banco do Agno: é ele que guarda o `session_state` de cada rodada. Arquivo
# separado de propósito, porque quem manda no schema dele é o Agno.
CAMINHO_ESTADO = pathlib.Path(os.environ.get("NEURA_DB_AGNO") or (RAIZ / "neura-agno.db"))

HOST = os.environ.get("NEURA_HOST", "127.0.0.1")
PORTA = int(os.environ.get("NEURA_PORTA", "8787"))
# URL que os agentes usam para falar UNS COM OS OUTROS. Tudo passa por HTTP
# mesmo rodando no mesmo processo: mover um agente de máquina não muda código,
# só esta variável.
BASE_URL = os.environ.get("NEURA_BASE_URL", f"http://{HOST}:{PORTA}")


def capacidade(agente_id: str, padrao: str = "auto") -> str:
    """Capacidade da NeuraLake que um agente usa.

    Padrão `auto` em todos (é o que a régua do desafio premia). Dá para trocar
    por agente sem mexer no código: `NEURA_CAP_PROPERTY_CASA_VERIFICADA=code`.
    """
    chave = "NEURA_CAP_" + agente_id.upper().replace("-", "_")
    return (os.environ.get(chave) or "").strip() or padrao


# Orçamento inicial de cada carteira, em dólar. Serve para a tela mostrar
# quanto sobrou; o gasto de inferência que sai daqui é REAL.
ORCAMENTO_PADRAO_USD = float(os.environ.get("NEURA_ORCAMENTO_USD", "5.0"))


# Negociação A2A. O dono pediu "2 a 3" rodadas: o padrão é 3.
MAX_RODADAS_NEGOCIACAO = int(os.environ.get("NEURA_MAX_RODADAS", "3"))
# Quando o comprador não diz a oferta mínima, o Buyer Agent assume esta fração
# do teto e a suposição vai registrada no evento, nunca escondida.
FRACAO_OFERTA_MIN_PADRAO = float(os.environ.get("NEURA_FRACAO_OFERTA_MIN", "0.90"))
