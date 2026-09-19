"""Saída estruturada de cada skill, em Pydantic. O Agno pede o JSON no formato.

Por que schema e não só "responda em JSON": medido em 19/09 contra a API real,
o modelo devolvia `{"itens": [{"itens": [...]}]}`, com a lista de verdade um
nível abaixo. Com `output_schema` isso deixou de acontecer. O extrator tolerante
continua no código como rede de segurança, porque `auto` vai para `text` e
`text` não garante nada.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Pedido(BaseModel):
    tipo: str = Field(default="apartamento", description="apartamento, cobertura ou casa")
    cidade: str = Field(default="São Paulo")
    bairros: list[str] = Field(default_factory=list)
    preco_max: int | None = Field(default=None, description="teto em reais, só número")
    quartos_min: int | None = None
    vagas_min: int | None = None
    area_min: int | None = Field(default=None, description="em metros quadrados")
    objetivo: str = Field(default="moradia", description="moradia ou investimento")
    financiamento: bool = False


class PedidoEntendido(BaseModel):
    pedido: Pedido
    suposicoes: list[str] = Field(default_factory=list,
                                  description="o que você assumiu porque a frase não disse")


class ItemImovel(BaseModel):
    property_id: str
    preco: int
    area: int
    quartos: int
    vagas: int
    localizacao: str
    seller_agent: str
    disponibilidade: str = Field(description="available ou unavailable")
    documentacao_status: str = Field(
        description="basic_verified, pendencias ou sem_documentos")
    motivo: str = Field(description="uma frase para o comprador ler")


class ListaImoveis(BaseModel):
    itens: list[ItemImovel] = Field(default_factory=list)


class JogadaCompra(BaseModel):
    acao: str = Field(description="oferta, aceitar ou desistir")
    valor: int | None = Field(default=None, description="em reais, nunca acima do teto")
    mensagem: str = Field(default="", description="uma ou duas frases para o agente do vendedor")
    motivo: str = Field(default="", description="por que essa jogada, em uma frase")


class JogadaVenda(BaseModel):
    acao: str = Field(description="aceita, contraproposta ou rejeita")
    valor: int | None = Field(default=None, description="em reais")
    mensagem: str = Field(default="", description="uma ou duas frases para o agente do comprador")
    motivo: str = Field(default="", description="por que essa jogada, em uma frase")


class EscolhaDeFornecedor(BaseModel):
    escolhido: str = Field(description="o agente_id exato de um dos candidatos")
    motivo: str = Field(description="uma ou duas frases em português simples dizendo "
                                    "por que este e não o outro")
