"""Testes do carregador idempotente. Usa banco e pasta de casos temporários,
sem tocar em evals/evals.db nem em evals/casos/."""
import json

import pytest

from evals import db, loader


@pytest.fixture
def pasta_casos(tmp_path):
    pasta = tmp_path / "casos"
    pasta.mkdir()
    return pasta


@pytest.fixture
def caminho_db(tmp_path):
    return tmp_path / "teste.db"


def _escrever(pasta, nome_arquivo, casos):
    caminho = pasta / nome_arquivo
    with caminho.open("w", encoding="utf-8") as f:
        for c in casos:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def test_sincronizar_cria_suite_e_casos(pasta_casos, caminho_db):
    _escrever(pasta_casos, "minha_suite.jsonl", [
        {"nome": "caso_1", "alvo": "prompt", "entrada": {"frase": "oi"}, "checagens": []},
        {"nome": "caso_2", "alvo": "prompt", "entrada": {"frase": "tchau"}, "checagens": []},
    ])
    resumos = loader.sincronizar_tudo(pasta_casos, caminho_db=caminho_db)
    assert resumos[0]["suite"] == "minha_suite"
    assert resumos[0]["novos"] == 2
    assert resumos[0]["atualizados"] == 0

    with db.abrir(caminho_db) as conexao:
        ativos = loader.casos_ativos(conexao, "minha_suite")
        assert len(ativos) == 2
        assert {c["nome"] for c in ativos} == {"caso_1", "caso_2"}


def test_sincronizar_de_novo_e_idempotente(pasta_casos, caminho_db):
    _escrever(pasta_casos, "s.jsonl", [
        {"nome": "c1", "alvo": "prompt", "entrada": {"x": 1}, "checagens": []},
    ])
    loader.sincronizar_tudo(pasta_casos, caminho_db=caminho_db)
    resumo2 = loader.sincronizar_tudo(pasta_casos, caminho_db=caminho_db)[0]
    assert resumo2["novos"] == 0
    assert resumo2["atualizados"] == 1  # já existia, foi atualizado no lugar

    with db.abrir(caminho_db) as conexao:
        total = conexao.execute("SELECT COUNT(*) AS n FROM casos").fetchone()["n"]
        assert total == 1  # não duplicou


def test_caso_removido_do_arquivo_fica_inativo(pasta_casos, caminho_db):
    _escrever(pasta_casos, "s.jsonl", [
        {"nome": "c1", "alvo": "prompt", "entrada": {}, "checagens": []},
        {"nome": "c2", "alvo": "prompt", "entrada": {}, "checagens": []},
    ])
    loader.sincronizar_tudo(pasta_casos, caminho_db=caminho_db)
    _escrever(pasta_casos, "s.jsonl", [
        {"nome": "c1", "alvo": "prompt", "entrada": {}, "checagens": []},
    ])
    loader.sincronizar_tudo(pasta_casos, caminho_db=caminho_db)

    with db.abrir(caminho_db) as conexao:
        ativos = {c["nome"] for c in loader.casos_ativos(conexao, "s")}
        assert ativos == {"c1"}
        inativo = conexao.execute(
            "SELECT ativo FROM casos c JOIN suites s ON s.id=c.suite_id "
            "WHERE s.nome='s' AND c.nome='c2'").fetchone()
        assert inativo["ativo"] == 0


def test_caso_sem_nome_da_erro_claro(pasta_casos, caminho_db):
    _escrever(pasta_casos, "s.jsonl", [{"entrada": {}}])
    with pytest.raises(ValueError, match="sem 'nome'"):
        loader.sincronizar_tudo(pasta_casos, caminho_db=caminho_db)
