"""Máquina de estados: o que pode e, principalmente, o que NÃO pode."""
import pytest

from nucleo import estados


def test_caminho_feliz_inteiro_e_valido():
    for de, para in zip(estados.TRILHO, estados.TRILHO[1:]):
        assert estados.pode(de, para), f"{de} -> {para} deveria ser válido"


def test_nao_da_para_pular_etapa():
    assert not estados.pode("SEARCH", "OFFER_ACCEPTED")
    assert not estados.pode("SHORTLIST", "COMPLETED")
    assert not estados.pode("KYC_PENDING", "PAYMENT_RELEASED")


def test_pagamento_nao_sai_antes_das_condicoes():
    """FUNDS_LOCKED nunca vai direto para PAYMENT_RELEASED: passa por CONDITIONS_MET."""
    assert not estados.pode("FUNDS_LOCKED", "PAYMENT_RELEASED")
    assert estados.pode("FUNDS_LOCKED", "CONDITIONS_MET")
    assert estados.pode("CONDITIONS_MET", "PAYMENT_RELEASED")


def test_estado_terminal_nao_anda_mais():
    assert estados.TRANSICOES["COMPLETED"] == set()
    assert estados.TRANSICOES["ABORTED"] == set()
    with pytest.raises(estados.TransicaoInvalida):
        estados.exigir("COMPLETED", "SEARCH")


def test_recusa_volta_para_a_shortlist():
    """Vendedor recusar não mata a compra: o comprador escolhe outro imóvel."""
    assert estados.pode("OFFER_REJECTED", "SHORTLIST")


def test_busca_pode_ser_refeita_depois_da_shortlist():
    assert estados.pode("SHORTLIST", "SEARCH")


def test_toda_fase_pode_abortar_com_motivo():
    """Só PROPERTY_TRANSFERRED não aborta: depois que o imóvel mudou de dono,
    não existe mais desistir, existe desfazer, que é outra história."""
    for estado in estados.TRILHO[:-1]:
        if estado == "PROPERTY_TRANSFERRED":
            continue
        assert "ABORTED" in estados.TRANSICOES[estado], f"{estado} não tem saída de falha"


def test_estado_desconhecido_levanta():
    with pytest.raises(estados.TransicaoInvalida):
        estados.exigir("SEARCH", "ESTADO_QUE_NAO_EXISTE")
    with pytest.raises(estados.TransicaoInvalida):
        estados.exigir("INVENTADO", "SHORTLIST")
