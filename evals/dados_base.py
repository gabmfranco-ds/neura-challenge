"""Leitura só-de-código da base `dados/imoveis.json`, para as checagens que
conferem a saída do modelo contra a verdade dos dados (nunca nota de LLM).

Adaptado de `nucleo/dados.py` e `nucleo/verificacao.py` (repo `neura-challenge`,
branch `v1`, lido em 19/09/2026). Cópia reduzida: só o necessário para as
checagens `ids_existem_na_base` e `respeita_filtros`. Não importa o pacote
`nucleo` porque o worktree `evals` nasceu de `main` (esqueleto, sem código
ainda) -- ver `config.pasta_dados()` para de onde os dados são lidos.
"""
from __future__ import annotations

import functools
import json
import re
import unicodedata

from evals import config


@functools.lru_cache(maxsize=1)
def imoveis() -> list[dict]:
    caminho = config.pasta_dados() / "imoveis.json"
    if not caminho.exists():
        return []
    return json.loads(caminho.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _por_id() -> dict[str, dict]:
    return {im["property_id"]: im for im in imoveis()}


def imovel(property_id: str) -> dict | None:
    return _por_id().get(property_id)


def documento(property_id: str) -> str | None:
    caminho = config.pasta_dados() / "documentos" / f"{property_id}.txt"
    if not caminho.exists():
        return None
    return caminho.read_text(encoding="utf-8")


def limpar_cache() -> None:
    imoveis.cache_clear()
    _por_id.cache_clear()


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn").lower().strip()


def bate_com_filtros(im: dict, pedido: dict) -> list[str]:
    """Devolve a lista de motivos pelos quais `im` NÃO atende ao `pedido`.
    Lista vazia = atende. Espelha `nucleo.verificacao.conferir_item` (só a
    parte de filtros, sem checar números afirmados nem documentação)."""
    motivos: list[str] = []
    if pedido.get("tipo") and im.get("tipo") != pedido["tipo"]:
        motivos.append(f"tipo {im.get('tipo')} != pedido {pedido['tipo']}")
    if pedido.get("preco_max") and im.get("preco", 0) > pedido["preco_max"]:
        motivos.append(f"preco {im.get('preco')} > preco_max {pedido['preco_max']}")
    if pedido.get("quartos_min") and im.get("quartos", 0) < pedido["quartos_min"]:
        motivos.append(f"quartos {im.get('quartos')} < quartos_min {pedido['quartos_min']}")
    if pedido.get("vagas_min") and im.get("vagas", 0) < pedido["vagas_min"]:
        motivos.append(f"vagas {im.get('vagas')} < vagas_min {pedido['vagas_min']}")
    if pedido.get("area_min") and im.get("area", 0) < pedido["area_min"]:
        motivos.append(f"area {im.get('area')} < area_min {pedido['area_min']}")
    bairros = [b.lower() for b in (pedido.get("bairros") or [])]
    if bairros and (im.get("bairro") or "").lower() not in bairros:
        motivos.append(f"bairro {im.get('bairro')} fora de {bairros}")
    if pedido.get("financiamento") and not im.get("aceita_financiamento"):
        motivos.append("nao aceita financiamento e o pedido exige")
    return motivos


_RE_SECAO = re.compile(r"^===\s*(.+?)\s*===\s*$", re.MULTILINE)
_SECOES = {
    "MATRICULA": "matricula",
    "CERTIDAO NEGATIVA DE DEBITOS MUNICIPAIS (IPTU)": "certidao_iptu",
    "CERTIDAO DE DISTRIBUICAO CIVEL E FISCAL": "certidao_distribuicao",
    "DECLARACAO DE QUITACAO DE CONDOMINIO": "condominio",
}
_ONUS = ("HIPOTECA", "PENHORA", "USUFRUTO", "INDISPONIBILIDADE", "ARRESTO",
         "ALIENACAO FIDUCIARIA", "ACAO REIPERSECUTORIA")
_RE_VALIDADE = re.compile(r"validade\s+at[ée]\s*:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_RE_RESULTADO = re.compile(r"resultado\s*:\s*([^.\n]+)", re.IGNORECASE)
_RE_SITUACAO = re.compile(r"situa[çc][ãa]o\s*:\s*([A-Za-zÀ-ÿ]+)", re.IGNORECASE)


def status_documentacao_real(property_id: str) -> str:
    """Versão reduzida de `nucleo.verificacao.analisar_documentos`: só o
    status final (`basic_verified` | `pendencias` | `sem_documentos`), sem as
    pendências detalhadas -- é só o que as checagens de eval precisam."""
    texto = documento(property_id)
    if not texto or not texto.strip():
        return "sem_documentos"
    secoes: dict[str, str] = {}
    marcas = list(_RE_SECAO.finditer(texto))
    for i, marca in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        titulo = _sem_acento(marca.group(1)).upper().strip()
        chave = _SECOES.get(titulo)
        if chave:
            secoes[chave] = texto[marca.end():fim].strip()

    pendencia = False
    matricula = secoes.get("matricula", "")
    for linha in matricula.splitlines():
        linha_limpa = _sem_acento(linha).upper()
        if not (linha_limpa.startswith("AV-") or linha_limpa.startswith("R-")):
            continue
        if any(p in linha_limpa for p in _ONUS):
            situacao = _RE_SITUACAO.search(linha)
            estado = _sem_acento(situacao.group(1)).upper() if situacao else "ATIVA"
            if estado.startswith("ATIV"):
                pendencia = True

    import datetime as dt
    hoje = dt.date.today()
    for chave in ("matricula", "certidao_iptu", "certidao_distribuicao", "condominio"):
        trecho = secoes.get(chave)
        if not trecho:
            pendencia = True
            continue
        validade = _RE_VALIDADE.search(trecho)
        if not validade:
            pendencia = True
            continue
        try:
            data_validade = dt.datetime.strptime(validade.group(1), "%d/%m/%Y").date()
        except ValueError:
            pendencia = True
            continue
        if data_validade < hoje:
            pendencia = True

    for chave in ("certidao_iptu", "certidao_distribuicao"):
        trecho = secoes.get(chave)
        if not trecho:
            continue
        resultado = _RE_RESULTADO.search(trecho)
        texto_resultado = _sem_acento(resultado.group(1)).upper() if resultado else ""
        if "NADA CONSTA" not in texto_resultado:
            pendencia = True

    trecho = secoes.get("condominio")
    if trecho:
        situacao = _RE_SITUACAO.search(trecho)
        estado = _sem_acento(situacao.group(1)).upper() if situacao else ""
        if not estado.startswith("ADIMPLENTE"):
            pendencia = True

    return "pendencias" if pendencia else "basic_verified"
