"""Testes das checagens declarativas. Sem rede, sem banco."""
from evals.checagens import Contexto, rodar_checagens


def ctx(saida=None, texto="", entrada=None, esperado=None):
    return Contexto(saida=saida, texto=texto, entrada=entrada or {}, esperado=esperado or {})


def test_json_valido_falha_quando_none():
    ok, nota, falhas = rodar_checagens([{"tipo": "json_valido"}], ctx(saida=None))
    assert not ok
    assert nota == 0.0
    assert falhas[0]["checagem"] == "json_valido"


def test_json_valido_passa():
    ok, nota, falhas = rodar_checagens([{"tipo": "json_valido"}], ctx(saida={"a": 1}))
    assert ok and nota == 1.0 and not falhas


def test_campos_obrigatorios_detecta_faltante():
    ok, nota, falhas = rodar_checagens(
        [{"tipo": "campos_obrigatorios", "campos": ["pedido.cidade", "pedido.preco_max"]}],
        ctx(saida={"pedido": {"cidade": "São Paulo"}}))
    assert not ok
    assert "pedido.preco_max" in falhas[0]["motivo"]


def test_igual_normaliza_acento_e_maiuscula():
    ok, _, _ = rodar_checagens(
        [{"tipo": "igual", "campo": "pedido.tipo", "valor": "Apartamento"}],
        ctx(saida={"pedido": {"tipo": "APARTAMENTO"}}))
    assert ok


def test_diferente_de_com_valor_fixo():
    ok, _, falhas = rodar_checagens(
        [{"tipo": "diferente_de", "campo": "pedido.preco_max", "valor": 0}],
        ctx(saida={"pedido": {"preco_max": 0}}))
    assert not ok


def test_diferente_de_com_referencia_a_entrada():
    ok, _, _ = rodar_checagens(
        [{"tipo": "diferente_de", "campo": "escolhido", "campo_referencia": "agente_reprovado_id"}],
        ctx(saida={"escolhido": "agt-bom"}, entrada={"agente_reprovado_id": "agt-ruim"}))
    assert ok
    ok2, _, _ = rodar_checagens(
        [{"tipo": "diferente_de", "campo": "escolhido", "campo_referencia": "agente_reprovado_id"}],
        ctx(saida={"escolhido": "agt-ruim"}, entrada={"agente_reprovado_id": "agt-ruim"}))
    assert not ok2


def test_contem_todos():
    ok, _, _ = rodar_checagens(
        [{"tipo": "contem_todos", "campo": "pedido.bairros", "lista": ["Pinheiros"]}],
        ctx(saida={"pedido": {"bairros": ["pinheiros", "Moema"]}}))
    assert ok


def test_contem_algum():
    ok, _, _ = rodar_checagens(
        [{"tipo": "contem_algum", "campo": "motivo", "lista": ["preço", "documenta"]}],
        ctx(saida={"motivo": "Escolhi porque o preco era melhor"}))
    assert ok


def test_numero_entre():
    ok, _, falhas = rodar_checagens(
        [{"tipo": "numero_entre", "campo": "valor", "min": 100, "max": 200}],
        ctx(saida={"valor": 250}))
    assert not ok


def test_enum():
    ok, _, _ = rodar_checagens(
        [{"tipo": "enum", "campo": "acao", "valores": ["oferta", "aceitar", "desistir"]}],
        ctx(saida={"acao": "OFERTA"}))
    assert ok


def test_sem_think_detecta_vazamento():
    ok, _, _ = rodar_checagens([{"tipo": "sem_think"}],
                               ctx(texto="<think>planejando...</think>resposta final"))
    assert not ok


def test_nao_vazio():
    ok, _, _ = rodar_checagens([{"tipo": "nao_vazio"}], ctx(texto="   "))
    assert not ok


def test_respeita_piso_aceita_abaixo_falha():
    ok, _, falhas = rodar_checagens(
        [{"tipo": "respeita_piso", "piso_entrada": "piso"}],
        ctx(saida={"acao": "aceita", "valor": 500}, entrada={"piso": 900}))
    assert not ok
    assert "ABAIXO DO PISO" in falhas[0]["motivo"]


def test_respeita_piso_aceita_acima_passa():
    ok, _, _ = rodar_checagens(
        [{"tipo": "respeita_piso", "piso_entrada": "piso"}],
        ctx(saida={"acao": "aceita", "valor": 950}, entrada={"piso": 900}))
    assert ok


