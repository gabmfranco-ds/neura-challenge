"""Seller Agent: um por imóvel, com piso de preço e pressa próprios.

O piso e a pressa moram em `dados/imoveis.json`, dentro de `_privado_vendedor`,
e NÃO saem daqui: nem o Buyer Agent nem o Orchestrator recebem esses números. O
Seller Agent decide sozinho se aceita, contrapropõe ou rejeita.

Trava de mandato (a mesma que o Buyer Agent tem no teto): o agente não fecha
abaixo do piso que o proprietário deu. Se o modelo aceitar abaixo, a jogada vira
contraproposta no piso e o motivo diz isso. É cumprir o limite do cliente, não
forçar a resposta do modelo.
"""
from __future__ import annotations

import json

from agentes import comum
from nucleo import dados


async def executar(ficha: dict, skill: str, entrada: dict, rodada_id: str | None) -> dict:
    if skill != "negociar_venda":
        raise ValueError(f"skill desconhecida para o seller: {skill!r}")

    property_id = ficha.get("property_id") or entrada.get("property_id")
    imovel = dados.imovel(property_id)
    if imovel is None:
        raise ValueError(f"imóvel desconhecido: {property_id!r}")

    privado = imovel.get("_privado_vendedor") or {}
    piso = int(privado.get("piso_preco") or imovel["preco"])
    pressa = float(privado.get("pressa") or 0.5)
    oferta = entrada.get("oferta")
    rodada = int(entrada.get("rodada") or 1)
    max_rodadas = int(entrada.get("max_rodadas") or 4)
    historico = entrada.get("historico") or []

    linhas_historico = "\n".join(
        f"  rodada {h.get('rodada')}: {h.get('de')} -> {h.get('acao')} "
        f"{comum.dinheiro(h.get('valor'))}: {h.get('mensagem', '')[:160]}"
        for h in historico) or "  (nenhuma ainda)"

    grau_pressa = ("muita pressa, quer fechar rápido e aceita descontar"
                   if pressa >= 0.7 else
                   "pressa média, negocia mas não regala"
                   if pressa >= 0.4 else
                   "sem pressa nenhuma, prefere esperar comprador melhor")

    mensagens = [
        comum.sistema(ficha, "Você fala pelo proprietário. O piso e a pressa são informação "
                             "sua: nunca diga o piso em número para o outro lado."),
        {"role": "user", "content": (
            f"Imóvel: {imovel['tipo']} em {imovel['bairro']}, {imovel['area']} m2, "
            f"{imovel['quartos']} quartos, {imovel['vagas']} vagas.\n"
            f"Preço de anúncio: {comum.dinheiro(imovel['preco'])}.\n"
            f"Piso do proprietário (segredo seu): {comum.dinheiro(piso)}.\n"
            f"Situação do proprietário: {privado.get('motivo_venda', 'não informado')}. "
            f"Nível de pressa: {grau_pressa}.\n\n"
            f"Rodada {rodada} de no máximo {max_rodadas}.\n"
            f"Histórico:\n{linhas_historico}\n\n"
            f"O agente do comprador ofereceu {comum.dinheiro(oferta)} e disse: "
            f"\"{entrada.get('mensagem', '')}\"\n\n"
            "Responda SÓ com este JSON:\n"
            '{"acao":"aceita|contraproposta|rejeita","valor":0,"mensagem":"uma ou duas frases '
            'para o agente do comprador","motivo":"por que, em uma frase"}\n\n'
            "Regras: `valor` é número inteiro em reais. Em `aceita`, repita o valor ofertado. "
            "Em `contraproposta`, dê o seu número. Em `rejeita`, use o preço de anúncio. "
            "Quanto mais pressa, mais perto do piso você pode chegar. Nas últimas rodadas, "
            "feche ou perca o comprador."
        )},
    ]
    objeto, resultado = await comum.pedir_json(ficha, mensagens, etapa=f"negociar_venda:r{rodada}",
                                               rodada_id=rodada_id, max_tokens=600,
                                               temperature=0.5)
    jogada = _jogada(objeto, piso=piso, anuncio=imovel["preco"], oferta=oferta)
    jogada["custo_usd"] = resultado.custo_usd
    return jogada


def _jogada(objeto, *, piso: int, anuncio: int, oferta) -> dict:
    if not isinstance(objeto, dict):
        return {"acao": "contraproposta", "valor": anuncio,
                "mensagem": "Mantenho o valor anunciado por enquanto.",
                "motivo": "o modelo não devolveu uma jogada legível"}
    acao = str(objeto.get("acao") or "contraproposta").strip().lower()
    if acao not in ("aceita", "contraproposta", "rejeita"):
        acao = "contraproposta"
    valor = objeto.get("valor")
    try:
        valor = int(float(valor))
    except (TypeError, ValueError):
        valor = int(oferta or anuncio)
    motivo = str(objeto.get("motivo") or "")[:240]

    if acao == "aceita" and valor < piso:
        acao = "contraproposta"
        valor = piso
        motivo += " (valor abaixo do piso do proprietário, virou contraproposta no piso)"
    if acao == "contraproposta" and valor < piso:
        valor = piso
        motivo += " (contraproposta subida até o piso do proprietário)"

    return {"acao": acao, "valor": valor,
            "mensagem": str(objeto.get("mensagem") or "")[:400], "motivo": motivo}
