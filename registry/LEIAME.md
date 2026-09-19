# registry

Dono: a definir. (Esta pasta era `marketplace/` no esqueleto.)

O marketplace. É a **única URL que o Orchestrator conhece**.

| Rota | O que faz |
|---|---|
| `POST /registry/agentes` | um agente publica a própria ficha e entra no catálogo |
| `GET /registry/agentes?capacidade=X` | fichas de quem faz X, com o histórico de entregas verificadas |
| `GET /registry/agentes?capacidade=X&property_id=Y` | filtra o Seller Agent de um imóvel |
| `GET /registry/agentes/{id}` | uma ficha com histórico |
| `POST /registry/recibos` | o Orchestrator publica o resultado verificado de uma entrega |
| `GET /registry/recibos` | os recibos, filtráveis por agente |

## Histórico

Não é nota, não é estrela e não é opinião. É a soma dos recibos: `entregas`,
`itens_pedidos`, `itens_provados`, `taxa_aprovacao`, `pago_usd`, `retido_usd`. Recibo ruim
derruba o histórico do agente na hora, e o próximo contratante vê.

## Agente novo entra sozinho

Basta um `POST /registry/agentes` com uma ficha que tenha `agente_id`, `url` e `skills`.
Os agentes deste repositório fazem exatamente isso no boot do servidor, por HTTP, como um
agente de fora faria. Ninguém edita lista de agentes na mão.

Ficha válida é a do Agent Card do A2A: `name`, `description`, `url`,
`skills[{id, description, entrada, saida}]`, `preco_usd`, `estrategia` e o que mais o
agente quiser declarar (`acesso_a_dados`, `escrow`, `simulado`).