def test_respeita_teto_passou_do_teto_falha():
    ok, _, falhas = rodar_checagens(
        [{"tipo": "respeita_teto", "teto_entrada": "mandato.teto_preco"}],
        ctx(saida={"acao": "oferta", "valor": 1200000},
            entrada={"mandato": {"teto_preco": 1000000}}))
    assert not ok
    assert "PASSOU DO TETO" in falhas[0]["motivo"]


def test_documentacao_bate_com_base_passa_com_lista_vazia():
    ok, _, _ = rodar_checagens([{"tipo": "documentacao_bate_com_base"}], ctx(saida={"itens": []}))
    assert ok


def test_lista_nao_vazia():
    ok, _, _ = rodar_checagens([{"tipo": "lista_nao_vazia", "campo": "itens", "minimo": 1}],
                               ctx(saida={"itens": []}))
    assert not ok


def test_checagem_desconhecida_vira_falha_sem_derrubar():
    ok, nota, falhas = rodar_checagens([{"tipo": "isso_nao_existe"}], ctx(saida={}))
    assert not ok
    assert "desconhecida" in falhas[0]["motivo"]


def test_nota_e_fracao_de_checagens_que_passaram():
    ok, nota, falhas = rodar_checagens(
        [{"tipo": "json_valido"}, {"tipo": "nao_vazio"}],
        ctx(saida={"a": 1}, texto=""))
    assert not ok
    assert nota == 0.5


def test_sem_checagens_passa_por_padrao():
    ok, nota, falhas = rodar_checagens([], ctx())
    assert ok and nota == 1.0 and not falhas


# --------------------------- regra de negociação nova (faixa, não revela limite)

def test_nao_revela_limite_detecta_numero_cru():
    ok, _, falhas = rodar_checagens(
        [{"tipo": "nao_revela_limite", "limite_entrada": "limite"}],
        ctx(saida={"mensagem": "Meu teto e 1000000, nao passo disso."}, entrada={"limite": 1000000}))
    assert not ok


def test_nao_revela_limite_detecta_abreviado_mi():
    ok, _, _ = rodar_checagens(
        [{"tipo": "nao_revela_limite", "limite_entrada": "limite"}],
        ctx(saida={"mensagem": "Nao posso passar de 1,8 mi de jeito nenhum."},
            entrada={"limite": 1800000}))
    assert not ok


def test_nao_revela_limite_passa_quando_nao_menciona():
    ok, _, _ = rodar_checagens(
        [{"tipo": "nao_revela_limite", "limite_entrada": "limite"}],
        ctx(saida={"mensagem": "Essa e minha oferta por enquanto."}, entrada={"limite": 1800000}))
    assert ok


def test_primeira_oferta_igual_min_na_primeira_rodada():
    ok, _, falhas = rodar_checagens(
        [{"tipo": "primeira_oferta_igual_min"}],
        ctx(saida={"valor": 900000},
            entrada={"mandato": {"oferta_min": 850000}, "historico": []}))
    assert not ok
    ok2, _, _ = rodar_checagens(
        [{"tipo": "primeira_oferta_igual_min"}],
        ctx(saida={"valor": 850000},
            entrada={"mandato": {"oferta_min": 850000}, "historico": []}))
    assert ok2


def test_primeira_oferta_igual_min_nao_se_aplica_com_historico():
    ok, _, _ = rodar_checagens(
        [{"tipo": "primeira_oferta_igual_min"}],
        ctx(saida={"valor": 950000},
            entrada={"mandato": {"oferta_min": 850000},
                    "historico": [{"de": "comprador", "acao": "oferta", "valor": 850000}]}))
    assert ok


def test_ofertas_nao_decrescentes():
    historico = [{"de": "comprador", "acao": "oferta", "valor": 900000}]
    ok, _, _ = rodar_checagens(
        [{"tipo": "ofertas_nao_decrescentes"}],
        ctx(saida={"acao": "oferta", "valor": 850000}, entrada={"historico": historico}))
    assert not ok
    ok2, _, _ = rodar_checagens(
        [{"tipo": "ofertas_nao_decrescentes"}],
        ctx(saida={"acao": "oferta", "valor": 950000}, entrada={"historico": historico}))
    assert ok2


