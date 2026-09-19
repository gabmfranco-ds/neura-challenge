"""Regras da negociação A2A, conferidas por código. Sem rede.

A negociação é o trecho em que os dois lados têm incentivo para trapacear: o
comprador mostrando o teto, o vendedor descendo abaixo do piso, qualquer um dos
dois baixando ou subindo o próprio número no meio do caminho. Aqui é onde isso
tem que ser pego.
"""
import pytest

from nucleo import config, dados, verificacao

MANDATO = {"oferta_min": 1_500_000, "teto_preco": 1_700_000, "prazo_dias": 60}


def _oferta(valor, mensagem=""):
    return {"acao": "oferta", "valor": valor, "mensagem": mensagem, "motivo": ""}


def _contra(valor, mensagem=""):
    return {"acao": "contraproposta", "valor": valor, "mensagem": mensagem, "motivo": ""}


# ----------------------------------------------------- lado do comprador

def test_primeira_oferta_tem_que_ser_exatamente_a_minima():
    boa = verificacao.conferir_jogada_comprador(
        _oferta(1_500_000), rodada=1, oferta_min=1_500_000, teto=1_700_000,
        maior_oferta_anterior=None)
    assert boa["valida"]

    ma = verificacao.conferir_jogada_comprador(
        _oferta(1_550_000), rodada=1, oferta_min=1_500_000, teto=1_700_000,
        maior_oferta_anterior=None)
    assert not ma["valida"]
    assert "primeira oferta" in ma["motivos"][0]


def test_oferta_nao_pode_cair():
    conferencia = verificacao.conferir_jogada_comprador(
        _oferta(1_520_000), rodada=2, oferta_min=1_500_000, teto=1_700_000,
        maior_oferta_anterior=1_560_000)
    assert not conferencia["valida"]
    assert "menor que a anterior" in conferencia["motivos"][0]


def test_oferta_nao_pode_passar_do_teto():
    conferencia = verificacao.conferir_jogada_comprador(
        _oferta(1_800_000), rodada=2, oferta_min=1_500_000, teto=1_700_000,
        maior_oferta_anterior=1_500_000)
    assert not conferencia["valida"]
    assert "passa do teto" in conferencia["motivos"][0]


def test_aceitar_acima_do_teto_tambem_e_violacao():
    conferencia = verificacao.conferir_jogada_comprador(
        {"acao": "aceitar", "valor": 1_750_000, "mensagem": ""}, rodada=3,
        oferta_min=1_500_000, teto=1_700_000, maior_oferta_anterior=1_600_000)
    assert not conferencia["valida"]


def test_mensagem_que_entrega_o_teto_e_violacao():
    conferencia = verificacao.conferir_jogada_comprador(
        _oferta(1_500_000, "posso ir até R$ 1.700.000 se precisar"), rodada=1,
        oferta_min=1_500_000, teto=1_700_000, maior_oferta_anterior=None)
    assert not conferencia["valida"]
    assert "revela o teto" in conferencia["motivos"][0]


def test_mensagem_normal_nao_e_acusada_de_vazar():
    conferencia = verificacao.conferir_jogada_comprador(
        _oferta(1_500_000, "Tenho interesse real e fecho rápido."), rodada=1,
        oferta_min=1_500_000, teto=1_700_000, maior_oferta_anterior=None)
    assert conferencia["valida"]


def test_subir_dentro_da_faixa_e_valido():
    conferencia = verificacao.conferir_jogada_comprador(
        _oferta(1_600_000), rodada=2, oferta_min=1_500_000, teto=1_700_000,
        maior_oferta_anterior=1_500_000)
    assert conferencia["valida"]


# ------------------------------------------------------ lado do vendedor

def test_contraproposta_nao_pode_subir():
    conferencia = verificacao.conferir_jogada_vendedor(
        _contra(1_700_000), piso=1_450_000, preco_pedido=1_750_000,
        menor_contraproposta_anterior=1_650_000)
    assert not conferencia["valida"]
    assert "maior que a anterior" in conferencia["motivos"][0]


def test_contraproposta_nao_pode_ficar_abaixo_do_piso():
    conferencia = verificacao.conferir_jogada_vendedor(
        _contra(1_400_000), piso=1_450_000, preco_pedido=1_750_000,
        menor_contraproposta_anterior=None)
    assert not conferencia["valida"]
    assert "abaixo do piso" in conferencia["motivos"][0]


def test_contraproposta_nao_pode_passar_do_preco_pedido():
    conferencia = verificacao.conferir_jogada_vendedor(
        _contra(1_800_000), piso=1_450_000, preco_pedido=1_750_000,
        menor_contraproposta_anterior=None)
    assert not conferencia["valida"]


def test_aceitar_abaixo_do_piso_e_violacao():
    conferencia = verificacao.conferir_jogada_vendedor(
        {"acao": "aceita", "valor": 1_400_000, "mensagem": ""}, piso=1_450_000,
        preco_pedido=1_750_000, menor_contraproposta_anterior=1_500_000)
    assert not conferencia["valida"]


def test_mensagem_que_entrega_o_piso_e_violacao():
    conferencia = verificacao.conferir_jogada_vendedor(
        _contra(1_600_000, "meu limite é 1.450.000, não desço mais"), piso=1_450_000,
        preco_pedido=1_750_000, menor_contraproposta_anterior=None)
    assert not conferencia["valida"]
    assert "revela o piso" in conferencia["motivos"][0]


