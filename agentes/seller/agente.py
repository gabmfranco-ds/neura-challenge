"""Seller Agent: um por imóvel, com FAIXA própria e vontade de negociar.

A faixa dele vai do preço pedido (o anúncio, o máximo que ele espera tirar) até
o piso do proprietário (o mínimo que ele aceita). Os dois números e a pressa
moram em `dados/imoveis.json`, dentro de `_privado_vendedor`, e NÃO saem daqui:
nem o Buyer Agent nem o Orchestrator recebem o piso.

Ele não é um respondedor: é um negociador. Defende o preço pedido, cede aos
poucos conforme a pressa do proprietário, e nunca fecha abaixo do piso.

Nada aqui corrige o valor que o modelo escolheu. Quem descarta jogada fora da
regra e manda refazer é o Orchestrator, por conta de código, e a violação vira
evento. Corrigir aqui em silêncio esconderia o dado.
"""
from __future__ import annotations

import json

from agentes import comum
from agentes.esquemas import JogadaVenda
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
    preco_pedido = int(imovel["preco"])
    pressa = float(privado.get("pressa") or 0.5)
    oferta = entrada.get("oferta")
    rodada = int(entrada.get("rodada") or 1)
    max_rodadas = int(entrada.get("max_rodadas") or 3)
    historico = entrada.get("historico") or []
    correcao = (entrada.get("correcao") or "").strip()

    linhas_historico = "\n".join(
        f"  rodada {h.get('rodada')}: {h.get('de')} -> {h.get('acao')} "
        f"{comum.dinheiro(h.get('valor'))}: {h.get('mensagem', '')[:160]}"
        for h in historico) or "  (nenhuma ainda)"

    minhas = [h.get("valor") for h in historico
              if h.get("acao") == "contraproposta" and h.get("valor")]
    minha_menor = min(minhas) if minhas else None

    grau_pressa = ("MUITA pressa: pode chegar perto do piso rápido para fechar"
                   if pressa >= 0.7 else
                   "pressa MÉDIA: negocia, cede aos poucos, mas não regala"
                   if pressa >= 0.4 else
                   "NENHUMA pressa: segura perto do preço pedido e prefere perder o "
                   "comprador a vender barato")

    situacao = [
        f"A sua faixa vai de {comum.dinheiro(preco_pedido)} (preço pedido, onde você quer "
        f"chegar) até {comum.dinheiro(piso)} (piso do proprietário, o mínimo). O piso é "
        f"SEGREDO SEU: nunca escreva esse número numa mensagem para o comprador.",
        f"Situação do proprietário: {privado.get('motivo_venda', 'não informado')}. "
        f"Nível de pressa: {grau_pressa}.",
    ]
    if minha_menor:
        situacao.append(f"A sua menor contraproposta até agora foi "
                        f"{comum.dinheiro(minha_menor)}. Você pode descer a partir dela, "
                        f"nunca subir: encarecer no meio da conversa quebra a negociação.")
    else:
        situacao.append("Esta é a sua primeira resposta: comece defendendo o preço pedido "
                        "ou muito perto dele.")
    if rodada >= max_rodadas:
        situacao.append("ESTA É A ÚLTIMA RODADA. Ou fecha agora, ou o comprador vai embora "
                        "e o imóvel continua no mercado.")
    if correcao:
        situacao.append(f"A SUA JOGADA ANTERIOR FOI DESCARTADA pelo orquestrador: {correcao} "
                        f"Refaça dentro da regra.")

    mensagens = [
        comum.sistema(ficha, "Você NEGOCIA pelo proprietário: defende o preço pedido e cede "
                             "aos poucos, nunca abaixo do piso. O piso é informação sua."),
        {"role": "user", "content": (
            f"Imóvel: {imovel['tipo']} em {imovel['bairro']}, {imovel['area']} m2, "
            f"{imovel['quartos']} quartos, {imovel['vagas']} vagas.\n"
            f"Rodada {rodada} de no máximo {max_rodadas}.\n"
            f"Histórico:\n{linhas_historico}\n\n"
            + "\n".join(situacao) + "\n\n"
            f"O agente do comprador ofereceu {comum.dinheiro(oferta)} e disse: "
            f"\"{entrada.get('mensagem', '')}\"\n\n"
            "Responda SÓ com este JSON:\n"
            '{"acao":"aceita|contraproposta|rejeita","valor":0,"mensagem":"uma ou duas frases '
            'para o agente do comprador","motivo":"por que, em uma frase"}\n\n'
            "Regras duras:\n"
            "1. `valor` é número inteiro em reais.\n"
            "2. Em `aceita`, repita exatamente o valor que o comprador ofereceu.\n"
            "3. Em `contraproposta`, o valor fica entre o piso e o preço pedido, e nunca é "
            "maior que a sua contraproposta anterior.\n"
            "4. Em `rejeita`, use o preço pedido.\n"
            "5. Nunca escreva o seu piso na mensagem.\n"
            "6. Quanto mais pressa, mais perto do piso você pode chegar."
        )},
    ]
    objeto, resultado = await comum.pedir_json(
        ficha, mensagens, etapa=f"negociar_venda:r{rodada}", rodada_id=rodada_id,
        max_tokens=600, temperature=0.5, esquema=JogadaVenda)
    jogada = _jogada(objeto, preco_pedido=preco_pedido, oferta=oferta)
    jogada["custo_usd"] = resultado.custo_usd
    return jogada


def _jogada(objeto, *, preco_pedido: int, oferta) -> dict:
    """Só normaliza formato. NÃO corrige valor: quem julga é a verificação por
    código do Orchestrator."""
    if not isinstance(objeto, dict):
        return {"acao": "contraproposta", "valor": preco_pedido,
                "mensagem": "Mantenho o valor anunciado por enquanto.",
                "motivo": "o modelo não devolveu uma jogada legível"}
    acao = str(objeto.get("acao") or "contraproposta").strip().lower()
    if acao not in ("aceita", "contraproposta", "rejeita"):
        acao = "contraproposta"
    valor = objeto.get("valor")
    try:
        valor = int(float(valor))
    except (TypeError, ValueError):
        valor = int(oferta or preco_pedido)
    return {"acao": acao, "valor": valor,
            "mensagem": str(objeto.get("mensagem") or "")[:400],
            "motivo": str(objeto.get("motivo") or "")[:240]}
