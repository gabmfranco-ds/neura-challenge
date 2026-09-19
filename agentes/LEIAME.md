# agentes

Dono: a definir.

Os agentes que o Orchestrator contrata. Cada um tem URL própria, ficha própria em
`/.well-known/agent-card.json` e recebe trabalho em `POST /tarefas`.

| Pasta | Agentes | Usa LLM? |
|---|---|---|
| `buyer/` | Porta Aberta | sim: entende a frase e negocia |
| `property/` | Casa Verificada (US$ 0,90) e Busca Relâmpago (US$ 0,35) | sim |
| `seller/` | um por imóvel, 30 no total | sim: aceita, contrapropõe ou rejeita |
| `transaction/` | Cartório Digital (US$ 1,20) e Fecha Rápido (US$ 0,55) | não: regra de código, SIMULADO |
| `payment/` | Escrow Guardião (US$ 0,80) e Liquida Já (US$ 0,45) | não: regra de código, SIMULADO |

`catalogo.py` guarda as fichas, `rotas.py` é a superfície HTTP, `comum.py` monta o prompt
de sistema a partir da ficha.

## A regra mais importante desta pasta

**O comportamento de um agente sai da ficha dele, nunca de um `if` no código.** As duas
variantes de Property Agent rodam o MESMO código: a diferença é que a ficha de uma
declara `acesso_a_dados: "anuncio + disponibilidade + texto dos documentos"` e a da outra
declara `acesso_a_dados: "somente o anuncio"`. Quem compra o agente barato está comprando
essa limitação, e ela está escrita na ficha pública.

Nenhuma linha aqui força um agente a errar. Quem descobre o erro é a verificação por
código do Orchestrator, depois.

## Agente novo

1. crie a pasta com um `agente.py` que exporte
   `async def executar(ficha, skill, entrada, rodada_id) -> dict`;
2. acrescente a ficha em `catalogo.py` (ou faça o agente se cadastrar de fora, por
   `POST /registry/agentes`);
3. ligue o papel no dicionário `EXECUTORES` de `rotas.py`.

Se o agente usar a NeuraLake, chame por `comum.pedir_json`: é ele que abre a carteira,
debita o custo real e registra o evento.
