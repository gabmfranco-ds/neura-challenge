"""Verificação por conta de CÓDIGO. Nenhuma nota de LLM entra aqui.

Toda entrega de agente contratado passa por uma função deste arquivo antes de
virar pagamento. Custa zero token e é o que sustenta o pagamento proporcional:
`pago = preço x itens provados / itens pedidos`.

O que é conferido:

- o imóvel devolvido EXISTE na base e os números batem com os da base;
- ele atende aos filtros do pedido do comprador;
- a disponibilidade afirmada bate com a da base;
- o status de documentação afirmado bate com o que o código lê dos documentos;
- o preço afirmado é comparado com a mediana do bairro na base;
- o preço acordado na negociação cabe no mandato do comprador;
- todas as condições precedentes obrigatórias estão marcadas antes de liberar
  o pagamento.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

from . import dados

SECOES = {
    "MATRICULA": "matricula",
    "CERTIDAO NEGATIVA DE DEBITOS MUNICIPAIS (IPTU)": "certidao_iptu",
    "CERTIDAO DE DISTRIBUICAO CIVEL E FISCAL": "certidao_distribuicao",
    "DECLARACAO DE QUITACAO DE CONDOMINIO": "condominio",
}
ONUS = ("HIPOTECA", "PENHORA", "USUFRUTO", "INDISPONIBILIDADE", "ARRESTO",
        "ALIENACAO FIDUCIARIA", "ACAO REIPERSECUTORIA")

_RE_SECAO = re.compile(r"^===\s*(.+?)\s*===\s*$", re.MULTILINE)
_RE_VALIDADE = re.compile(r"validade\s+at[ée]\s*:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_RE_EMISSAO = re.compile(r"emitida\s+em\s*:\s*(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_RE_SITUACAO = re.compile(r"situa[çc][ãa]o\s*:\s*([A-Za-zÀ-ÿ]+)", re.IGNORECASE)
_RE_RESULTADO = re.compile(r"resultado\s*:\s*([^.\n]+)", re.IGNORECASE)

_NOMES = {
    "matricula": "matrícula",
    "certidao_iptu": "certidão de IPTU",
    "certidao_distribuicao": "certidão de distribuição",
    "condominio": "declaração de condomínio",
}

STATUS_OK = "basic_verified"
STATUS_PENDENCIA = "pendencias"
STATUS_SEM_DOCUMENTOS = "sem_documentos"


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn").upper()


def _data(texto: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(texto, "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None


def separar_secoes(texto: str) -> dict[str, str]:
    """Quebra o arquivo de documentos nas quatro seções conhecidas."""
    saida: dict[str, str] = {}
    marcas = list(_RE_SECAO.finditer(texto or ""))
    for i, marca in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        titulo = _sem_acento(marca.group(1)).strip()
        chave = SECOES.get(titulo)
        if chave:
            saida[chave] = texto[marca.end():fim].strip()
    return saida


def analisar_documentos(texto: str | None, hoje: dt.date | None = None) -> dict:
    """Lê o texto dos documentos e devolve o status e as pendências.

    Regras, todas legíveis no próprio documento:
    - matrícula com averbação de ônus em `Situação: ATIVA` é pendência;
    - certidão com `Validade até` anterior a hoje é pendência;
    - certidão de IPTU que não diga `NADA CONSTA` é pendência;
    - condomínio que não esteja `ADIMPLENTE` é pendência.
    """
    hoje = hoje or dt.date.today()
    if not texto or not texto.strip():
        return {"status": STATUS_SEM_DOCUMENTOS, "pendencias": ["não há documentos na base"],
                "pendencias_por_fonte": {}, "secoes": [], "achados": {}}

    secoes = separar_secoes(texto)
    achados: dict[str, dict] = {}
    # Cada pendência sai com a FONTE (qual documento) junto, porque o Transaction
    # Agent precisa saber qual condição precedente cada uma derruba.
    achadas: list[tuple[str, str]] = []

    def anotar(fonte: str, descricao: str) -> None:
        achadas.append((fonte, descricao))

    for chave in SECOES.values():
        if chave not in secoes:
            anotar(chave, f"documento ausente: {chave}")

    # 1. matrícula: ônus ativo
    matricula = secoes.get("matricula", "")
    onus_ativos = []
    for linha in matricula.splitlines():
        linha_limpa = _sem_acento(linha)
        if not (linha_limpa.startswith("AV-") or linha_limpa.startswith("R-")):
            continue
        if not any(palavra in linha_limpa for palavra in ONUS):
            continue
        situacao = _RE_SITUACAO.search(linha)
        estado = _sem_acento(situacao.group(1)) if situacao else "ATIVA"
        if estado.startswith("ATIV"):
            onus_ativos.append(linha.strip()[:140])
    achados["matricula"] = {"onus_ativos": onus_ativos, "presente": bool(matricula)}
    if onus_ativos:
        anotar("matricula", f"ônus ativo na matrícula: {onus_ativos[0]}")

    # 2. validade das certidões e da matrícula
    for chave in ("matricula", "certidao_iptu", "certidao_distribuicao", "condominio"):
        trecho = secoes.get(chave)
        if not trecho:
            continue
        validade = _RE_VALIDADE.search(trecho)
        emissao = _RE_EMISSAO.search(trecho)
        data_validade = _data(validade.group(1)) if validade else None
        achados.setdefault(chave, {})
        achados[chave]["validade"] = validade.group(1) if validade else None
        achados[chave]["emissao"] = emissao.group(1) if emissao else None
        if data_validade is None:
            anotar(chave, f"não achei data de validade em {chave}")
        elif data_validade < hoje:
            anotar(chave, f"{_NOMES[chave]} vencida em {validade.group(1)} "
                          f"(hoje é {hoje.strftime('%d/%m/%Y')})")
            achados[chave]["vencida"] = True

    # 3. resultado das certidões
    for chave in ("certidao_iptu", "certidao_distribuicao"):
        trecho = secoes.get(chave)
        if not trecho:
            continue
        resultado = _RE_RESULTADO.search(trecho)
        texto_resultado = _sem_acento(resultado.group(1)) if resultado else ""
        achados.setdefault(chave, {})["resultado"] = texto_resultado.strip()
        if "NADA CONSTA" not in texto_resultado:
            anotar(chave, f"{_NOMES[chave]} não diz NADA CONSTA: {texto_resultado.strip()[:80]}")

    # 4. condomínio adimplente
    trecho = secoes.get("condominio")
    if trecho:
        situacao = _RE_SITUACAO.search(trecho)
        estado = _sem_acento(situacao.group(1)) if situacao else ""
        achados.setdefault("condominio", {})["situacao"] = estado
        if not estado.startswith("ADIMPLENTE"):
            anotar("condominio", f"condomínio não está adimplente: {estado or 'sem situação'}")

    por_fonte: dict[str, list[str]] = {}
    for fonte, descricao in achadas:
        por_fonte.setdefault(fonte, []).append(descricao)

    return {
        "status": STATUS_OK if not achadas else STATUS_PENDENCIA,
        "pendencias": [descricao for _, descricao in achadas],
        "pendencias_por_fonte": por_fonte,
        "secoes": list(secoes),
        "achados": achados,
    }


def status_documentacao(property_id: str, hoje: dt.date | None = None) -> dict:
    return analisar_documentos(dados.documento(property_id), hoje)


# ------------------------------------------------------- entrega de busca

CAMPOS_NUMERICOS = ("preco", "area", "quartos", "vagas")


def conferir_item(item: dict, pedido: dict, hoje: dt.date | None = None) -> dict:
    """Confere UM imóvel devolvido por um Property Agent contra a base."""
    motivos: list[str] = []
    property_id = str(item.get("property_id") or "").strip()
    base = dados.imovel(property_id)
    if base is None:
        return {"property_id": property_id or "(sem id)", "aprovado": False,
                "motivos": ["imóvel não existe na base"], "conferido": {}}

    # números afirmados x base
    for campo in CAMPOS_NUMERICOS:
        if item.get(campo) is None:
            continue
        try:
            afirmado = float(item[campo])
        except (TypeError, ValueError):
            motivos.append(f"{campo} veio em formato inválido: {item[campo]!r}")
            continue
        if abs(afirmado - float(base[campo])) > 0.01:
            motivos.append(f"{campo} afirmado ({afirmado:.0f}) não bate com a base ({base[campo]})")

    # filtros do pedido
    if pedido.get("preco_max") and base["preco"] > pedido["preco_max"]:
        motivos.append(f"preço {base['preco']} passa do teto pedido {pedido['preco_max']}")
    if pedido.get("quartos_min") and base["quartos"] < pedido["quartos_min"]:
        motivos.append(f"{base['quartos']} quartos, o pedido pede pelo menos {pedido['quartos_min']}")
    if pedido.get("vagas_min") and base["vagas"] < pedido["vagas_min"]:
        motivos.append(f"{base['vagas']} vagas, o pedido pede pelo menos {pedido['vagas_min']}")
    if pedido.get("area_min") and base["area"] < pedido["area_min"]:
        motivos.append(f"{base['area']} m2, o pedido pede pelo menos {pedido['area_min']} m2")
    bairros = [b.lower() for b in (pedido.get("bairros") or [])]
    if bairros and base["bairro"].lower() not in bairros:
        motivos.append(f"bairro {base['bairro']} está fora dos bairros pedidos")
    if pedido.get("tipo") and base["tipo"] != pedido["tipo"]:
        motivos.append(f"tipo {base['tipo']} não é o tipo pedido ({pedido['tipo']})")
    if pedido.get("financiamento") and not base.get("aceita_financiamento"):
        motivos.append("imóvel não aceita financiamento e o pedido exige")

    # disponibilidade afirmada x base
    disponibilidade_real = base.get("disponibilidade")
    afirmada = (item.get("disponibilidade") or "").strip() or None
    if disponibilidade_real != "available":
        motivos.append(
            f"imóvel está {disponibilidade_real} na base"
            + (f" ({base['motivo_indisponibilidade']})" if base.get("motivo_indisponibilidade") else "")
            + (f", mas a entrega afirmou {afirmada}" if afirmada else ""))
    elif afirmada and afirmada != disponibilidade_real:
        motivos.append(f"disponibilidade afirmada ({afirmada}) não bate com a base ({disponibilidade_real})")

    # documentação afirmada x documentos
    analise = status_documentacao(property_id, hoje)
    afirmado_doc = (item.get("documentacao_status") or "").strip() or None
    if afirmado_doc and afirmado_doc != analise["status"]:
        motivos.append(
            f"documentação afirmada como {afirmado_doc}, mas os documentos dizem "
            f"{analise['status']}" + (f": {analise['pendencias'][0]}" if analise["pendencias"] else ""))
    elif not afirmado_doc:
        motivos.append("a entrega não disse nada sobre a documentação")
    elif analise["status"] != STATUS_OK:
        motivos.append(f"documentação com pendência: {analise['pendencias'][0]}")

    # preço contra a mediana do bairro
    mediana = dados.mediana_bairro(base["bairro"])
    ppm2 = base["preco"] / base["area"] if base["area"] else 0
    comparacao = None
    if mediana:
        variacao = (ppm2 - mediana) / mediana
        comparacao = {"mediana_bairro_m2": mediana, "preco_m2": round(ppm2, 2),
                      "variacao": round(variacao, 4)}

    return {
        "property_id": property_id,
        "aprovado": not motivos,
        "motivos": motivos,
        "conferido": {
            "disponibilidade": disponibilidade_real,
            "documentacao_status": analise["status"],
            "pendencias_documentais": analise["pendencias"],
            "preco": base["preco"],
            "comparacao_preco": comparacao,
        },
    }


def conferir_busca(itens: list[dict], pedido: dict, hoje: dt.date | None = None) -> dict:
    conferidos = [conferir_item(item, pedido, hoje) for item in (itens or [])]
    aprovados = [c for c in conferidos if c["aprovado"]]
    reprovados = [c for c in conferidos if not c["aprovado"]]
    return {
        "itens": conferidos,
        "pedidos": len(conferidos),
        "provados": len(aprovados),
        "aprovados": [c["property_id"] for c in aprovados],
        "reprovados": [{"property_id": c["property_id"], "motivos": c["motivos"]}
                       for c in reprovados],
    }


# ------------------------------------------------------------- mandato

def conferir_mandato(preco_acordado: float | None, mandato: dict) -> dict:
    """O acordo cabe no mandato que o comprador deu? Conta de código."""
    motivos: list[str] = []
    teto = mandato.get("teto_preco")
    if preco_acordado is None:
        motivos.append("não há preço acordado")
    elif teto is not None and preco_acordado > teto:
        motivos.append(f"preço acordado R$ {preco_acordado:,.0f} passa do teto autorizado "
                       f"R$ {teto:,.0f}".replace(",", "."))
    prazo = mandato.get("prazo_dias")
    prazo_acordado = mandato.get("prazo_acordado_dias")
    if prazo and prazo_acordado and prazo_acordado > prazo:
        motivos.append(f"prazo acordado ({prazo_acordado} dias) passa do prazo do mandato ({prazo})")
    return {"aprovado": not motivos, "motivos": motivos,
            "preco_acordado": preco_acordado, "teto": teto}


# --------------------------------------------------- condições precedentes

def conferir_condicoes(condicoes: list[dict], ate_fase: str | None = None) -> dict:
    """Nenhuma liberação de pagamento sem TODAS as obrigatórias marcadas.

    `ate_fase` limita a cobrança às condições que já deveriam estar prontas
    naquele ponto do trilho: cobrar o registro na matrícula antes de liberar o
    pagamento travaria a compra para sempre, porque o registro vem depois.
    """
    from . import estados
    if ate_fase:
        limite = estados.TRILHO.index(ate_fase) if ate_fase in estados.TRILHO else len(estados.TRILHO)
        condicoes = [c for c in condicoes
                     if c.get("fase") not in estados.TRILHO
                     or estados.TRILHO.index(c["fase"]) <= limite]
    obrigatorias = [c for c in condicoes if c.get("obrigatoria")]
    pendentes = [c for c in obrigatorias if c.get("status") != "atendida"]
    return {
        "aprovado": not pendentes,
        "total": len(condicoes),
        "obrigatorias": len(obrigatorias),
        "atendidas": len([c for c in condicoes if c.get("status") == "atendida"]),
        "pendentes": [{"id": c.get("id"), "nome": c.get("nome"),
                       "motivo": c.get("motivo") or "não marcada"} for c in pendentes],
    }


# ----------------------------------------------------- regras da negociação

def _numero_no_texto(texto: str, numero: int | None) -> bool:
    """O número aparece na mensagem, em qualquer formatação usual?

    Um agente que escreve "meu teto é R$ 1.880.000" entrega a própria carta.
    Procuramos o número cru, com ponto, com vírgula e em milhares.
    """
    if not numero or not texto:
        return False
    limpo = re.sub(r"[.\s]", "", texto)
    formas = {str(numero), f"{numero:,}".replace(",", "."), f"{numero:,}"}
    if numero % 1000 == 0:
        formas.add(str(numero // 1000))
    return any(re.sub(r"[.\s]", "", f) in limpo for f in formas)


def conferir_jogada_comprador(jogada: dict, *, rodada: int, oferta_min: int | None,
                              teto: int | None, maior_oferta_anterior: int | None) -> dict:
    """Regras do lado do comprador, conferidas por código.

    1. a primeira oferta é EXATAMENTE a oferta mínima autorizada;
    2. oferta nova nunca é menor que a anterior;
    3. nenhuma oferta passa do teto;
    4. a mensagem não pode conter o teto (é a carta na manga do comprador).
    """
    motivos: list[str] = []
    acao = (jogada.get("acao") or "").strip().lower()
    valor = jogada.get("valor")
    if acao == "oferta":
        if valor is None:
            motivos.append("jogada de oferta sem valor")
        else:
            if rodada == 1 and oferta_min is not None and valor != oferta_min:
                motivos.append(
                    f"a primeira oferta tem que ser exatamente a mínima autorizada "
                    f"({oferta_min}), e veio {valor}")
            if maior_oferta_anterior and valor < maior_oferta_anterior:
                motivos.append(f"oferta {valor} é menor que a anterior {maior_oferta_anterior}")
            if teto is not None and valor > teto:
                motivos.append(f"oferta {valor} passa do teto do mandato {teto}")
    if acao == "aceitar" and teto is not None and valor is not None and valor > teto:
        motivos.append(f"aceitou {valor}, acima do teto do mandato {teto}")
    if _numero_no_texto(jogada.get("mensagem") or "", teto):
        motivos.append("a mensagem revela o teto do comprador ao vendedor")
    return {"valida": not motivos, "motivos": motivos}


def conferir_jogada_vendedor(jogada: dict, *, piso: int | None, preco_pedido: int | None,
                             menor_contraproposta_anterior: int | None) -> dict:
    """Regras do lado do vendedor.

    1. contraproposta nunca sobe (ele cede aos poucos, não encarece);
    2. nada abaixo do piso do proprietário;
    3. nada acima do preço pedido;
    4. a mensagem não pode conter o piso.
    """
    motivos: list[str] = []
    acao = (jogada.get("acao") or "").strip().lower()
    valor = jogada.get("valor")
    if acao == "contraproposta":
        if valor is None:
            motivos.append("contraproposta sem valor")
        else:
            if menor_contraproposta_anterior and valor > menor_contraproposta_anterior:
                motivos.append(f"contraproposta {valor} é maior que a anterior "
                               f"{menor_contraproposta_anterior}")
            if piso is not None and valor < piso:
                motivos.append(f"contraproposta {valor} está abaixo do piso {piso}")
            if preco_pedido is not None and valor > preco_pedido:
                motivos.append(f"contraproposta {valor} passa do preço pedido {preco_pedido}")
    if acao == "aceita" and piso is not None and valor is not None and valor < piso:
        motivos.append(f"aceitou {valor}, abaixo do piso do proprietário {piso}")
    if _numero_no_texto(jogada.get("mensagem") or "", piso):
        motivos.append("a mensagem revela o piso do vendedor ao comprador")
    return {"valida": not motivos, "motivos": motivos}


def conferir_acordo(preco_final: int | None, *, oferta_min: int | None, teto: int | None,
                    piso: int | None, preco_pedido: int | None) -> dict:
    """Acordo só vale se o preço final couber nas DUAS faixas."""
    motivos: list[str] = []
    if preco_final is None:
        motivos.append("não há preço acordado")
        return {"aprovado": False, "motivos": motivos}
    if teto is not None and preco_final > teto:
        motivos.append(f"preço final {preco_final} passa do teto do comprador {teto}")
    if oferta_min is not None and preco_final < oferta_min:
        motivos.append(f"preço final {preco_final} está abaixo da oferta mínima autorizada "
                       f"{oferta_min}, o que não faz sentido")
    if piso is not None and preco_final < piso:
        motivos.append(f"preço final {preco_final} está abaixo do piso do vendedor {piso}")
    if preco_pedido is not None and preco_final > preco_pedido:
        motivos.append(f"preço final {preco_final} passa do preço pedido {preco_pedido}")
    return {"aprovado": not motivos, "motivos": motivos, "preco_final": preco_final}


def jogadas_validas(negociacao: list[dict]) -> list[dict]:
    """O histórico que cada lado pode ler.

    Jogada descartada pela regra fica na lista para a tela e para o registro,
    mas NÃO pode ser mostrada ao adversário: um número que a regra rejeitou,
    lido pelo outro lado, vale tanto quanto uma jogada aceita. Medido: um
    vendedor com piso de R$ 1,97 milhão "fechou" em R$ 1,78 milhão porque duas
    contrapropostas descartadas continuaram visíveis para o comprador.
    """
    return [j for j in (negociacao or []) if not j.get("violacao")]


def motivo_da_negativa(historico: list[dict], *, nome_comprador: str,
                       max_rodadas: int) -> str:
    """Explica em português por que não houve acordo. É isto que vai na tela."""
    ofertas = [h.get("valor") for h in historico
               if h.get("de") == nome_comprador and h.get("valor")]
    contras = [h.get("valor") for h in historico
               if h.get("de") != nome_comprador and h.get("valor")]
    ultima_oferta = ofertas[-1] if ofertas else None
    ultima_contra = contras[-1] if contras else None
    if ultima_oferta is None or ultima_contra is None:
        return (f"acabaram as {max_rodadas} rodadas sem os dois lados chegarem a um número "
                f"comparável")
    distancia = ultima_contra - ultima_oferta
    return (f"acabaram as {max_rodadas} rodadas sem acordo: a última oferta do comprador foi "
            f"R$ {ultima_oferta:,.0f} e a última contraproposta do vendedor foi "
            f"R$ {ultima_contra:,.0f}, uma distância de R$ {distancia:,.0f}"
            .replace(",", "."))


def pagamento_proporcional(preco_usd: float, pedidos: int, provados: int) -> tuple[float, float]:
    """`pago = preço x provados / pedidos`. O resto fica retido e visível."""
    if pedidos <= 0:
        return 0.0, round(preco_usd, 6)
    pago = round(preco_usd * provados / pedidos, 6)
    return pago, round(preco_usd - pago, 6)
