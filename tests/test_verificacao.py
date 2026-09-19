"""Verificação por conta de código. É ela que sustenta o pagamento proporcional.

Os casos usam os documentos REAIS de `dados/`, inclusive os dois defeitos
plantados, porque um dublê de documento esconderia justamente o que interessa:
se o texto mudar de formato, este teste tem que quebrar.
"""
import datetime as dt

from nucleo import dados, verificacao


# ------------------------------------------------------------- documentos

def test_documento_limpo_passa():
    analise = verificacao.status_documentacao("SP1008")
    assert analise["status"] == verificacao.STATUS_OK
    assert analise["pendencias"] == []


def test_hipoteca_ativa_na_matricula_reprova():
    analise = verificacao.status_documentacao("SP1003")
    assert analise["status"] == verificacao.STATUS_PENDENCIA
    assert any("ônus ativo" in p for p in analise["pendencias"])
    assert "matricula" in analise["pendencias_por_fonte"]


def test_hipoteca_cancelada_nao_reprova():
    """SP1008 tem AV de hipoteca CANCELADA: baixada não é ônus."""
    analise = verificacao.status_documentacao("SP1008")
    assert analise["achados"]["matricula"]["onus_ativos"] == []


def test_certidao_vencida_reprova():
    analise = verificacao.status_documentacao("SP1010")
    assert analise["status"] == verificacao.STATUS_PENDENCIA
    assert any("vencida" in p for p in analise["pendencias"])
    assert "certidao_distribuicao" in analise["pendencias_por_fonte"]


def test_certidao_vale_enquanto_esta_na_validade():
    """A mesma certidão de SP1010 passa se a data de hoje for antes do vencimento."""
    analise = verificacao.status_documentacao("SP1010", hoje=dt.date(2026, 5, 1))
    assert not any("vencida" in p for p in analise["pendencias"])


def test_sem_documento_nenhum():
    analise = verificacao.analisar_documentos(None)
    assert analise["status"] == verificacao.STATUS_SEM_DOCUMENTOS


def test_documento_sem_os_marcadores_conhecidos_nao_passa_por_limpo():
    analise = verificacao.analisar_documentos("um texto qualquer sem seção nenhuma")
    assert analise["status"] == verificacao.STATUS_PENDENCIA
    assert len(analise["pendencias"]) >= 4


# ------------------------------------------------------- entrega de busca

def _item(property_id, **troca):
    base = dados.imovel(property_id)
    item = {
        "property_id": property_id, "preco": base["preco"], "area": base["area"],
        "quartos": base["quartos"], "vagas": base["vagas"],
        "localizacao": base["bairro"], "seller_agent": base["seller_agent"],
        "disponibilidade": "available", "documentacao_status": "basic_verified",
        "motivo": "serve",
    }
    item.update(troca)
    return item


def test_imovel_bom_passa(pedido):
    conferencia = verificacao.conferir_busca([_item("SP1008")], pedido)
    assert conferencia["provados"] == 1
    assert conferencia["reprovados"] == []


def test_imovel_inventado_reprova(pedido):
    conferencia = verificacao.conferir_busca([{"property_id": "SP9999"}], pedido)
    assert conferencia["provados"] == 0
    assert "não existe na base" in conferencia["reprovados"][0]["motivos"][0]


def test_indisponivel_reprova_mesmo_afirmado_como_disponivel(pedido):
    """SP1005 está unavailable na base. Dizer available na entrega não salva."""
    conferencia = verificacao.conferir_busca([_item("SP1005")], pedido)
    assert conferencia["provados"] == 0
    assert any("unavailable" in m for m in conferencia["reprovados"][0]["motivos"])


def test_documentacao_afirmada_a_mais_reprova(pedido):
    """SP1003 tem ônus. Afirmar basic_verified é exatamente o erro que pegamos."""
    conferencia = verificacao.conferir_busca([_item("SP1003")], pedido)
    assert conferencia["provados"] == 0
    assert any("documentação afirmada" in m for m in conferencia["reprovados"][0]["motivos"])


