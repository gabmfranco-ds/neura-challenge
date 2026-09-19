"""Testes do executor com alvo DUBLÊ: nenhuma chamada de rede, nem à
NeuraLake nem ao servidor do projeto. `monkeypatch` troca as funções que
fariam I/O por versões falsas e determinísticas."""
import asyncio
import json

import pytest

from evals import alvos, checagens, db, loader, neuralake_client, rodar


def _rodar(coro):
    return asyncio.run(coro)


@pytest.fixture
def caso_prompt(tmp_path):
    pasta = tmp_path / "casos"
    pasta.mkdir()
    (pasta / "buyer_extracao.jsonl").write_text(
        json.dumps({
            "nome": "caso_falso", "alvo": "prompt",
            "entrada": {"frase": "apartamento em Pinheiros ate 1 milhao"},
            "checagens": [{"tipo": "json_valido"},
                         {"tipo": "campos_obrigatorios", "campos": ["pedido.tipo"]}],
        }, ensure_ascii=False) + "\n", encoding="utf-8")
    caminho_db = tmp_path / "t.db"
    loader.sincronizar_tudo(pasta, caminho_db=caminho_db)
    with db.abrir(caminho_db) as conexao:
        caso = loader.casos_ativos(conexao, "buyer_extracao")[0]
        # sqlite3.Row não sobrevive fora da conexão de forma confiável em todo
        # driver: materializa num dict com as mesmas chaves usadas pelo executor.
        return dict(caso)


def test_tentativa_prompt_com_resposta_boa(monkeypatch, caso_prompt):
    async def chamar_falso(mensagens, *, capacidade, api_key, max_tokens, temperature, timeout=None):
        return neuralake_client.ResultadoBruto(
            ok=True, texto=json.dumps({"pedido": {"tipo": "apartamento"}, "suposicoes": []}),
            modelo_usado="text", custo_usd=0.0001, tokens_entrada=50, tokens_saida=20,
            latencia_ms=123, http_status=200, resposta_bruta={"model": "text"})

    monkeypatch.setattr(neuralake_client, "chamar", chamar_falso)

    resultado = _rodar(rodar._tentativa_prompt(
        caso_prompt, "buyer_extracao", "auto", 1, "chave-falsa", asyncio.Semaphore(1)))
    assert resultado["passou"] is True
    assert resultado["erro_tipo"] is None
    assert resultado["custo_usd"] == 0.0001
    assert resultado["modelo_usado"] == "text"


def test_tentativa_prompt_com_timeout_vira_resultado_nao_excecao(monkeypatch, caso_prompt):
    async def chamar_falso(mensagens, *, capacidade, api_key, max_tokens, temperature, timeout=None):
        return neuralake_client.ResultadoBruto(ok=False, erro_tipo="timeout", latencia_ms=30000)

    monkeypatch.setattr(neuralake_client, "chamar", chamar_falso)

    resultado = _rodar(rodar._tentativa_prompt(
        caso_prompt, "buyer_extracao", "auto", 1, "chave-falsa", asyncio.Semaphore(1)))
    assert resultado["passou"] is False
    assert resultado["erro_tipo"] == "timeout"


def test_tentativa_prompt_corpo_vazio_marca_erro_tipo(monkeypatch, caso_prompt):
    async def chamar_falso(mensagens, *, capacidade, api_key, max_tokens, temperature, timeout=None):
        return neuralake_client.ResultadoBruto(ok=True, texto="   ", modelo_usado="reasoning",
                                               custo_usd=0.001, latencia_ms=500, http_status=200)

    monkeypatch.setattr(neuralake_client, "chamar", chamar_falso)

    resultado = _rodar(rodar._tentativa_prompt(
        caso_prompt, "buyer_extracao", "reasoning", 1, "chave-falsa", asyncio.Semaphore(1)))
    assert resultado["erro_tipo"] == "corpo_vazio"
    assert resultado["passou"] is False


def test_tentativa_http_alvo_fora_do_ar(monkeypatch, caso_prompt):
    async def chamar_http_falso(entrada, base_url=None, timeout=None):
        return {"ok": False, "erro_tipo": "alvo_fora_do_ar", "http_status": None,
               "corpo": {}, "latencia_ms": 5}

    monkeypatch.setattr(alvos, "chamar_http", chamar_http_falso)

    resultado = _rodar(rodar._tentativa_http(caso_prompt, "auto", asyncio.Semaphore(1)))
    assert resultado["erro_tipo"] == "alvo_fora_do_ar"
    assert resultado["passou"] is False


def test_tentativa_http_com_sucesso_roda_checagens(monkeypatch, caso_prompt):
    async def chamar_http_falso(entrada, base_url=None, timeout=None):
        return {"ok": True, "erro_tipo": None, "http_status": 200,
               "corpo": {"saida": {"pedido": {"tipo": "apartamento"}}, "custo_usd": 0.002},
               "latencia_ms": 42}

    monkeypatch.setattr(alvos, "chamar_http", chamar_http_falso)

    resultado = _rodar(rodar._tentativa_http(caso_prompt, "auto", asyncio.Semaphore(1)))
    # o caso de fixture checa "pedido.tipo" na raiz, não em "saida.pedido.tipo": por
    # construção deve falhar essa checagem específica, mas sem lançar exceção.
    assert resultado["erro_tipo"] is None
    assert isinstance(resultado["falhas"], list)