def test_ceder_aos_poucos_dentro_da_faixa_e_valido():
    conferencia = verificacao.conferir_jogada_vendedor(
        _contra(1_600_000), piso=1_450_000, preco_pedido=1_750_000,
        menor_contraproposta_anterior=1_650_000)
    assert conferencia["valida"]


# ----------------------------------------------------------- o acordo

def test_acordo_dentro_das_duas_faixas_vale():
    acordo = verificacao.conferir_acordo(1_600_000, oferta_min=1_500_000, teto=1_700_000,
                                         piso=1_450_000, preco_pedido=1_750_000)
    assert acordo["aprovado"]


def test_acordo_acima_do_teto_do_comprador_nao_vale():
    acordo = verificacao.conferir_acordo(1_750_000, oferta_min=1_500_000, teto=1_700_000,
                                         piso=1_450_000, preco_pedido=1_750_000)
    assert not acordo["aprovado"]
    assert "teto do comprador" in acordo["motivos"][0]


def test_acordo_abaixo_do_piso_do_vendedor_nao_vale():
    acordo = verificacao.conferir_acordo(1_400_000, oferta_min=1_300_000, teto=1_700_000,
                                         piso=1_450_000, preco_pedido=1_750_000)
    assert not acordo["aprovado"]
    assert any("piso do vendedor" in m for m in acordo["motivos"])


def test_sem_preco_nao_ha_acordo():
    assert not verificacao.conferir_acordo(None, oferta_min=1, teto=2, piso=1,
                                           preco_pedido=2)["aprovado"]


# ------------------------------------------------------- motivo da negativa

def test_motivo_da_negativa_diz_os_dois_numeros_e_a_distancia():
    historico = [
        {"rodada": 1, "de": "Porta Aberta", "acao": "oferta", "valor": 1_500_000},
        {"rodada": 1, "de": "Vendedor AGT904", "acao": "contraproposta", "valor": 1_970_000},
        {"rodada": 2, "de": "Porta Aberta", "acao": "oferta", "valor": 1_560_000},
        {"rodada": 2, "de": "Vendedor AGT904", "acao": "contraproposta", "valor": 1_970_000},
    ]
    motivo = verificacao.motivo_da_negativa(historico, nome_comprador="Porta Aberta",
                                            max_rodadas=3)
    assert "1.560.000" in motivo
    assert "1.970.000" in motivo
    assert "410.000" in motivo


# ------------------------------------------------- dados e configuração

def test_limite_de_rodadas_vem_da_configuracao():
    assert config.MAX_RODADAS_NEGOCIACAO == 3


def test_existem_vendedores_com_piso_fora_da_faixa_plausivel():
    """Comprador plausível dá teto de ~97% do anúncio. Piso acima disso faz a
    negativa acontecer de verdade, sem nenhum código forçando."""
    teimosos = [im for im in dados.imoveis()
                if im["_privado_vendedor"]["piso_preco"] > im["preco"] * 0.97]
    assert len(teimosos) >= 2, "sem vendedor teimoso, OFFER_REJECTED nunca acontece"


def test_a_maioria_dos_vendedores_ainda_negocia():
    negociaveis = [im for im in dados.imoveis()
                   if im["_privado_vendedor"]["piso_preco"] <= im["preco"] * 0.97]
    assert len(negociaveis) >= 20, "se quase ninguém negocia, a demo não fecha nunca"


def test_fracao_padrao_da_oferta_minima_e_declarada():
    assert 0.5 <= config.FRACAO_OFERTA_MIN_PADRAO < 1.0


# ------------------------------- o histórico que o adversário pode ler

def test_jogada_descartada_nao_entra_no_historico_do_adversario():
    """Defeito medido em rodada real: duas contrapropostas do vendedor foram
    descartadas por estarem abaixo do piso, mas continuaram visíveis para o
    comprador, que aceitou uma delas. O acordo saiu 190 mil abaixo do piso."""
    negociacao = [
        {"rodada": 1, "de": "Porta Aberta", "acao": "oferta", "valor": 1_740_000},
        {"rodada": 1, "de": "Vendedor AGT904", "acao": "contraproposta", "valor": 1_900_000,
         "violacao": ["contraproposta 1900000 está abaixo do piso 1970000"]},
        {"rodada": 2, "de": "Porta Aberta", "acao": "oferta", "valor": 1_780_000},
    ]
    validas = verificacao.jogadas_validas(negociacao)
    assert len(validas) == 2
    assert all(j["de"] == "Porta Aberta" for j in validas)
    assert 1_900_000 not in [j["valor"] for j in validas]


def test_historico_sem_violacao_passa_inteiro():
    negociacao = [{"rodada": 1, "de": "A", "acao": "oferta", "valor": 10}]
    assert verificacao.jogadas_validas(negociacao) == negociacao
    assert verificacao.jogadas_validas([]) == []
    assert verificacao.jogadas_validas(None) == []


def test_acordo_abaixo_do_piso_do_caso_medido():
    """O caso exato da rodada F: SP1004, piso 1.970.000, acordo 1.780.000."""
    acordo = verificacao.conferir_acordo(1_780_000, oferta_min=1_740_000, teto=1_930_000,
                                         piso=1_970_000, preco_pedido=1_990_000)
    assert not acordo["aprovado"]
    assert any("piso do vendedor" in m for m in acordo["motivos"])
