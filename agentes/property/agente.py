"""Property Agents. Duas variantes concorrentes na mesma capacidade.

A diferença entre elas está na FICHA, em dois campos: `estrategia` e
`acesso_a_dados`. O código aqui é o mesmo para as duas: ele lê a ficha e monta a
visão dos dados que aquela ficha declarou comprar.

- `Casa Verificada` declarou que abre documento e confere disponibilidade, então
  recebe `visao_completa` (anúncio + disponibilidade + texto dos documentos).
- `Busca Relâmpago` declarou que trabalha só com o anúncio, então recebe
  `visao_anuncio`. Ela precisa preencher disponibilidade e status de
  documentação assim mesmo, e o que ela escreve sai do modelo, não daqui.

Nenhuma linha deste arquivo decide que uma vai errar. A verificação do
Orchestrator é que descobre, depois, quem acertou.
"""
from __future__ import annotations

import json

from agentes import comum
from nucleo import dados

MAX_CANDIDATOS = 8


async def executar(ficha: dict, skill: str, entrada: dict, rodada_id: str | None) -> dict:
    if skill != "buscar_imoveis":
        raise ValueError(f"skill desconhecida para o property: {skill!r}")

    pedido = entrada.get("pedido") or {}
    evitar = set(entrada.get("evitar") or [])
    quantidade = int(entrada.get("quantidade") or 4)

    candidatos, ampliou = _candidatos(pedido, evitar)
    if not candidatos:
        return {"itens": [], "observacao": "nenhum imóvel na base atende ao pedido",
                "custo_usd": 0.0, "candidatos_vistos": 0}

    completo = "documento" in (ficha.get("acesso_a_dados") or "")
    visao = [dados.visao_completa(c) if completo else dados.visao_anuncio(c) for c in candidatos]

    instrucao_extra = (
        "Você abriu os documentos de cada candidato. Use o campo `documentos` para dizer o "
        "status de documentação: `basic_verified` quando matrícula, certidões, IPTU e "
        "condomínio estiverem limpos e dentro da validade; `pendencias` quando qualquer um "
        "deles tiver problema; `sem_documentos` quando não houver texto. Use o campo "
        "`disponibilidade` da base como está."
        if completo else
        "Você NÃO recebe documento nem campo de disponibilidade: a sua ficha diz que você "
        "trabalha com o anúncio. Preencha `disponibilidade` e `documentacao_status` com o "
        "que o anúncio te permite concluir. Valores possíveis: `available` ou `unavailable`; "
        "`basic_verified`, `pendencias` ou `sem_documentos`."
    )

    mensagens = [
        comum.sistema(ficha),
        {"role": "user", "content": (
            f"Pedido do comprador:\n{json.dumps(pedido, ensure_ascii=False)}\n\n"
            f"Candidatos da base ({len(visao)}):\n"
            f"{json.dumps(visao, ensure_ascii=False, indent=1)}\n\n"
            f"{instrucao_extra}\n\n"
            f"Escolha até {quantidade} imóveis e responda SÓ com este JSON:\n"
            '{"itens":[{"property_id":"SP1234","preco":0,"area":0,"quartos":0,"vagas":0,'
            '"localizacao":"bairro e rua","seller_agent":"AGT000",'
            '"disponibilidade":"available","documentacao_status":"basic_verified",'
            '"motivo":"uma frase dizendo por que este imóvel serve para este comprador"}]}\n\n'
            "Regras: use só `property_id` que está na lista de candidatos. Copie preço, área, "
            "quartos e vagas exatamente como vieram. O motivo é para o comprador ler."
        )},
    ]
    objeto, resultado = await comum.pedir_json(ficha, mensagens, etapa="buscar_imoveis",
                                               rodada_id=rodada_id, max_tokens=1600)
    itens = extrair_itens(objeto)[:quantidade]

    return {
        "itens": itens,
        "observacao": ("busca ampliada porque o filtro exato não trouxe candidatos"
                       if ampliou else ""),
        "candidatos_vistos": len(visao),
        "custo_usd": resultado.custo_usd,
    }


def extrair_itens(objeto, profundidade: int = 0) -> list[dict]:
    """Desembrulha a lista de imóveis de uma resposta de modelo.

    Medido contra a API real em 19/09: o modelo às vezes devolve
    `{"itens": [{"itens": [ ... ]}]}`, com a lista de verdade um nível abaixo.
    Cobrar formato perfeito do modelo é perder entrega boa por casca.
    """
    if profundidade > 4 or objeto is None:
        return []
    if isinstance(objeto, dict):
        if objeto.get("property_id"):
            return [objeto]
        for chave in ("itens", "imoveis", "resultados", "data"):
            if chave in objeto:
                return extrair_itens(objeto[chave], profundidade + 1)
        return []
    if isinstance(objeto, list):
        saida: list[dict] = []
        for elemento in objeto:
            saida.extend(extrair_itens(elemento, profundidade + 1))
        return saida
    return []


def _candidatos(pedido: dict, evitar: set[str]) -> tuple[list[dict], bool]:
    """Acesso do agente à base. Se o filtro exato não traz ninguém, o agente
    afrouxa area_min e depois vagas_min, e avisa que ampliou."""
    encontrados = [im for im in dados.filtrar(pedido) if im["property_id"] not in evitar]
    ampliou = False
    for solto in ("area_min", "vagas_min", "quartos_min"):
        if encontrados:
            break
        pedido = {**pedido, solto: None}
        encontrados = [im for im in dados.filtrar(pedido) if im["property_id"] not in evitar]
        ampliou = True
    encontrados.sort(key=lambda im: im["preco"] / im["area"] if im["area"] else im["preco"])
    return encontrados[:MAX_CANDIDATOS], ampliou
