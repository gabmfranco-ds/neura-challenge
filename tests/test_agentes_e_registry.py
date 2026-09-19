"""Fichas, Registry e o caminho do modelo, tudo com dublê. Nenhuma chamada sai.

O dublê aqui é explícito de propósito: ele devolve o objeto que o modelo
devolveria, e nada mais. Se o código passar a depender de algo que o modelo não
dá, o teste quebra em vez de passar por acaso.
"""
import asyncio

import pytest

from agentes import catalogo, comum
from agentes.property import agente as property_agente
from nucleo import db


# ------------------------------------------------------------ fichas A2A

def test_toda_ficha_tem_o_que_o_registry_exige():
    for ficha in catalogo.todas_as_fichas():
        assert ficha.get("agente_id"), ficha
        assert ficha.get("url", "").startswith("http")
        assert ficha.get("skills"), ficha["agente_id"]
        for skill in ficha["skills"]:
            assert skill.get("id") and skill.get("description")
            assert "entrada" in skill and "saida" in skill


def test_toda_ficha_pede_auto_por_padrao():
    for ficha in catalogo.todas_as_fichas():
        assert ficha["capacidade_neuralake"] == "auto", ficha["agente_id"]


def test_cada_capacidade_que_importa_tem_dois_concorrentes():
    fichas = catalogo.todas_as_fichas()
    for capacidade in ("buscar_imoveis", "conduzir_transacao", "custodia_pagamento"):
        quantos = [f for f in fichas if any(s["id"] == capacidade for s in f["skills"])]
        assert len(quantos) >= 2, f"{capacidade} tem só {len(quantos)} agente"
        precos = {f["preco_usd"] for f in quantos}
        assert len(precos) >= 2, f"{capacidade}: concorrentes com o mesmo preço"


def test_as_duas_variantes_de_property_declaram_acesso_a_dados_diferente():
    cara = catalogo.ficha("property-casa-verificada")
    barata = catalogo.ficha("property-busca-relampago")
    assert "texto dos documentos" in cara["acesso_a_dados"]
    assert cara["acesso_a_dados"] != barata["acesso_a_dados"]
    assert barata["acesso_a_dados"].startswith("somente o anuncio")
    assert barata["preco_usd"] < cara["preco_usd"]


def test_agentes_simulados_estao_marcados_como_simulados():
    for agente_id in ("transaction-cartorio-digital", "transaction-fecha-rapido",
                      "payment-escrow-guardiao", "payment-liquida-ja"):
        assert catalogo.ficha(agente_id)["simulado"] is True


def test_seller_tem_um_agente_por_imovel():
    from nucleo import dados
    sellers = [f for f in catalogo.todas_as_fichas() if f["papel"] == "seller"]
    assert len(sellers) == len(dados.imoveis())


def test_ficha_nao_vaza_piso_nem_pressa_do_vendedor():
    """O piso do proprietário é segredo do Seller Agent. Se o NÚMERO vazar na
    ficha pública, o comprador negocia com carta marcada. A ficha pode dizer que
    existe um piso; o que ela não pode é dizer qual."""
    import json
    from nucleo import dados
    texto = json.dumps(catalogo.todas_as_fichas(), ensure_ascii=False)
    assert "piso_preco" not in texto
    assert "_privado_vendedor" not in texto
    for imovel in dados.imoveis():
        privado = imovel["_privado_vendedor"]
        assert str(privado["piso_preco"]) not in texto, imovel["property_id"]
        assert f"\"pressa\": {privado['pressa']}" not in texto


# ------------------------------------------------- visões de dados por ficha

def test_visao_do_anuncio_nao_tem_disponibilidade_nem_documento():
    from nucleo import dados
    imovel = dados.imovel("SP1005")
    anuncio = dados.visao_anuncio(imovel)
    assert "disponibilidade" not in anuncio
    assert "documentos" not in anuncio
    assert "_privado_vendedor" not in anuncio


def test_visao_completa_tem_disponibilidade_e_documento():
    from nucleo import dados
    completa = dados.visao_completa(dados.imovel("SP1005"))
    assert completa["disponibilidade"] == "unavailable"
    assert "MATRICULA" in completa["documentos"]
    assert "_privado_vendedor" not in completa


# ------------------------------------------------- desembrulhar resposta

def test_lista_aninhada_do_modelo_e_desembrulhada():
    """Medido contra a API real: o modelo devolveu {"itens":[{"itens":[...]}]}."""
    aninhado = {"itens": [{"itens": [{"property_id": "SP1008"}, {"property_id": "SP1002"}]}]}
    itens = property_agente.extrair_itens(aninhado)
    assert [i["property_id"] for i in itens] == ["SP1008", "SP1002"]


def test_lista_normal_continua_funcionando():
    normal = {"itens": [{"property_id": "SP1008"}]}
    assert len(property_agente.extrair_itens(normal)) == 1


def test_lixo_do_modelo_vira_lista_vazia_e_nao_explode():
    assert property_agente.extrair_itens(None) == []
    assert property_agente.extrair_itens("texto solto") == []
    assert property_agente.extrair_itens({"resposta": "nao achei nada"}) == []