def test_numero_alterado_pelo_agente_reprova(pedido):
    conferencia = verificacao.conferir_busca([_item("SP1008", preco=900000)], pedido)
    assert conferencia["provados"] == 0
    assert any("não bate com a base" in m for m in conferencia["reprovados"][0]["motivos"])


def test_filtro_do_pedido_e_cobrado(pedido):
    apertado = {**pedido, "quartos_min": 5}
    conferencia = verificacao.conferir_busca([_item("SP1008")], apertado)
    assert conferencia["provados"] == 0
    assert any("quartos" in m for m in conferencia["reprovados"][0]["motivos"])


def test_entrega_calada_sobre_documentacao_reprova(pedido):
    item = _item("SP1008")
    item["documentacao_status"] = ""
    conferencia = verificacao.conferir_busca([item], pedido)
    assert conferencia["provados"] == 0


def test_comparacao_com_a_mediana_do_bairro(pedido):
    conferencia = verificacao.conferir_busca([_item("SP1008")], pedido)
    comparacao = conferencia["itens"][0]["conferido"]["comparacao_preco"]
    assert comparacao["mediana_bairro_m2"] > 0
    esperado = dados.mediana_bairro("Vila Madalena")
    assert comparacao["mediana_bairro_m2"] == esperado


# --------------------------------------------------------------- mandato

def test_acordo_dentro_do_teto_passa():
    assert verificacao.conferir_mandato(1600000, {"teto_preco": 1700000})["aprovado"]


def test_acordo_acima_do_teto_reprova():
    conferencia = verificacao.conferir_mandato(1800000, {"teto_preco": 1700000})
    assert not conferencia["aprovado"]
    assert "passa do teto" in conferencia["motivos"][0]


def test_sem_preco_acordado_reprova():
    assert not verificacao.conferir_mandato(None, {"teto_preco": 1700000})["aprovado"]


# --------------------------------------------- condições e pagamento

def _condicoes(**status):
    catalogo = dados.criterios_fechamento()["condicoes"]
    return [{**c, "status": status.get(c["id"], "atendida")} for c in catalogo]


def test_todas_atendidas_libera():
    assert verificacao.conferir_condicoes(_condicoes(), ate_fase="CONDITIONS_MET")["aprovado"]


def test_uma_obrigatoria_pendente_nao_libera():
    condicoes = _condicoes(itbi_recolhido="pendente")
    conferencia = verificacao.conferir_condicoes(condicoes, ate_fase="CONDITIONS_MET")
    assert not conferencia["aprovado"]
    assert conferencia["pendentes"][0]["id"] == "itbi_recolhido"


def test_condicao_de_fase_futura_nao_trava_o_pagamento():
    """Registro na matrícula só acontece DEPOIS do pagamento: cobrar antes
    travaria a compra para sempre."""
    condicoes = _condicoes(registro_na_matricula="pendente")
    assert verificacao.conferir_condicoes(condicoes, ate_fase="CONDITIONS_MET")["aprovado"]
    assert not verificacao.conferir_condicoes(condicoes)["aprovado"]


def test_condicao_opcional_pendente_nao_trava():
    condicoes = _condicoes(financiamento_aprovado="pendente")
    assert verificacao.conferir_condicoes(condicoes, ate_fase="CONDITIONS_MET")["aprovado"]


def test_pagamento_proporcional():
    assert verificacao.pagamento_proporcional(0.90, 4, 3) == (0.675, 0.225)
    assert verificacao.pagamento_proporcional(0.90, 4, 0) == (0.0, 0.9)
    assert verificacao.pagamento_proporcional(0.90, 4, 4) == (0.9, 0.0)


def test_entrega_vazia_nao_paga_nada():
    pago, retido = verificacao.pagamento_proporcional(0.90, 0, 0)
    assert pago == 0.0
    assert retido == 0.90
