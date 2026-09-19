"""Biblioteca de checagens declarativas. SEMPRE por código, nunca nota de LLM.

Cada checagem é uma função `(ctx) -> (passou: bool, motivo: str)`. `ctx` é um
`Contexto` com o que foi extraído da resposta (`saida`, `texto`), o caso
(`entrada`, `esperado`) e metadados da chamada (`modelo_usado` etc).

`checagens_json` de um caso é uma lista de `{"tipo": "...", ...parametros}`.
`rodar_checagens` aplica todas e devolve (passou_tudo, nota, falhas).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

from evals import dados_base


@dataclass
class Contexto:
    saida: Any                    # objeto JSON extraído da resposta (ou None)
    texto: str                    # texto bruto (com <think> se tiver vazado)
    entrada: dict = field(default_factory=dict)   # caso["entrada"]
    esperado: dict = field(default_factory=dict)  # caso["esperado"]
    modelo_usado: str = ""
    capacidade_pedida: str = ""
    capacidade_usada: str = ""


def _get(obj: Any, caminho: str, ausente=object()):
    """Acessa `a.b.0.c` em dicts/listas aninhados. Devolve `ausente` se faltar."""
    atual = obj
    if not caminho:
        return atual
    for parte in caminho.split("."):
        if isinstance(atual, dict):
            if parte not in atual:
                return ausente
            atual = atual[parte]
        elif isinstance(atual, list):
            if not parte.lstrip("-").isdigit() or not (-len(atual) <= int(parte) < len(atual)):
                return ausente
            atual = atual[int(parte)]
        else:
            return ausente
    return atual


_AUSENTE = object()


def _norm_str(v: Any) -> str:
    if v is None:
        return ""
    texto = str(v)
    texto = "".join(c for c in unicodedata.normalize("NFD", texto)
                     if unicodedata.category(c) != "Mn")
    return texto.strip().lower()


# --------------------------------------------------------------- checagens

def checar_json_valido(ctx: Contexto, **_) -> tuple[bool, str]:
    if ctx.saida is None:
        return False, "não consegui extrair um JSON válido da resposta"
    return True, "JSON válido"


def checar_campos_obrigatorios(ctx: Contexto, campos: list[str], **_) -> tuple[bool, str]:
    faltando = []
    for campo in campos:
        valor = _get(ctx.saida, campo, _AUSENTE)
        if valor is _AUSENTE or valor is None or valor == "":
            faltando.append(campo)
    if faltando:
        return False, f"campos faltando ou vazios: {', '.join(faltando)}"
    return True, "todos os campos obrigatórios presentes"


def checar_igual(ctx: Contexto, campo: str, valor: Any, **_) -> tuple[bool, str]:
    real = _get(ctx.saida, campo, _AUSENTE)
    if real is _AUSENTE:
        return False, f"campo {campo} ausente"
    if isinstance(valor, str) or isinstance(real, str):
        ok = _norm_str(real) == _norm_str(valor)
    else:
        ok = real == valor
    return ok, ("igual" if ok else f"{campo}={real!r}, esperado {valor!r}")


def checar_diferente_de(ctx: Contexto, campo: str, valor: Any = None,
                        campo_referencia: str | None = None, **_) -> tuple[bool, str]:
    real = _get(ctx.saida, campo, _AUSENTE)
    referencia = valor
    if campo_referencia is not None:
        referencia = _get(ctx.entrada, campo_referencia, _AUSENTE)
    if real is _AUSENTE:
        return False, f"campo {campo} ausente"
    ok = _norm_str(real) != _norm_str(referencia)
    return ok, ("diferente, ok" if ok else f"{campo}={real!r} é igual ao valor proibido {referencia!r}")


def checar_contem_todos(ctx: Contexto, campo: str, lista: list[str], **_) -> tuple[bool, str]:
    real = _get(ctx.saida, campo, _AUSENTE)
    if real is _AUSENTE or not isinstance(real, list):
        return False, f"campo {campo} ausente ou não é lista"
    normalizados = {_norm_str(x) for x in real}
    faltando = [item for item in lista if _norm_str(item) not in normalizados]
    if faltando:
        return False, f"faltam em {campo}: {', '.join(faltando)}"
    return True, "todos presentes"


def checar_contem_algum(ctx: Contexto, campo: str, lista: list[str], **_) -> tuple[bool, str]:
    real = _get(ctx.saida, campo, _AUSENTE)
    if real is _AUSENTE:
        return False, f"campo {campo} ausente"
    texto = _norm_str(real if isinstance(real, str) else str(real))
    achou = [item for item in lista if _norm_str(item) in texto]
    if achou:
        return True, f"citou: {', '.join(achou)}"
    return False, f"não citou nenhum de {lista} em {campo!r}={real!r}"


def checar_numero_entre(ctx: Contexto, campo: str, min: float | None = None,
                        max: float | None = None, **_) -> tuple[bool, str]:
    real = _get(ctx.saida, campo, _AUSENTE)
    if real is _AUSENTE or real is None:
        return False, f"campo {campo} ausente"
    try:
        numero = float(real)
    except (TypeError, ValueError):
        return False, f"{campo}={real!r} não é número"
    if min is not None and numero < min:
        return False, f"{campo}={numero} < mínimo {min}"
    if max is not None and numero > max:
        return False, f"{campo}={numero} > máximo {max}"
    return True, f"{campo}={numero} dentro da faixa"


def checar_enum(ctx: Contexto, campo: str, valores: list[str], **_) -> tuple[bool, str]:
    real = _get(ctx.saida, campo, _AUSENTE)
    if real is _AUSENTE:
        return False, f"campo {campo} ausente"
    ok = _norm_str(real) in {_norm_str(v) for v in valores}
    return ok, (f"{campo}={real!r} em {valores}" if ok else f"{campo}={real!r} fora de {valores}")


_RE_THINK = re.compile(r"<think\b", re.IGNORECASE)


def checar_sem_think(ctx: Contexto, **_) -> tuple[bool, str]:
    if _RE_THINK.search(ctx.texto or ""):
        return False, "vazou <think> no conteúdo"
    return True, "sem vazamento de <think>"


def checar_nao_vazio(ctx: Contexto, campo: str | None = None, **_) -> tuple[bool, str]:
    valor = ctx.texto if campo is None else _get(ctx.saida, campo, "")
    if valor is _AUSENTE or valor is None or not str(valor).strip():
        return False, "corpo vazio (possível queima de raciocínio)"
    return True, "não vazio"


def checar_lista_nao_vazia(ctx: Contexto, campo: str, minimo: int = 1, **_) -> tuple[bool, str]:
    real = _get(ctx.saida, campo, _AUSENTE)
    if real is _AUSENTE or not isinstance(real, list):
        return False, f"campo {campo} ausente ou não é lista"
    if len(real) < minimo:
        return False, f"{campo} tem {len(real)} item(ns), mínimo esperado {minimo}"
    return True, f"{campo} tem {len(real)} item(ns)"


def _itens_da_saida(saida: Any, profundidade: int = 0) -> list[dict]:
    """Desembrulha a lista de imóveis de uma resposta de modelo, recursivamente.

    Mesma lógica de `agentes/property/agente.py::extrair_itens` (lida em
    19/09/2026): medido contra a API real, o modelo devolve formatos
    variados e ambos aninhados — `{"itens":[{"itens":[...]}]}`,
    `[{"itens":[...]}]`, uma lista pura de imóveis, um imóvel solto — e
    cobrar formato perfeito do modelo é perder entrega boa por casca."""
    if profundidade > 4 or saida is None:
        return []
    if isinstance(saida, dict):
        if saida.get("property_id"):
            return [saida]
        for chave in ("itens", "imoveis", "resultados", "data"):
            if chave in saida:
                return _itens_da_saida(saida[chave], profundidade + 1)
        return []
    if isinstance(saida, list):
        encontrados: list[dict] = []
        for elemento in saida:
            encontrados.extend(_itens_da_saida(elemento, profundidade + 1))
        return encontrados
    return []


def checar_ids_existem_na_base(ctx: Contexto, campo: str = "itens", **_) -> tuple[bool, str]:
    itens = _itens_da_saida(ctx.saida)
    if not itens:
        return False, "nenhum item para conferir (saída vazia ou mal formada)"
    desconhecidos = [i.get("property_id") for i in itens
                     if dados_base.imovel(str(i.get("property_id"))) is None]
    if desconhecidos:
        return False, f"property_id inexistente na base: {desconhecidos}"
    return True, f"{len(itens)} property_id conferidos, todos existem"


def checar_respeita_filtros(ctx: Contexto, pedido_campo: str = "pedido", **_) -> tuple[bool, str]:
    pedido = ctx.entrada.get(pedido_campo) or ctx.entrada
    itens = _itens_da_saida(ctx.saida)
    if not itens:
        return False, "nenhum item para conferir"
    falhas = []
    for item in itens:
        base = dados_base.imovel(str(item.get("property_id")))
        if base is None:
            falhas.append(f"{item.get('property_id')}: não existe na base")
            continue
        motivos = dados_base.bate_com_filtros(base, pedido)
        if motivos:
            falhas.append(f"{item.get('property_id')}: {'; '.join(motivos)}")
    if falhas:
        return False, " | ".join(falhas)
    return True, f"{len(itens)} imóveis respeitam os filtros do pedido"


def checar_documentacao_bate_com_base(ctx: Contexto, **_) -> tuple[bool, str]:
    itens = _itens_da_saida(ctx.saida)
    if not itens:
        # lista vazia é uma resposta válida quando não havia candidato
        # nenhum (ex.: pedido sem nenhum imóvel na base); outras checagens
        # (ids_existem_na_base, respeita_filtros) cobrem o caso em que a
        # lista deveria ter vindo cheia e veio vazia por engano.
        return True, "sem itens para conferir (lista vazia)"
    falhas = []
    for item in itens:
        pid = str(item.get("property_id"))
        if dados_base.documento(pid) is None:
            continue  # sem documento de exemplo para este imóvel: não dá para conferir
        real = dados_base.status_documentacao_real(pid)
        afirmado = str(item.get("documentacao_status") or "")
        if afirmado and afirmado != real:
            falhas.append(f"{pid}: afirmou {afirmado!r}, documento real diz {real!r}")
    if falhas:
        return False, " | ".join(falhas)
    return True, "status de documentação bate com os documentos (quando havia documento)"


def checar_respeita_piso(ctx: Contexto, campo_valor: str = "valor", campo_acao: str = "acao",
                         piso_entrada: str = "piso", **_) -> tuple[bool, str]:
    piso = ctx.entrada.get(piso_entrada)
    acao = _norm_str(_get(ctx.saida, campo_acao, ""))
    valor = _get(ctx.saida, campo_valor, _AUSENTE)
    if piso is None:
        return False, "caso não declarou piso (entrada.piso)"
    if acao in ("aceita", "aceitar"):
        if valor is _AUSENTE:
            return False, "aceitou sem valor"
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return False, f"valor {valor!r} não é número"
        ok = valor >= piso
        return ok, (f"aceitou {valor} >= piso {piso}" if ok
                    else f"ACEITOU ABAIXO DO PISO: {valor} < {piso}")
    if acao == "contraproposta":
        if valor is _AUSENTE:
            return False, "contrapropôs sem valor"
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return False, f"valor {valor!r} não é número"
        ok = valor >= piso
        return ok, (f"contraproposta {valor} >= piso {piso}" if ok
                    else f"CONTRAPROPOSTA ABAIXO DO PISO: {valor} < {piso}")
    return True, f"ação {acao!r} não tem restrição de piso"


def checar_respeita_teto(ctx: Contexto, campo_valor: str = "valor", campo_acao: str = "acao",
                         teto_entrada: str = "mandato.teto_preco", **_) -> tuple[bool, str]:
    teto = _get(ctx.entrada, teto_entrada, None)
    acao = _norm_str(_get(ctx.saida, campo_acao, ""))
    valor = _get(ctx.saida, campo_valor, _AUSENTE)
    if teto is None:
        return False, "caso não declarou teto (entrada.mandato.teto_preco)"
    if acao in ("oferta", "aceitar"):
        if valor is _AUSENTE:
            return False, f"ação {acao} sem valor"
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return False, f"valor {valor!r} não é número"
        ok = valor <= teto
        return ok, (f"{acao} {valor} <= teto {teto}" if ok
                    else f"PASSOU DO TETO: {acao} {valor} > {teto}")
    return True, f"ação {acao!r} não tem restrição de teto"


def _numero_como_texto(numero: float) -> list[str]:
    """Formas em que um número pode aparecer escrito por um agente em PT-BR:
    inteiro cru, com pontos de milhar, e abreviado em milhões/mil."""
    numero = float(numero)
    inteiro = int(numero)
    formas = {str(inteiro)}
    formas.add(f"{inteiro:,}".replace(",", "."))
    if numero >= 1_000_000:
        mi = numero / 1_000_000
        formas.add(f"{mi:.1f}".replace(".", ",") + " mi")
        formas.add(f"{mi:.2f}".replace(".", ",") + " mi")
        formas.add(f"{mi:.1f}".rstrip("0").rstrip(".") + " mi")
        if mi == int(mi):
            formas.add(f"{int(mi)} mi")
            formas.add(f"{int(mi)} milh")
    if numero >= 1_000:
        formas.add(f"{numero / 1000:.0f} mil")
    return list(formas)


def checar_nao_revela_limite(ctx: Contexto, campo_mensagem: str = "mensagem",
                             limite_entrada: str = "limite", **_) -> tuple[bool, str]:
    """A mensagem para o outro lado não pode conter o número do teto/piso do
    próprio agente, em nenhum formato comum (cru, com ponto de milhar, ou
    abreviado tipo "1,88 mi"). Ver `nucleo/verificacao` novo (regra do dono,
    19/09/2026): o mandato é informação PRÓPRIA, nunca revelada ao outro lado."""
    limite = _get(ctx.entrada, limite_entrada, None)
    mensagem = _get(ctx.saida, campo_mensagem, "")
    if limite is None:
        return False, f"caso não declarou limite ({limite_entrada})"
    if not mensagem:
        return True, "mensagem vazia, nada a revelar"
    texto_norm = _norm_str(mensagem).replace(" ", "")
    for forma in _numero_como_texto(limite):
        forma_norm = _norm_str(forma).replace(" ", "")
        if forma_norm and forma_norm in texto_norm:
            return False, f"mensagem revela o limite {limite} (achado como {forma!r})"
    return True, "mensagem não revela o limite"


def checar_primeira_oferta_igual_min(ctx: Contexto, campo_valor: str = "valor",
                                     oferta_min_entrada: str = "mandato.oferta_min",
                                     historico_entrada: str = "historico", **_) -> tuple[bool, str]:
    """Regra do dono (19/09/2026): a PRIMEIRA oferta do comprador é exatamente
    `oferta_min` (aposta no mínimo). Só se aplica quando o histórico está
    vazio (é de fato a primeira rodada)."""
    historico = _get(ctx.entrada, historico_entrada, []) or []
    if historico:
        return True, "não é a primeira rodada, checagem não se aplica"
    oferta_min = _get(ctx.entrada, oferta_min_entrada, None)
    if oferta_min is None:
        return False, f"caso não declarou {oferta_min_entrada}"
    valor = _get(ctx.saida, campo_valor, _AUSENTE)
    if valor is _AUSENTE:
        return False, "sem valor na saída"
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return False, f"valor {valor!r} não é número"
    ok = abs(valor - float(oferta_min)) < 0.5
    return ok, (f"primeira oferta {valor} == oferta_min {oferta_min}" if ok
               else f"primeira oferta deveria ser oferta_min {oferta_min}, veio {valor}")


def _valores_de(historico: list[dict], de: str, acoes: tuple[str, ...]) -> list[float]:
    saida = []
    for h in historico:
        if _norm_str(h.get("de")) == _norm_str(de) and _norm_str(h.get("acao")) in acoes:
            try:
                saida.append(float(h.get("valor")))
            except (TypeError, ValueError):
                continue
    return saida


def checar_ofertas_nao_decrescentes(ctx: Contexto, campo_valor: str = "valor",
                                    campo_acao: str = "acao", de: str = "comprador",
                                    historico_entrada: str = "historico", **_) -> tuple[bool, str]:
    """As ofertas do comprador ao longo da negociação nunca caem: cada oferta
    nova é >= a maior oferta anterior dele mesmo."""
    historico = _get(ctx.entrada, historico_entrada, []) or []
    anteriores = _valores_de(historico, de, ("oferta", "aceitar"))
    acao = _norm_str(_get(ctx.saida, campo_acao, ""))
    if acao not in ("oferta", "aceitar"):
        return True, f"ação {acao!r} não é oferta, checagem não se aplica"
    valor = _get(ctx.saida, campo_valor, _AUSENTE)
    if valor is _AUSENTE:
        return False, "sem valor na saída"
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return False, f"valor {valor!r} não é número"
    maior_anterior = max(anteriores) if anteriores else None
    if maior_anterior is not None and valor < maior_anterior:
        return False, f"nova oferta {valor} é MENOR que a anterior {maior_anterior}"
    return True, "não decresceu"


def checar_contrapropostas_nao_crescentes(ctx: Contexto, campo_valor: str = "valor",
                                          campo_acao: str = "acao", de: str = "vendedor",
                                          historico_entrada: str = "historico", **_) -> tuple[bool, str]:
    """As contrapropostas do vendedor nunca sobem: ele cede aos poucos a
    partir do preço pedido."""
    historico = _get(ctx.entrada, historico_entrada, []) or []
    anteriores = _valores_de(historico, de, ("contraproposta", "aceita"))
    acao = _norm_str(_get(ctx.saida, campo_acao, ""))
    if acao not in ("contraproposta", "aceita"):
        return True, f"ação {acao!r} não é contraproposta, checagem não se aplica"
    valor = _get(ctx.saida, campo_valor, _AUSENTE)
    if valor is _AUSENTE:
        return False, "sem valor na saída"
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return False, f"valor {valor!r} não é número"
    menor_anterior = min(anteriores) if anteriores else None
    if menor_anterior is not None and valor > menor_anterior:
        return False, f"nova contraproposta {valor} é MAIOR que a anterior {menor_anterior}"
    return True, "não cresceu"


def checar_acordo_dentro_das_duas_faixas(ctx: Contexto, campo_preco: str = "preco_final",
                                         campo_acordo: str = "acordo",
                                         piso_entrada: str = "vendedor.piso",
                                         teto_entrada: str = "comprador.teto_preco", **_) -> tuple[bool, str]:
    acordo = bool(_get(ctx.saida, campo_acordo, False))
    if not acordo:
        return True, "sem acordo, checagem não se aplica"
    preco = _get(ctx.saida, campo_preco, _AUSENTE)
    piso = _get(ctx.entrada, piso_entrada, None)
    teto = _get(ctx.entrada, teto_entrada, None)
    if preco is _AUSENTE or piso is None or teto is None:
        return False, "faltam dados para conferir (preco_final, piso ou teto)"
    try:
        preco = float(preco)
    except (TypeError, ValueError):
        return False, f"preco_final {preco!r} não é número"
    ok = piso <= preco <= teto
    return ok, (f"acordo em {preco}, dentro de [{piso}, {teto}]" if ok
               else f"ACORDO FORA DA ZONA: {preco} fora de [{piso}, {teto}]")


def checar_rejeita_quando_faixas_nao_se_cruzam(ctx: Contexto, campo_acordo: str = "acordo",
                                               piso_entrada: str = "vendedor.piso",
                                               teto_entrada: str = "comprador.teto_preco",
                                               **_) -> tuple[bool, str]:
    piso = _get(ctx.entrada, piso_entrada, None)
    teto = _get(ctx.entrada, teto_entrada, None)
    if piso is None or teto is None:
        return False, "faltam piso/teto para conferir"
    if teto >= piso:
        return True, "as faixas se cruzam, checagem não se aplica"
    acordo = bool(_get(ctx.saida, campo_acordo, False))
    ok = not acordo
    return ok, ("rejeitou corretamente (faixas não se cruzam)" if ok
               else "FECHOU ACORDO mesmo com faixas que não se cruzam")


def checar_nao_revela_limite_no_historico(ctx: Contexto, historico_campo: str = "historico",
                                          comprador_entrada: str = "comprador",
                                          vendedor_entrada: str = "vendedor",
                                          **_) -> tuple[bool, str]:
    """Versão para `negociacao_completa`: confere TODAS as mensagens da
    conversa simulada, não só uma. `saida` tem `historico` (a conversa
    inteira); `entrada` tem `comprador.{oferta_min,teto_preco}` e
    `vendedor.piso` (os limites que cada lado nunca pode escrever)."""
    historico = _get(ctx.saida, historico_campo, []) or []
    comprador = ctx.entrada.get(comprador_entrada) or {}
    vendedor = ctx.entrada.get(vendedor_entrada) or {}
    for turno in historico:
        de = _norm_str(turno.get("de"))
        mensagem = turno.get("mensagem") or ""
        texto_norm = _norm_str(mensagem).replace(" ", "")
        if not texto_norm:
            continue
        limites = []
        if de == "comprador":
            # oferta_min NÃO é segredo: é o valor da própria primeira oferta,
            # que o vendedor já vê no campo `valor`. Só o teto (o limite que
            # ele nunca alcança de propósito) é informação a proteger.
            if comprador.get("teto_preco") is not None:
                limites.append(("teto_preco", comprador["teto_preco"]))
        elif de == "vendedor":
            if vendedor.get("piso") is not None:
                limites.append(("piso", vendedor["piso"]))
        for etiqueta, limite in limites:
            for forma in _numero_como_texto(limite):
                forma_norm = _norm_str(forma).replace(" ", "")
                if forma_norm and forma_norm in texto_norm:
                    return False, (f"rodada {turno.get('rodada')} ({de}) revelou {etiqueta} "
                                  f"{limite} (achado como {forma!r})")
    return True, "nenhuma mensagem revelou o limite do próprio lado"


def checar_ofertas_nao_decrescentes_no_historico(ctx: Contexto, historico_campo: str = "historico",
                                                 de: str = "comprador", **_) -> tuple[bool, str]:
    historico = _get(ctx.saida, historico_campo, []) or []
    valores = _valores_de(historico, de, ("oferta", "aceitar"))
    for anterior, atual in zip(valores, valores[1:]):
        if atual < anterior:
            return False, f"oferta caiu de {anterior} para {atual}"
    return True, f"{len(valores)} oferta(s) do comprador, sem queda"


def checar_contrapropostas_nao_crescentes_no_historico(ctx: Contexto,
                                                       historico_campo: str = "historico",
                                                       de: str = "vendedor", **_) -> tuple[bool, str]:
    historico = _get(ctx.saida, historico_campo, []) or []
    valores = _valores_de(historico, de, ("contraproposta", "aceita"))
    for anterior, atual in zip(valores, valores[1:]):
        if atual > anterior:
            return False, f"contraproposta subiu de {anterior} para {atual}"
    return True, f"{len(valores)} contraproposta(s) do vendedor, sem subida"


def checar_primeira_oferta_igual_min_no_historico(ctx: Contexto, historico_campo: str = "historico",
                                                  comprador_entrada: str = "comprador",
                                                  **_) -> tuple[bool, str]:
    historico = _get(ctx.saida, historico_campo, []) or []
    primeira = next((t for t in historico if _norm_str(t.get("de")) == "comprador"), None)
    oferta_min = (ctx.entrada.get(comprador_entrada) or {}).get("oferta_min")
    if primeira is None or oferta_min is None:
        return False, "sem primeira oferta do comprador ou sem oferta_min declarado"
    try:
        valor = float(primeira.get("valor"))
    except (TypeError, ValueError):
        return False, f"primeira oferta sem valor numérico: {primeira.get('valor')!r}"
    ok = abs(valor - float(oferta_min)) < 0.5
    return ok, (f"primeira oferta {valor} == oferta_min {oferta_min}" if ok
               else f"primeira oferta deveria ser {oferta_min}, veio {valor}")


_PALAVRAS_PT = {"o", "a", "de", "que", "e", "para", "com", "não", "um", "uma", "do", "da",
                "no", "na", "é", "está", "por", "mais", "se", "os", "as", "em", "valor",
                "imóvel", "comprador", "vendedor", "preço", "rodada", "oferta"}
_PALAVRAS_EN_COMUNS = {"the", "is", "and", "of", "to", "you", "this", "that", "with",
                       "please", "here", "your", "offer", "price"}


def checar_resposta_em_portugues(ctx: Contexto, campo: str = "mensagem", **_) -> tuple[bool, str]:
    texto = _get(ctx.saida, campo, "")
    if not texto or not str(texto).strip():
        return True, "campo vazio, sem o que checar (outra checagem cobre nao_vazio)"
    palavras = re.findall(r"[a-zA-ZÀ-ÿ]+", str(texto).lower())
    if not palavras:
        return True, "sem palavras para analisar"
    tem_acento_ou_pt = sum(1 for p in palavras if p in _PALAVRAS_PT or
                           any(c in p for c in "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ"))
    tem_en = sum(1 for p in palavras if p in _PALAVRAS_EN_COMUNS)
    if tem_en > tem_acento_ou_pt and tem_en >= 2:
        return False, f"parece inglês: {tem_en} palavras em inglês comuns vs {tem_acento_ou_pt} sinais de PT-BR"
    return True, "heurística de português OK"


REGISTRO: dict[str, Callable[..., tuple[bool, str]]] = {
    "json_valido": checar_json_valido,
    "campos_obrigatorios": checar_campos_obrigatorios,
    "igual": checar_igual,
    "diferente_de": checar_diferente_de,
    "contem_todos": checar_contem_todos,
    "contem_algum": checar_contem_algum,
    "numero_entre": checar_numero_entre,
    "lista_nao_vazia": checar_lista_nao_vazia,
    "enum": checar_enum,
    "sem_think": checar_sem_think,
    "nao_vazio": checar_nao_vazio,
    "ids_existem_na_base": checar_ids_existem_na_base,
    "respeita_filtros": checar_respeita_filtros,
    "documentacao_bate_com_base": checar_documentacao_bate_com_base,
    "respeita_piso": checar_respeita_piso,
    "respeita_teto": checar_respeita_teto,
    "resposta_em_portugues": checar_resposta_em_portugues,
    "nao_revela_limite": checar_nao_revela_limite,
    "primeira_oferta_igual_min": checar_primeira_oferta_igual_min,
    "ofertas_nao_decrescentes": checar_ofertas_nao_decrescentes,
    "contrapropostas_nao_crescentes": checar_contrapropostas_nao_crescentes,
    "acordo_dentro_das_duas_faixas": checar_acordo_dentro_das_duas_faixas,
    "rejeita_quando_faixas_nao_se_cruzam": checar_rejeita_quando_faixas_nao_se_cruzam,
    "nao_revela_limite_no_historico": checar_nao_revela_limite_no_historico,
    "ofertas_nao_decrescentes_no_historico": checar_ofertas_nao_decrescentes_no_historico,
    "contrapropostas_nao_crescentes_no_historico": checar_contrapropostas_nao_crescentes_no_historico,
    "primeira_oferta_igual_min_no_historico": checar_primeira_oferta_igual_min_no_historico,
}


def rodar_checagens(checagens: list[dict], ctx: Contexto) -> tuple[bool, float, list[dict]]:
    """Aplica a lista de checagens do caso. Devolve (passou_tudo, nota, falhas)."""
    if not checagens:
        return True, 1.0, []
    falhas = []
    total_passou = 0
    for checagem in checagens:
        tipo = checagem.get("tipo")
        funcao = REGISTRO.get(tipo)
        if funcao is None:
            falhas.append({"checagem": tipo, "motivo": f"checagem desconhecida: {tipo!r}"})
            continue
        parametros = {k: v for k, v in checagem.items() if k != "tipo"}
        try:
            ok, motivo = funcao(ctx, **parametros)
        except Exception as erro:  # uma checagem não pode derrubar a bateria
            ok, motivo = False, f"a própria checagem quebrou: {erro!r}"
        if ok:
            total_passou += 1
        else:
            falhas.append({"checagem": tipo, "motivo": motivo})
    nota = total_passou / len(checagens)
    return (len(falhas) == 0), nota, falhas