# ---------------------------------------------- defesas do cliente

def test_think_e_removido():
    assert comum.remover_think("<think>penso muito</think>resposta") == "resposta"
    assert comum.remover_think("<think>sem fechar nunca") == ""
    assert comum.remover_think("resposta limpa") == "resposta limpa"


def test_extrator_acha_json_no_meio_da_prosa():
    import json
    texto = 'Claro! Aqui esta:\n```json\n{"a": 1, "b": [2, 3]}\n```\nEspero ter ajudado.'
    assert json.loads(comum.extrair_json(texto)) == {"a": 1, "b": [2, 3]}


def test_extrator_nao_se_perde_com_chave_dentro_de_string():
    import json
    texto = '{"motivo": "tem { e } no texto", "ok": true}'
    assert json.loads(comum.extrair_json(texto))["ok"] is True


def test_extrator_devolve_none_quando_nao_ha_json():
    assert comum.extrair_json("sem json nenhum aqui") is None
    assert comum.extrair_json("") is None


# ------------------------------------- chamada ao modelo, com dublê

class _RespostaFalsa:
    def __init__(self, conteudo):
        self.content = conteudo


def _dublar(monkeypatch, conteudo, custo=0.0005, modelo_roteado="text"):
    """Substitui o Agent do Agno e o gancho de custo. Nada sai pela rede."""
    class AgenteFalso:
        async def arun(self, entrada):
            caixa = comum.modelo._CAIXA.get()
            if caixa is not None:
                caixa.append({"custo_usd": custo, "modelo_roteado": modelo_roteado,
                              "finish_reason": "stop", "status": 200})
            return _RespostaFalsa(conteudo)

    monkeypatch.setattr(comum, "agente", lambda *a, **k: AgenteFalso())


FICHA_TESTE = {"agente_id": "ag-teste", "name": "Agente de Teste",
               "description": "faz teste", "estrategia": "responder",
               "capacidade_neuralake": "auto"}


def test_chamada_registra_evento_com_custo_e_modelo_roteado(monkeypatch):
    _dublar(monkeypatch, '{"ok": true}')
    objeto, resultado = asyncio.run(comum.pedir_json(
        FICHA_TESTE, [{"role": "user", "content": "oi"}], etapa="teste", rodada_id="rt1"))
    assert objeto == {"ok": True}
    assert resultado.custo_usd == pytest.approx(0.0005)
    assert resultado.modelo_roteado == "text"
    assert resultado.plano_b is False

    eventos = db.eventos_desde(0, "rt1")
    assert len(eventos) == 1
    assert eventos[0]["tipo"] == "chamada"
    assert eventos[0]["dados"]["capacidade_pedida"] == "auto"
    assert eventos[0]["dados"]["modelo_roteado"] == "text"
    assert eventos[0]["custo_usd"] == pytest.approx(0.0005)


def test_carteira_do_agente_e_debitada_pelo_custo_real(monkeypatch):
    _dublar(monkeypatch, '{"ok": true}', custo=0.0012)
    asyncio.run(comum.pedir_json(FICHA_TESTE, [{"role": "user", "content": "oi"}],
                                 etapa="teste", rodada_id="rt2"))
    assert db.carteira("ag-teste")["gasto_inferencia_usd"] == pytest.approx(0.0012)


def test_corpo_vazio_repete_e_registra_plano_b(monkeypatch):
    """Corpo vazio é queima de raciocínio. Repete e, se não colar, cai para text."""
    _dublar(monkeypatch, "")
    objeto, resultado = asyncio.run(comum.pedir_json(
        FICHA_TESTE, [{"role": "user", "content": "oi"}], etapa="teste", rodada_id="rt3"))
    assert objeto is None
    assert resultado.tentativas >= 2, "não repetiu depois do corpo vazio"
    assert resultado.capacidade_usada == "text"
    assert resultado.plano_b is True
    assert "vazio" in resultado.motivo_plano_b


def test_falha_do_modelo_nao_derruba_a_rodada(monkeypatch):
    class AgenteQueQuebra:
        async def arun(self, entrada):
            raise RuntimeError("a NeuraLake respondeu 504")

    monkeypatch.setattr(comum, "agente", lambda *a, **k: AgenteQueQuebra())
    objeto, resultado = asyncio.run(comum.pedir_json(
        FICHA_TESTE, [{"role": "user", "content": "oi"}], etapa="teste", rodada_id="rt4"))
    assert objeto is None
    assert "504" in resultado.motivo_plano_b


def test_resposta_com_prosa_em_volta_ainda_vira_json(monkeypatch):
    _dublar(monkeypatch, 'Segue o resultado:\n{"itens": []}\nabraco')
    objeto, _ = asyncio.run(comum.pedir_json(
        FICHA_TESTE, [{"role": "user", "content": "oi"}], etapa="teste", rodada_id="rt5"))
    assert objeto == {"itens": []}
