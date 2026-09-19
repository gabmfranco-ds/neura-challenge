"""Buyer Agent. Duas capacidades: entender o pedido e negociar pelo comprador.

Na negociação ele age dentro de um MANDATO (teto de preço e prazo) que o
comprador deu uma vez. Não existe botão de aprovar no meio: se a jogada cabe no
mandato, ele joga.
"""
from __future__ import annotations

import json
import re

from agentes import comum

PEDIDO_EXEMPLO = {
    "tipo": "apartamento", "cidade": "São Paulo", "bairros": ["Pinheiros", "Vila Madalena"],
    "preco_max": 2000000, "quartos_min": 3, "vagas_min": 2, "area_min": 120,
    "objetivo": "moradia", "financiamento": True,
}


async def executar(ficha: dict, skill: str, entrada: dict, rodada_id: str | None) -> dict:
    if skill == "entender_pedido":
        return await _entender(ficha, entrada, rodada_id)
    if skill == "negociar_compra":
        return await _negociar(ficha, entrada, rodada_id)
    raise ValueError(f"skill desconhecida para o buyer: {skill!r}")


async def _entender(ficha: dict, entrada: dict, rodada_id: str | None) -> dict:
    frase = (entrada.get("frase") or "").strip()
    mensagens = [
        comum.sistema(ficha),
        {"role": "user", "content": (
            "Transforme a frase do comprador abaixo em um pedido estruturado de imóvel.\n\n"
            f"FRASE: {frase}\n\n"
            "Responda com este JSON exato (sem nada em volta):\n"
            '{"pedido": ' + json.dumps(PEDIDO_EXEMPLO, ensure_ascii=False) + ', '
            '"suposicoes": ["o que você assumiu porque a frase não disse"]}\n\n'
            "Regras: valores em reais, números sem ponto nem texto. `bairros` é lista; se a "
            "frase não citar bairro, devolva lista vazia. `tipo` é um de: apartamento, "
            "cobertura, casa. `objetivo` é moradia ou investimento. Só assuma o que for "
            "razoável e escreva cada suposição em `suposicoes`."
        )},
    ]
    objeto, resultado = await comum.pedir_json(ficha, mensagens, etapa="entender_pedido",
                                               rodada_id=rodada_id, max_tokens=700)
    if isinstance(objeto, dict) and isinstance(objeto.get("pedido"), dict):
        pedido = _limpar_pedido(objeto["pedido"])
        suposicoes = [str(s) for s in (objeto.get("suposicoes") or [])][:6]
        return {"pedido": pedido, "suposicoes": suposicoes, "fonte": "modelo",
                "custo_usd": resultado.custo_usd}

    # O modelo não devolveu JSON utilizável. Em vez de derrubar a rodada, o
    # próprio Buyer Agent cai para uma leitura por regra de código da frase, e
    # DIZ que foi isso. Nunca inventa imóvel: só lê o que está escrito.
    return {"pedido": _pedido_por_regra(frase), "suposicoes": [],
            "fonte": "regra de código (o modelo não devolveu JSON válido)",
            "custo_usd": resultado.custo_usd}


def _limpar_pedido(bruto: dict) -> dict:
    def numero(chave):
        valor = bruto.get(chave)
        if isinstance(valor, (int, float)):
            return int(valor)
        if isinstance(valor, str):
            so_digitos = re.sub(r"[^\d]", "", valor)
            return int(so_digitos) if so_digitos else None
        return None

    bairros = bruto.get("bairros")
    if isinstance(bairros, str):
        bairros = [b.strip() for b in bairros.split(",") if b.strip()]
    return {
        "tipo": (bruto.get("tipo") or "apartamento"),
        "cidade": (bruto.get("cidade") or "São Paulo"),
        "bairros": [str(b) for b in (bairros or [])],
        "preco_max": numero("preco_max"),
        "quartos_min": numero("quartos_min"),
        "vagas_min": numero("vagas_min"),
        "area_min": numero("area_min"),
        "objetivo": bruto.get("objetivo") or "moradia",
        "financiamento": bool(bruto.get("financiamento")),
    }


BAIRROS_CONHECIDOS = ["Pinheiros", "Vila Madalena", "Vila Mariana", "Moema", "Perdizes"]


def _pedido_por_regra(frase: str) -> dict:
    texto = frase.lower()
    preco = None
    achado = re.search(r"(\d+[\d\.,]*)\s*(milh|mi\b|m\b|mil)", texto)
    if achado:
        numero = float(achado.group(1).replace(".", "").replace(",", "."))
        preco = int(numero * (1_000_000 if achado.group(2).startswith(("milh", "mi", "m")) else 1_000))
    quartos = re.search(r"(\d+)\s*(quarto|dormit)", texto)
    vagas = re.search(r"(\d+)\s*vaga", texto)
    area = re.search(r"(\d+)\s*m2|\b(\d+)\s*metros", texto)
    return {
        "tipo": "cobertura" if "cobertura" in texto else ("casa" if " casa" in texto else "apartamento"),
        "cidade": "São Paulo",
        "bairros": [b for b in BAIRROS_CONHECIDOS if b.lower() in texto],
        "preco_max": preco,
        "quartos_min": int(quartos.group(1)) if quartos else None,
        "vagas_min": int(vagas.group(1)) if vagas else None,
        "area_min": int(area.group(1) or area.group(2)) if area else None,
        "objetivo": "investimento" if "investimento" in texto else "moradia",
        "financiamento": "financi" in texto,
    }


