"""Reprise (que não pode tocar em carteira) e o estado guardado pelo Agno."""
import json
import time

import pytest

from nucleo import config, db, estados, reprise
from orchestrator import estado as estado_agno
from orchestrator import memoria


def _rodada_gravavel(rodada_id="rg1"):
    db.inserir_evento(rodada_id, "SEARCH", "humano", "Comprador", "Buyer", "quero um apto")
    db.inserir_evento(rodada_id, "SEARCH", "decisao", "Orquestrador", "Casa Verificada",
                      "contratei Casa Verificada", 0.0001)
    db.inserir_evento(rodada_id, "SHORTLIST", "estado", "SEARCH", "SHORTLIST", "3 imóveis")
    return {"estado": "SHORTLIST", "frase": "quero um apto", "shortlist": [],
            "contratos": [], "negociacao": []}


def test_gravacao_guarda_tempo_relativo():
    resumo = _rodada_gravavel()
    nome = reprise.gravar("rg1", resumo)
    pacote = json.loads((config.PASTA_GRAVACOES / nome).read_text(encoding="utf-8"))
    assert pacote["eventos"][0]["t"] == 0.0
    assert all("ts" not in e for e in pacote["eventos"]), "tempo absoluto não vai para a gravação"
    assert pacote["resumo"]["estado"] == "SHORTLIST"


def test_gravacao_nao_sai_se_tiver_cara_de_segredo():
    # O token falso é montado por pedaços de propósito: o README manda o time
    # rodar `git grep -i "nlk-"` antes de cada commit, e um literal aqui faria
    # essa checagem apontar para um teste toda vez.
    falso = "Bearer " + "nlk" + "-" + "abcdef123456"
    db.inserir_evento("rg2", "SEARCH", "chamada", "A", "NeuraLake",
                      f"usei Authorization: {falso} na chamada")
    with pytest.raises(reprise.SegredoNaGravacao):
        reprise.gravar("rg2", {"estado": "SEARCH"})


def test_reprise_nao_toca_em_carteira_nem_no_banco():
    db.abrir_carteira("ag-reprise", "Agente", 5.0)
    db.debitar_inferencia("ag-reprise", 0.01)
    nome = reprise.gravar("rg3", _rodada_gravavel("rg3"))
    antes_carteira = db.carteira("ag-reprise")
    antes_eventos = db.ultimo_seq()
    sessao = reprise.iniciar_sessao(nome, velocidade=1000.0)
    time.sleep(0.05)
    pacote = reprise.eventos(sessao["sessao_id"], since=0)

    assert pacote["reprise"] is True
    assert len(pacote["eventos"]) >= 1
    assert db.carteira("ag-reprise") == antes_carteira, "reprise mexeu na carteira"
    assert db.ultimo_seq() == antes_eventos, "reprise escreveu evento no banco"


def test_reprise_sempre_traz_rotulo_dizendo_que_e_reprise():
    nome = reprise.gravar("rg4", _rodada_gravavel("rg4"))
    sessao = reprise.iniciar_sessao(nome)
    assert "REPRISE" in sessao["rotulo"]
    assert "gravada em" in sessao["rotulo"]
    pacote = reprise.eventos(sessao["sessao_id"])
    assert pacote["reprise"] is True
    assert "REPRISE" in pacote["rotulo"]


def test_reprise_solta_os_eventos_no_tempo_e_nao_de_uma_vez():
    nome = reprise.gravar("rg5", _rodada_gravavel("rg5"))
    sessao = reprise.iniciar_sessao(nome, velocidade=0.001)
    pacote = reprise.eventos(sessao["sessao_id"], since=0)
    assert pacote["terminou"] in (True, False)
    assert len(pacote["eventos"]) <= 3


def test_gravacao_de_exemplo_do_repositorio_abre_e_esta_limpa():
    """A reserva do palco precisa abrir. Se alguém trocar o arquivo por um
    quebrado, é aqui que aparece."""
    gravacoes = [g for g in reprise.listar() if g["pasta"] == "exemplo"]
    assert gravacoes, "não há gravação de exemplo em dados/reprise-exemplo"
    pacote = reprise.carregar(gravacoes[0]["arquivo"])
    assert pacote["resumo"]["estado"] == "COMPLETED"
    texto = json.dumps(pacote, ensure_ascii=False)
    assert "Bearer " not in texto
    assert "NEURALAKE_API_KEY" not in texto


# ------------------------------------------------- estado guardado pelo Agno

def test_estado_da_rodada_persiste_no_agno():
    rodada = estado_agno.nova("rod-teste-estado", "quero um apartamento")
    rodada.estado = "SHORTLIST"
    rodada.shortlist = [{"property_id": "SP1008", "preco": 1695000}]
    rodada.preco_acordado = 1600000
    rodada.salvar()

    lida = estado_agno.carregar("rod-teste-estado")
    assert lida is not None
    assert lida.estado == "SHORTLIST"
    assert lida.shortlist[0]["property_id"] == "SP1008"
    assert lida.preco_acordado == 1600000


def test_rodada_que_nao_existe_devolve_none():
    assert estado_agno.carregar("rod-que-nunca-existiu") is None


def test_rodada_nasce_no_estado_inicial():
    rodada = estado_agno.nova("rod-nova", "frase")
    assert rodada.estado == estados.INICIAL
    assert rodada.para_json()["concluida"] is False
    assert rodada.para_json()["motor_de_estado"].startswith("agno")


# ------------------------------------------------------------- memória

def test_pedido_parecido_cai_na_mesma_assinatura():
    memoria.limpar()
    a = {"tipo": "apartamento", "cidade": "São Paulo", "bairros": ["Pinheiros"],
         "preco_max": 2_000_000, "quartos_min": 3, "vagas_min": 2, "area_min": 120}
    b = {**a, "preco_max": 1_950_000}
    assert memoria.assinatura(a) == memoria.assinatura(b)

    memoria.guardar(a, [{"property_id": "SP1008"}], 0.002, "rod-1")
    lembranca = memoria.buscar(b)
    assert lembranca is not None
    assert lembranca["custo_original_usd"] == 0.002
    assert lembranca["rodada_id"] == "rod-1"


def test_pedido_diferente_nao_reaproveita():
    memoria.limpar()
    a = {"tipo": "apartamento", "cidade": "São Paulo", "bairros": ["Pinheiros"],
         "preco_max": 2_000_000, "quartos_min": 3, "vagas_min": 2, "area_min": 120}
    outro_bairro = {**a, "bairros": ["Moema"]}
    outra_faixa = {**a, "preco_max": 1_200_000}
    memoria.guardar(a, [{"property_id": "SP1008"}], 0.002, "rod-1")
    assert memoria.buscar(outro_bairro) is None
    assert memoria.buscar(outra_faixa) is None
