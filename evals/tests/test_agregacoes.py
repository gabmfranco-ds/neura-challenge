"""Testes das visões SQL (esquema.sql) com dados inseridos à mão. Sem rede."""
import pytest

from evals import db


@pytest.fixture
def conexao(tmp_path):
    caminho = tmp_path / "agregacoes.db"
    with db.abrir(caminho) as c:
        yield c


def _popular(conexao):
    suite_id = db.obter_ou_criar_suite(conexao, "suite_x")
    caso_id = conexao.execute(
        "INSERT INTO casos (suite_id, nome, entrada_json, checagens_json) VALUES (?,?,?,?)",
        (suite_id, "caso_a", "{}", "[]")).lastrowid
    caso_id_b = conexao.execute(
        "INSERT INTO casos (suite_id, nome, entrada_json, checagens_json) VALUES (?,?,?,?)",
        (suite_id, "caso_b", "{}", "[]")).lastrowid
    execucao_id = conexao.execute(
        "INSERT INTO execucoes (iniciada_em, rotulo, alvo, capacidade) VALUES (?,?,?,?)",
        ("2026-09-19T00:00:00Z", "rotulo1", "prompt", "auto")).lastrowid

    linhas = [
        # caso_a: passa 2x, falha 1x -> instável
        (execucao_id, caso_id, 1, 1, 1.0, 100, 0.001),
        (execucao_id, caso_id, 2, 1, 1.0, 200, 0.002),
        (execucao_id, caso_id, 3, 0, 0.0, 300, 0.001),
        # caso_b: sempre passa -> não é instável
        (execucao_id, caso_id_b, 1, 1, 1.0, 150, 0.003),
    ]
    for (exec_id, cid, rep, passou, nota, lat, custo) in linhas:
        conexao.execute(
            "INSERT INTO resultados (execucao_id, caso_id, repeticao, passou, nota, "
            "falhas_json, latencia_ms, custo_usd) VALUES (?,?,?,?,?,?,?,?)",
            (exec_id, cid, rep, passou, nota, "[]", lat, custo))
    conexao.commit()
    return execucao_id


def test_resumo_por_suite_capacidade_rotulo(conexao):
    _popular(conexao)
    linha = conexao.execute(
        "SELECT * FROM v_resumo_por_suite_capacidade_rotulo WHERE suite='suite_x'").fetchone()
    assert linha["total_execucoes_de_caso"] == 4
    assert linha["total_passou"] == 3
    assert abs(linha["taxa_acerto"] - 0.75) < 1e-6


def test_casos_instaveis(conexao):
    _popular(conexao)
    instaveis = conexao.execute("SELECT * FROM v_casos_instaveis").fetchall()
    nomes = {i["caso"] for i in instaveis}
    assert "caso_a" in nomes
    assert "caso_b" not in nomes
    linha_a = next(i for i in instaveis if i["caso"] == "caso_a")
    assert linha_a["vezes_passou"] == 2
    assert linha_a["vezes_falhou"] == 1
