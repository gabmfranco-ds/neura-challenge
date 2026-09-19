"""Escrow, carteiras, registro de eventos e placar de autonomia. Sem rede."""
import asyncio

import pytest

from agentes import catalogo
from agentes.payment import agente as payment
from agentes.transaction import agente as transaction
from nucleo import dados, db, verificacao
from orchestrator import motor


def _ficha(agente_id):
    return catalogo.ficha(agente_id)


def _condicoes(**status):
    catalogo_condicoes = dados.criterios_fechamento()["condicoes"]
    return [{**c, "status": status.get(c["id"], "atendida")} for c in catalogo_condicoes]


# ---------------------------------------------------------------- escrow

def test_escrow_reserva_e_libera_com_conferencia():
    ficha = _ficha("payment-escrow-guardiao")
    reserva = asyncio.run(payment.executar(ficha, "custodia_pagamento", {
        "acao": "reservar", "rodada_id": "r1", "property_id": "SP1008",
        "valor_brl": 1_695_000}, "r1"))
    assert reserva["reservado"] is True
    assert db.saldo_escrow("r1") == 1_695_000

    liberacao = asyncio.run(payment.executar(ficha, "custodia_pagamento", {
        "acao": "conferir_e_liberar", "rodada_id": "r1", "property_id": "SP1008",
        "valor_brl": 1_695_000, "condicoes": _condicoes()}, "r1"))
    assert liberacao["liberado"] is True
    assert db.saldo_escrow("r1") == 0


def test_escrow_nao_libera_com_condicao_pendente():
    ficha = _ficha("payment-escrow-guardiao")
    asyncio.run(payment.executar(ficha, "custodia_pagamento", {
        "acao": "reservar", "rodada_id": "r2", "valor_brl": 1_000_000}, "r2"))
    liberacao = asyncio.run(payment.executar(ficha, "custodia_pagamento", {
        "acao": "conferir_e_liberar", "rodada_id": "r2", "valor_brl": 1_000_000,
        "condicoes": _condicoes(itbi_recolhido="pendente")}, "r2"))
    assert liberacao["liberado"] is False
    assert db.saldo_escrow("r2") == 1_000_000, "o dinheiro tem que continuar preso"


def test_agente_sem_custodia_nao_reserva_nada():
    """`Liquida Já` declara na ficha que não faz escrow. O código respeita a
    ficha; quem descobre o problema é a verificação do Orchestrator."""
    ficha = _ficha("payment-liquida-ja")
    reserva = asyncio.run(payment.executar(ficha, "custodia_pagamento", {
        "acao": "reservar", "rodada_id": "r3", "valor_brl": 1_000_000}, "r3"))
    assert reserva["reservado"] is False
    assert db.saldo_escrow("r3") == 0


def test_tudo_do_pagamento_esta_rotulado_como_simulado():
    ficha = _ficha("payment-escrow-guardiao")
    saida = asyncio.run(payment.executar(ficha, "custodia_pagamento", {
        "acao": "reservar", "rodada_id": "r4", "valor_brl": 10}, "r4"))
    assert saida["simulado"] is True


# ----------------------------------------------------------- transaction

def test_cartorio_digital_confere_documento_e_fecha_as_condicoes():
    pacote = asyncio.run(transaction.executar(
        _ficha("transaction-cartorio-digital"), "conduzir_transacao",
        {"property_id": "SP1008", "preco_acordado": 1_600_000,
         "mandato": {"teto_preco": 1_700_000}}, "r5"))
    conferencia = verificacao.conferir_condicoes(pacote["condicoes"], ate_fase="CONDITIONS_MET")
    assert conferencia["aprovado"]
    assert pacote["simulado"] is True


def test_fecha_rapido_deixa_as_documentais_pendentes():
    """A ficha dele diz que não confere documentação. O resultado tem que bater
    com a ficha, e a verificação tem que pegar."""
    pacote = asyncio.run(transaction.executar(
        _ficha("transaction-fecha-rapido"), "conduzir_transacao",
        {"property_id": "SP1008", "preco_acordado": 1_600_000,
         "mandato": {"teto_preco": 1_700_000}}, "r6"))
    conferencia = verificacao.conferir_condicoes(pacote["condicoes"], ate_fase="CONDITIONS_MET")
    assert not conferencia["aprovado"]
    pendentes = {p["id"] for p in conferencia["pendentes"]}
    assert "matricula_atualizada" in pendentes
    assert "certidoes_dentro_da_validade" in pendentes