def test_contrapropostas_nao_crescentes():
    historico = [{"de": "vendedor", "acao": "contraproposta", "valor": 1200000}]
    ok, _, _ = rodar_checagens(
        [{"tipo": "contrapropostas_nao_crescentes"}],
        ctx(saida={"acao": "contraproposta", "valor": 1300000}, entrada={"historico": historico}))
    assert not ok
    ok2, _, _ = rodar_checagens(
        [{"tipo": "contrapropostas_nao_crescentes"}],
        ctx(saida={"acao": "contraproposta", "valor": 1100000}, entrada={"historico": historico}))
    assert ok2


def test_acordo_dentro_das_duas_faixas():
    ok, _, falhas = rodar_checagens(
        [{"tipo": "acordo_dentro_das_duas_faixas"}],
        ctx(saida={"acordo": True, "preco_final": 2000000},
            entrada={"vendedor": {"piso": 1000000}, "comprador": {"teto_preco": 1500000}}))
    assert not ok
    ok2, _, _ = rodar_checagens(
        [{"tipo": "acordo_dentro_das_duas_faixas"}],
        ctx(saida={"acordo": True, "preco_final": 1200000},
            entrada={"vendedor": {"piso": 1000000}, "comprador": {"teto_preco": 1500000}}))
    assert ok2


def test_rejeita_quando_faixas_nao_se_cruzam():
    ok, _, falhas = rodar_checagens(
        [{"tipo": "rejeita_quando_faixas_nao_se_cruzam"}],
        ctx(saida={"acordo": True},
            entrada={"vendedor": {"piso": 1500000}, "comprador": {"teto_preco": 1000000}}))
    assert not ok
    ok2, _, _ = rodar_checagens(
        [{"tipo": "rejeita_quando_faixas_nao_se_cruzam"}],
        ctx(saida={"acordo": False},
            entrada={"vendedor": {"piso": 1500000}, "comprador": {"teto_preco": 1000000}}))
    assert ok2
    ok3, _, _ = rodar_checagens(
        [{"tipo": "rejeita_quando_faixas_nao_se_cruzam"}],
        ctx(saida={"acordo": True},
            entrada={"vendedor": {"piso": 1000000}, "comprador": {"teto_preco": 1500000}}))
    assert ok3  # faixas se cruzam, checagem não se aplica


# ------------------------ checagens "_no_historico" (negociacao_completa)

def test_nao_revela_limite_no_historico_detecta_qualquer_turno():
    saida = {"historico": [
        {"rodada": 1, "de": "comprador", "acao": "oferta", "valor": 900000, "mensagem": "Minha oferta."},
        {"rodada": 1, "de": "vendedor", "acao": "contraproposta", "valor": 1100000,
         "mensagem": "Meu piso e 1000000, nao desco disso."},
    ]}
    ok, _, falhas = rodar_checagens(
        [{"tipo": "nao_revela_limite_no_historico"}],
        ctx(saida=saida, entrada={"comprador": {"oferta_min": 850000, "teto_preco": 1000000},
                                  "vendedor": {"piso": 1000000}}))
    assert not ok


def test_ofertas_nao_decrescentes_no_historico():
    saida = {"historico": [
        {"de": "comprador", "acao": "oferta", "valor": 900000},
        {"de": "vendedor", "acao": "contraproposta", "valor": 1100000},
        {"de": "comprador", "acao": "oferta", "valor": 880000},
    ]}
    ok, _, _ = rodar_checagens([{"tipo": "ofertas_nao_decrescentes_no_historico"}], ctx(saida=saida))
    assert not ok


def test_primeira_oferta_igual_min_no_historico():
    saida = {"historico": [{"de": "comprador", "acao": "oferta", "valor": 900000}]}
    ok, _, _ = rodar_checagens(
        [{"tipo": "primeira_oferta_igual_min_no_historico"}],
        ctx(saida=saida, entrada={"comprador": {"oferta_min": 850000}}))
    assert not ok


# --------------------------- desembrulho de itens (property_busca)

def test_itens_da_saida_desembrulha_lista_de_dict_com_itens():
    from evals.checagens import _itens_da_saida
    # forma medida contra a API real em 19/09/2026: lista contendo um dict
    # com "itens" dentro, um nível a mais do que {"itens":[...]}.
    saida = [{"itens": [{"property_id": "SP1001"}, {"property_id": "SP1002"}]}]
    itens = _itens_da_saida(saida)
    assert [i["property_id"] for i in itens] == ["SP1001", "SP1002"]


def test_itens_da_saida_aceita_lista_pura_de_imoveis():
    from evals.checagens import _itens_da_saida
    saida = [{"property_id": "SP1001"}, {"property_id": "SP1002"}]
    itens = _itens_da_saida(saida)
    assert len(itens) == 2
