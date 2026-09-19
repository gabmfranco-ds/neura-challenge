"""O estado da rodada mora no `session_state` de um Workflow do Agno.

Antes do porte, a rodada era um `dataclass` que vivia num dicionário em memória
e morria junto com o processo: reiniciar o servidor apagava a compra pela
metade, e não havia nenhum lugar para olhar o que tinha acontecido.

Agora cada rodada é uma sessão de Workflow do Agno, com `session_state`
persistido em sqlite pelo `SqliteDb` do próprio Agno. Quem escreve `rodada.estado
= "SHORTLIST"` está escrevendo no `session_state`; `salvar()` manda para o banco.
Não existe mais código nosso de carregar e gravar variável.

A `Rodada` continua parecendo um objeto comum de propósito: `motor.py` não
mudou por causa disso. É uma fachada sobre o dicionário do Agno.
"""
from __future__ import annotations

import logging
import time

from agno.db.sqlite import SqliteDb
from agno.workflow import Workflow

from nucleo import config, db, estados

logger = logging.getLogger("neura.estado")

_WORKFLOW: Workflow | None = None

CAMPOS_PADRAO: dict = {
    "id": "",
    "frase": "",
    "estado": estados.INICIAL,
    "criada_em": 0.0,
    "pedido": None,
    "suposicoes": [],
    "shortlist": [],
    "escolha": None,
    "mandato": None,
    "negociacao": [],
    "preco_acordado": None,
    "pacote": None,
    "contratos": [],
    "memoria_usada": None,
    "reprovados": [],
    "custo_busca_usd": 0.0,
    "erro": None,
    "concluida_em": None,
    "trabalhando": False,
    "gravacao": None,
}


def workflow() -> Workflow:
    """Um Workflow só, com o banco do Agno. Cada rodada é uma sessão dele."""
    global _WORKFLOW
    if _WORKFLOW is None:
        _WORKFLOW = Workflow(
            id="compra-de-imovel",
            name="Compra de imóvel por agentes",
            description="Descobre, avalia, contrata, delega e verifica agentes num marketplace.",
            db=SqliteDb(db_file=str(config.CAMINHO_ESTADO)),
            steps=[],
            store_events=False,
            telemetry=False,
        )
    return _WORKFLOW


class Rodada:
    """Fachada sobre o `session_state` da sessão do Agno.

    Ler `rodada.estado` lê o dicionário; escrever escreve nele. `salvar()`
    entrega ao Agno, que persiste no sqlite dele.
    """

    def __init__(self, dados: dict):
        object.__setattr__(self, "_dados", dados)

    def __getattr__(self, nome: str):
        dados = object.__getattribute__(self, "_dados")
        if nome in dados:
            return dados[nome]
        raise AttributeError(nome)

    def __setattr__(self, nome: str, valor) -> None:
        if nome.startswith("_"):
            object.__setattr__(self, nome, valor)
            return
        object.__getattribute__(self, "_dados")[nome] = valor

    @property
    def dados(self) -> dict:
        return object.__getattribute__(self, "_dados")

    def salvar(self) -> None:
        """Persiste no banco do Agno. Erro aqui nunca derruba a rodada."""
        try:
            fluxo = workflow()
            fluxo.update_session_state(session_state_updates=self.dados,
                                       session_id=self.id)
        except Exception:
            logger.exception("não consegui salvar a sessão %s no Agno", self.id)

    def para_json(self) -> dict:
        dados = self.dados
        return {
            "rodada_id": dados["id"], "frase": dados["frase"], "estado": dados["estado"],
            "pedido": dados["pedido"], "suposicoes": dados["suposicoes"],
            "shortlist": dados["shortlist"], "escolha": dados["escolha"],
            "mandato": dados["mandato"], "negociacao": dados["negociacao"],
            "preco_acordado": dados["preco_acordado"], "pacote": dados["pacote"],
            "contratos": dados["contratos"], "memoria_usada": dados["memoria_usada"],
            "custo_busca_usd": round(dados["custo_busca_usd"], 6), "erro": dados["erro"],
            "trabalhando": dados["trabalhando"],
            "duracao_s": round((dados["concluida_em"] or time.time()) - dados["criada_em"], 1),
            "concluida": dados["estado"] in estados.TERMINAIS,
            "gravacao": dados["gravacao"],
            "escrow": {"saldo_brl": db.saldo_escrow(dados["id"]),
                       "lancamentos": db.razao_escrow(dados["id"])},
            "motor_de_estado": "agno session_state (sqlite)",
        }


def nova(rodada_id: str, frase: str) -> Rodada:
    dados = {**CAMPOS_PADRAO, "id": rodada_id, "frase": frase, "criada_em": time.time(),
             "suposicoes": [], "shortlist": [], "negociacao": [], "contratos": [],
             "reprovados": []}
    rodada = Rodada(dados)
    try:
        fluxo = workflow()
        sessao = fluxo.read_or_create_session(session_id=rodada_id)
        if sessao.session_data is None:
            sessao.session_data = {}
        sessao.session_data["session_state"] = dados
        fluxo.save_session(session=sessao)
    except Exception:
        logger.exception("não consegui abrir a sessão %s no Agno", rodada_id)
    return rodada


def carregar(rodada_id: str) -> Rodada | None:
    """Recupera uma rodada do banco do Agno. Sobrevive a reinício do servidor."""
    try:
        guardado = workflow().get_session_state(session_id=rodada_id)
    except Exception:
        logger.exception("não consegui ler a sessão %s no Agno", rodada_id)
        return None
    if not guardado:
        return None
    return Rodada({**CAMPOS_PADRAO, **guardado})