def test_imovel_com_onus_nao_fecha_a_condicao_de_matricula():
    pacote = asyncio.run(transaction.executar(
        _ficha("transaction-cartorio-digital"), "conduzir_transacao",
        {"property_id": "SP1003", "preco_acordado": 1_600_000,
         "mandato": {"teto_preco": 1_700_000}}, "r7"))
    matricula = next(c for c in pacote["condicoes"] if c["id"] == "matricula_atualizada")
    assert matricula["status"] == "pendente"
    assert "ônus" in matricula["motivo"]


def test_preco_acima_do_mandato_nao_fecha_a_condicao():
    pacote = asyncio.run(transaction.executar(
        _ficha("transaction-cartorio-digital"), "conduzir_transacao",
        {"property_id": "SP1008", "preco_acordado": 1_900_000,
         "mandato": {"teto_preco": 1_700_000}}, "r8"))
    condicao = next(c for c in pacote["condicoes"] if c["id"] == "preco_dentro_do_mandato")
    assert condicao["status"] == "pendente"


# ---------------------------------------------------- eventos e placar

def test_placar_conta_cada_tipo_de_evento():
    db.inserir_evento("rx", "SEARCH", "humano", "Comprador", "Buyer", "escreveu a frase")
    db.inserir_evento("rx", "SEARCH", "decisao", "Orquestrador", "A", "contratei A")
    db.inserir_evento("rx", "SEARCH", "decisao", "Orquestrador", "B", "contratei B")
    db.inserir_evento("rx", "SEARCH", "repasse", "Orquestrador", "A", "deleguei")
    db.inserir_evento("rx", "SEARCH", "verificacao", "Orquestrador", "A", "conferi")
    db.inserir_evento("rx", None, "chamada", "A", "NeuraLake", "chamou", 0.001,
                      {"capacidade_pedida": "auto"})
    db.inserir_evento("rx", None, "chamada", "A", "NeuraLake", "chamou", 0.002,
                      {"capacidade_pedida": "code"})

    placar = motor.placar("rx")
    assert placar["intervencoes_humanas"] == 1
    assert placar["decisoes_sem_humano"] == 2
    assert placar["repasses"] == 1
    assert placar["verificacoes"] == 1
    assert placar["chamadas_auto"] == 1
    assert placar["chamadas_total"] == 2
    assert placar["custo_total_usd"] == pytest.approx(0.003)


def test_placar_de_uma_rodada_nao_conta_evento_de_outra():
    db.inserir_evento("r_a", "SEARCH", "humano", "Comprador", "Buyer", "frase A")
    db.inserir_evento("r_b", "SEARCH", "humano", "Comprador", "Buyer", "frase B")
    assert motor.placar("r_a")["intervencoes_humanas"] == 1


def test_carteira_debita_inferencia_e_credita_honorario():
    db.abrir_carteira("ag1", "Agente 1", 5.0)
    db.debitar_inferencia("ag1", 0.002)
    db.creditar_honorario("ag1", 0.68)
    db.registrar_retido("ag1", 0.22)
    carteira = db.carteira("ag1")
    assert carteira["gasto_inferencia_usd"] == pytest.approx(0.002)
    assert carteira["honorario_usd"] == pytest.approx(0.68)
    assert carteira["retido_usd"] == pytest.approx(0.22)
    assert carteira["saldo_usd"] == pytest.approx(5.0 - 0.002 + 0.68)


def test_historico_do_registry_sai_dos_recibos():
    db.salvar_recibo({"id": "rec1", "rodada_id": "r", "agente_id": "ag2",
                      "skill": "buscar_imoveis", "itens_pedidos": 4, "itens_provados": 1,
                      "preco_usd": 0.35, "pago_usd": 0.09, "retido_usd": 0.26,
                      "motivo": "1 de 4"})
    historico = db.historico("ag2")
    assert historico["entregas"] == 1
    assert historico["taxa_aprovacao"] == 0.25
    assert historico["retido_usd"] == pytest.approx(0.26)


def test_agente_sem_entrega_tem_historico_vazio_e_nao_zero():
    """Quem nunca entregou tem taxa None, não 0: são coisas diferentes na hora
    de decidir quem contratar."""
    historico = db.historico("agente-que-nunca-trabalhou")
    assert historico["entregas"] == 0
    assert historico["taxa_aprovacao"] is None