async def _negociar(ficha: dict, entrada: dict, rodada_id: str | None) -> dict:
    imovel = entrada.get("imovel") or {}
    mandato = entrada.get("mandato") or {}
    historico = entrada.get("historico") or []
    rodada = int(entrada.get("rodada") or 1)
    max_rodadas = int(entrada.get("max_rodadas") or 4)
    teto = mandato.get("teto_preco")

    linhas_historico = "\n".join(
        f"  rodada {h.get('rodada')}: {h.get('de')} -> {h.get('acao')} "
        f"{comum.dinheiro(h.get('valor'))}: {h.get('mensagem', '')[:160]}"
        for h in historico) or "  (nenhuma ainda)"

    minha_ultima = max([h.get("valor") or 0 for h in historico
                        if h.get("acao") in ("oferta", "aceitar")] or [0])
    contrapropostas = [h.get("valor") for h in historico
                       if h.get("acao") == "contraproposta" and h.get("valor")]
    ultima_do_vendedor = contrapropostas[-1] if contrapropostas else None
    ultima_rodada = rodada >= max_rodadas

    situacao = []
    if ultima_do_vendedor:
        cabe = ultima_do_vendedor <= (teto or 0)
        situacao.append(
            f"A última contraproposta do vendedor foi {comum.dinheiro(ultima_do_vendedor)} e ela "
            + ("CABE no seu teto." if cabe else "NÃO cabe no seu teto."))
        if cabe:
            situacao.append("Aceitar agora garante o imóvel. Insistir pode perder o negócio.")
    if minha_ultima:
        situacao.append(f"A sua maior oferta até agora foi {comum.dinheiro(minha_ultima)}. "
                        f"Nunca ofereça menos do que isso: baixar oferta quebra a negociação.")
    if ultima_rodada:
        situacao.append("ESTA É A ÚLTIMA RODADA. Depois dela não há mais conversa: ou você "
                        "aceita o que está na mesa (se couber no teto), ou o negócio morre.")

    mensagens = [
        comum.sistema(ficha, "Você negocia pelo comprador. O mandato é o seu limite duro: "
                             "nunca ofereça acima do teto, nem para fechar."),
        {"role": "user", "content": (
            f"Imóvel em negociação:\n{json.dumps(imovel, ensure_ascii=False, indent=2)}\n\n"
            f"Seu mandato: teto de {comum.dinheiro(teto)}, prazo de "
            f"{mandato.get('prazo_dias', 60)} dias. O comprador não vai ser consultado de novo.\n"
            f"Rodada {rodada} de no máximo {max_rodadas}.\n"
            f"Histórico da negociação:\n{linhas_historico}\n\n"
            + ("\n".join(situacao) + "\n\n" if situacao else "")
            + "Decida a próxima jogada e responda SÓ com este JSON:\n"
            '{"acao":"oferta|aceitar|desistir","valor":0,"mensagem":"uma ou duas frases para '
            'o agente do vendedor","motivo":"por que essa jogada, em uma frase"}\n\n'
            "Regras duras:\n"
            "1. `valor` é número inteiro em reais e NUNCA passa do teto.\n"
            "2. Se a contraproposta do vendedor couber no teto, `aceitar` com `valor` igual "
            "ao valor dele é a jogada certa, ainda mais na última rodada.\n"
            "3. Uma nova `oferta` tem que ser MAIOR que a sua oferta anterior.\n"
            "4. Só use `desistir` quando nada na mesa couber no teto."
        )},
    ]
    objeto, resultado = await comum.pedir_json(ficha, mensagens, etapa=f"negociar_compra:r{rodada}",
                                               rodada_id=rodada_id, max_tokens=600,
                                               temperature=0.5)
    jogada = _jogada(objeto, teto, padrao_valor=imovel.get("preco"), piso_proprio=minha_ultima)
    jogada["custo_usd"] = resultado.custo_usd
    return jogada


def _jogada(objeto, teto, padrao_valor, piso_proprio: int = 0) -> dict:
    """Duas travas, as duas declaradas na ficha do agente:

    - teto do mandato: o comprador autorizou um limite, e nenhuma jogada passa dele;
    - oferta monotônica: a ficha diz "sobe devagar", então uma oferta nova nunca
      vem abaixo da oferta anterior. Baixar preço no meio de uma negociação é o
      jeito mais rápido de perder o imóvel.

    A decisão de aceitar, ofertar ou desistir continua inteira do modelo.
    """
    if not isinstance(objeto, dict):
        return {"acao": "desistir", "valor": None,
                "mensagem": "Não consegui formular a proposta agora.",
                "motivo": "o modelo não devolveu uma jogada legível"}
    acao = str(objeto.get("acao") or "oferta").strip().lower()
    if acao not in ("oferta", "aceitar", "desistir"):
        acao = "oferta"
    valor = objeto.get("valor")
    try:
        valor = int(float(valor))
    except (TypeError, ValueError):
        valor = int(padrao_valor or 0) or None

    notas = []
    if acao == "oferta" and valor is not None and piso_proprio and valor < piso_proprio:
        valor = int(piso_proprio)
        notas.append("oferta segurada na anterior: a estratégia declarada é subir, nunca baixar")
    if teto is not None and valor is not None and valor > teto:
        valor = int(teto)
        notas.append("valor cortado no teto do mandato")

    return {
        "acao": acao, "valor": valor,
        "mensagem": str(objeto.get("mensagem") or "")[:400],
        "motivo": str(objeto.get("motivo") or "")[:240]
                  + ((" (" + "; ".join(notas) + ")") if notas else ""),
    }
