# Spec v1 · Agent Marketplace de imóveis

> Hackathon NeuraLake, desafio "Agent Marketplace". Este arquivo descreve o que está
> RODANDO, não o que a gente gostaria. Número aqui saiu de rodada real contra a API.

## A frase

Um comprador escreve uma frase e escolhe um imóvel. Todo o resto, achar quem faz o
trabalho, contratar, negociar preço com o vendedor, conferir documento e liberar
pagamento, é agente conversando com agente, e cada entrega só é paga na parte que o
código conseguiu provar.

## Régua do júri (toda decisão de projeto responde a isto)

| Peso | Critério | O que aparece NA TELA para ganhar o ponto |
|---|---|---|
| 30% | Autonomia entre agentes (e desempate) | placar "decisões sem humano / repasses / intervenções humanas" mais o motivo escrito de cada decisão |
| 25% | Funciona de verdade | fluxo inteiro ao vivo, de SEARCH a COMPLETED; reprise gravada como reserva, sempre rotulada |
| 15% | Valor por token | `auto` em toda chamada, contador "chamadas em auto: N de N", custo real por decisão, verificação por código (zero token) e memória de buscas |
| 15% | Valor de negócio | lista de condições precedentes brasileiras conferidas antes de liberar dinheiro; marketplace paga por entrega verificada |
| 10% | Pitch de 4 min | problema, demo, o que vem depois |
| 5% | Confiança | recibo de cada verificação, retenção visível, rótulo de simulado |

**Eficiência, o que a gente realmente faz**: `auto` em tudo, custo real por decisão,
verificação por conta de código em vez de nota de LLM (custa zero token), chamadas
independentes em paralelo e memória própria de buscas já verificadas. Cross Memory não
entra: não achamos como ligar e o mentor da NeuraLake confirmou que não é o caminho.

## As peças

```
COMPRADOR
   |  (1) a frase
   v
ORCHESTRATOR ---- pergunta por CAPACIDADE ----> REGISTRY (marketplace)
   |                                                |
   |  contrata, delega, verifica, paga             fichas A2A + histórico
   v                                                     de entregas verificadas
BUYER AGENT   PROPERTY AGENTS (2)   SELLER AGENTS (30)   TRANSACTION (2)   PAYMENT (2)
```

O Orchestrator **não conhece nome de agente**. Ele conhece uma URL, a do Registry, e
capacidades (`buscar_imoveis`, `negociar_compra`, `conduzir_transacao`, ...).

## Fluxo 1, achar e escolher

```
COMPRADOR escreve a frase
  -> Orchestrator descobre quem faz "entender_pedido" e contrata
  -> Buyer Agent devolve o pedido estruturado
  -> Orchestrator descobre quem faz "buscar_imoveis": 2 concorrentes com preço e
     estratégia diferentes, avalia ficha + histórico + preço, contrata um
  -> Property Agent consulta a base e devolve de 3 a 4 imóveis com o motivo de cada um
  -> Orchestrator VERIFICA POR CÓDIGO cada imóvel e paga proporcional ao que passou
  -> reprovou demais? publica o recibo ruim no Registry e contrata o concorrente
  -> SHORTLIST -> COMPRADOR ESCOLHE
```

Pedido estruturado que o Buyer Agent produz a partir da frase:

```json
{"tipo":"apartamento","cidade":"São Paulo","bairros":["Pinheiros","Vila Madalena"],
 "preco_max":2000000,"quartos_min":3,"vagas_min":2,"area_min":120,
 "objetivo":"moradia","financiamento":true}
```

Item que o Property Agent devolve:

```json
{"property_id":"SP1008","preco":1695000,"area":126,"quartos":3,"vagas":3,
 "localizacao":"Rua Harmonia, 688, Vila Madalena","seller_agent":"AGT908",
 "disponibilidade":"available","documentacao_status":"basic_verified",
 "motivo":"cabe no teto, documentação limpa e 3 vagas"}
```

## Fluxo 2, negociar e pagar

```
COMPRADOR diz "quero fazer oferta" e dá um TETO (é a última vez que ele age)
  -> Orchestrator contrata quem negocia pelo comprador e acha o Seller Agent do imóvel
  -> NEGOCIAÇÃO A2A por LLM, até 4 rodadas: oferta, contraproposta, aceite
  -> Orchestrator confere por código se o acordo cabe no mandato
  -> contrata "conduzir_transacao" (2 concorrentes): KYC, contrato e condições precedentes
  -> confere por código quantas condições obrigatórias ficaram atendidas, paga proporcional
  -> contrata "custodia_pagamento" (2 concorrentes): reserva em escrow
  -> confere TODAS as condições obrigatórias por código antes de mandar liberar
  -> PAYMENT_RELEASED -> PROPERTY_TRANSFERRED -> COMPLETED
```

## Máquina de estados

```
SEARCH -> SHORTLIST -> PROPERTY_SELECTED -> OFFER_CREATED -> OFFER_SENT ->
COUNTER_OFFER -> OFFER_ACCEPTED -> KYC_PENDING -> DOCUMENTS_VERIFIED ->
CONTRACT_SIGNED -> FUNDS_LOCKED -> CONDITIONS_MET -> PAYMENT_RELEASED ->
PROPERTY_TRANSFERRED -> COMPLETED
```

Saídas de falha: `OFFER_REJECTED` (volta para a shortlist, o comprador escolhe outro) e
`ABORTED` (sempre com o motivo no evento). A tabela de transições válidas está em
`nucleo/estados.py` e transição inválida levanta erro: estado que aparece fora de ordem
seria um defeito escondido.

Duas regras que a máquina garante: `FUNDS_LOCKED` nunca vai direto para
`PAYMENT_RELEASED` (passa por `CONDITIONS_MET`), e `PROPERTY_TRANSFERRED` não tem saída
de falha, porque depois que o imóvel mudou de dono não existe desistir, existe desfazer.

## Ficha do agente (Agent Card do A2A)

`GET {url_do_agente}/.well-known/agent-card.json`

```json
{
  "agente_id": "property-busca-relampago",
  "name": "Busca Relâmpago",
  "description": "Busca imóveis rápido e barato. ESTRATÉGIA DECLARADA: trabalha só com o texto do anúncio.",
  "url": "http://127.0.0.1:8787/agentes/property-busca-relampago",
  "papel": "property",
  "preco_usd": 0.35,
  "estrategia": "Velocidade e preço acima de conferência.",
  "acesso_a_dados": "somente o anuncio (sem disponibilidade, sem documentos)",
  "capacidade_neuralake": "auto",
  "skills": [{"id": "buscar_imoveis", "description": "...",
              "entrada": {"pedido": "..."}, "saida": {"itens": "..."}}]
}
```

Campos que mudam comportamento e por isso são **declarados**: `estrategia`,
`acesso_a_dados`, `confere_documentos`, `escrow`, `simulado`, `preco_usd`.

## Contrato HTTP

Tudo num processo, porta 8787, cada agente com URL própria. Os agentes falam **entre si
por HTTP** mesmo no mesmo processo: mover um deles de máquina muda a URL na ficha, não o
código.

**Registry** (a única URL que o Orchestrator conhece)

| Método | Rota | Devolve |
|---|---|---|
| POST | `/registry/agentes` | cadastra uma ficha; agente novo entra sozinho |
| GET | `/registry/agentes?capacidade=X` | fichas de quem faz X + `historico` |
| GET | `/registry/agentes?capacidade=X&property_id=Y` | o Seller Agent de um imóvel |
| GET | `/registry/agentes/{id}` | uma ficha com histórico |
| POST | `/registry/recibos` | publica o resultado verificado de uma entrega |
| GET | `/registry/recibos?agente_id=` | os recibos |

`historico` é `{entregas, itens_pedidos, itens_provados, taxa_aprovacao, pago_usd,
retido_usd}`. Não é nota nem estrela: é a soma dos recibos. Quem nunca entregou tem
`taxa_aprovacao: null`, que é diferente de zero.

**Agente contratado**

| Método | Rota | Corpo | Devolve |
|---|---|---|---|
| GET | `/agentes/{slug}/.well-known/agent-card.json` | - | a ficha |
| POST | `/agentes/{slug}/tarefas` | `{skill, entrada, criterios_de_aceite, orcamento_usd, rodada_id}` | `{agente_id, agente_nome, skill, saida, custo_usd, simulado}` |

**Orchestrator** (é o que a tela chama; o humano só toca nas três primeiras)

| Método | Rota | Para que |
|---|---|---|
| POST | `/orchestrator/rodadas` | `{frase}` começa a rodada. **Humano 1** |
| POST | `/orchestrator/rodadas/{id}/escolha` | `{property_id}`. **Humano 2** |
| POST | `/orchestrator/rodadas/{id}/oferta` | `{teto_preco, prazo_dias}`. **Humano 3** |
| GET | `/orchestrator/rodadas/{id}` | estado, shortlist, negociação, escrow, placar |
| GET | `/orchestrator/eventos?since=N&rodada_id=` | a linha do tempo |
| GET | `/orchestrator/carteiras` | custo de inferência e honorário por agente |
| GET | `/orchestrator/reprises` | gravações disponíveis |
| POST | `/orchestrator/reprises` | `{arquivo, velocidade}` abre uma reprise |
| GET | `/orchestrator/reprises/{sessao}/eventos?since=N` | eventos da reprise |

Evento: `{seq, ts, estado, tipo, de, para, motivo, custo_usd, dados}`, com `tipo` em
`humano | decisao | repasse | verificacao | chamada | estado | falha`. O placar conta
esses tipos.

## Verificação por conta de código (nunca nota de LLM)

`nucleo/verificacao.py`. Custa zero token e é o que sustenta o pagamento.

| O que | Como o Orchestrator confere |
|---|---|
| imóvel devolvido | existe na base e preço, área, quartos e vagas batem com a base |
| filtros do pedido | teto, mínimos, bairro, tipo e financiamento |
| disponibilidade | a afirmada bate com a da base (o anúncio não diz que está reservado) |
| documentação | o status afirmado bate com o que o texto do documento diz |
| preço | comparado com a mediana de R$/m2 do bairro na base |
| acordo | preço final dentro do teto do mandato, e nenhuma jogada acima do teto |
| condições precedentes | todas as obrigatórias daquela fase marcadas antes de liberar |

Regras de documento, todas legíveis no próprio arquivo: averbação de ônus com
`Situação: ATIVA` é pendência (`CANCELADA` não é), `Validade até` anterior a hoje é
pendência, certidão precisa dizer `NADA CONSTA` e condomínio precisa dizer `ADIMPLENTE`.

**Pagamento**: `pago = preço × itens provados ÷ itens pedidos`. O resto fica retido e
aparece na tela. Todo recibo, bom ou ruim, é publicado no Registry e vira histórico.

## O que é SIMULADO (dizer isto no palco)

- **KYC, contrato, escritura, ITBI e registro**: carimbo, não ato jurídico. Nenhum LLM
  redige contrato neste projeto, por decisão do time: contrato escrito por modelo não é
  valor de negócio, é risco.
- **Escrow**: razão em sqlite, lançamento a lançamento. Nenhum dinheiro se move, não há
  banco, não há blockchain.
- **Honorário dos agentes** (os US$ 0,30 a US$ 1,20): moeda de brincadeira.
- **A base de imóveis, os documentos e os vendedores**: inventados. Ver `dados/LEIAME.md`.

**O que é REAL**: as chamadas à NeuraLake, o `usage.estimated_cost` de cada uma (é ele
que debita a carteira de inferência), as decisões do modelo e a verificação por código.

## Motor de agentes: Agno

`agno` 3.0.10 com `OpenAILike(id="auto", base_url="https://api.neuralake.cloud/v1")`.

- **Um `Agent` por papel**, com as instruções montadas a partir da própria ficha e saída
  estruturada (`output_schema` Pydantic + `use_json_mode=True`). Os esquemas estão em
  `agentes/esquemas.py`.
- **O estado da rodada mora no `session_state` de um `Workflow`**, persistido pelo
  `SqliteDb` do Agno (`neura-agno.db`). Uma rodada sobrevive a reinício do servidor.
- **Sem tool calling no caminho crítico.** Medido: `auto` roteia para `text`, e `text`
  falha no turno `role:"tool"`. A orquestração é passo de Python chamando cada agente.
- **Duas coisas o Agno não entrega e a gente pega no cliente HTTP** (`nucleo/modelo.py`):
  o `usage.estimated_cost` (o `RunMetrics` vem com `cost=None`) e qual modelo a NeuraLake
  escolheu (o Agno repete o `auto` que mandamos). Um gancho de resposta no
  `httpx.AsyncClient` lê os dois do corpo cru. O gancho não olha cabeçalho.

Defesas que sobreviveram ao porte, agora em volta do Agno: timeout de 25 s, uma repetição
em corpo vazio, plano B em `text` quando `auto` não cola (com o motivo no evento),
remoção de `<think>` e extrator tolerante de JSON como rede de segurança.

## Autonomia: quem decide o quê

O humano age **três vezes**: escreve a frase, escolhe um imóvel, autoriza a oferta com um
teto. Não existe botão de aprovar no meio.

O Orchestrator decide sozinho: qual agente contratar em cada capacidade, com que
orçamento e critérios de aceite, se a entrega passou, quanto pagar, se retém, se publica
recibo ruim e se contrata o concorrente.

**Política de compra declarada** (aparece na tela em toda decisão em que vale): sem
histórico verificado no marketplace, começar pelo mais barato e verificar; havendo
histórico, a taxa de aprovação pesa mais que o preço. A escolha continua sendo do modelo:
em 6 rodadas medidas ele contrariou a política e foi direto no agente caro, porque os
critérios de aceite exigiam conferência de documento, e disse isso no motivo. Isso está
registrado como achado, não como defeito.

## Duas travas de mandato (e por que não são "código forçando resultado")

O Buyer Agent nunca emite valor acima do teto que o comprador deu, e nunca oferece menos
do que já ofereceu. O Seller Agent nunca fecha abaixo do piso do proprietário. As duas
são o limite que o cliente de cada agente deu, estão declaradas na ficha e aparecem no
motivo da jogada quando entram em ação. A decisão de aceitar, contrapropor ou desistir
continua inteira do modelo.

## Pastas

| Pasta | O que é | Dono |
|---|---|---|
| `orchestrator/` | o laço: descobre, avalia, contrata, delega, verifica | a definir |
| `registry/` | o marketplace: fichas, busca por capacidade, recibos | a definir |
| `agentes/` | os 8 papéis, com ficha e URL próprias | a definir |
| `nucleo/` | modelo, banco, estados, verificação, reprise | a definir |
| `tela/` | HTML, CSS e JS puros, sem build | a definir |
| `dados/` | base, documentos, critérios, gravação de exemplo | a definir |
| `tests/` | 77 testes, todos sem rede | a definir |

Cada pasta tem um `LEIAME.md` com as regras dela. O contrato entre pastas é o HTTP acima.

## Regras duras

1. **A chave só existe em `NEURALAKE_API_KEY` no ambiente** (ou num `.env` que está no
   `.gitignore`). Nunca em arquivo, log, evento, gravação, teste ou commit. Antes de cada
   commit: `git grep -n -i "nlk-"` e `git diff --cached | grep -i "bearer "`, os dois
   vazios. O repositório é público.
2. **Nenhum código força o resultado de um agente.** Agente diferente é ficha e instrução
   diferentes. Quem descobre o erro é a verificação por código, depois.
3. **Aceite de entrega é conta de código**, nunca nota de LLM.
4. **Reprise nunca se passa por ao vivo**: faixa no alto com a data da gravação, e ela
   não escreve no banco nem toca em carteira.
5. **Dizer no palco o que veio pronto antes do evento** (o cliente da NeuraLake e a
   conferência de citação vêm do projeto Aval, do mesmo dono) **e o que é simulado**.
6. **Dado dinâmico na tela só por `textContent`**, e `[hidden]{display:none !important}`
   é a primeira regra do CSS.

## Em aberto

1. A lista de condições precedentes é rascunho de quem não é especialista. Quem domina
   compra e venda de imóvel no Brasil precisa corrigir `dados/criterios-fechamento.json`.
2. A troca de contratado acontece em 3 de 6 rodadas medidas, e por causa de reprovação
   parcial da busca, não porque o Orchestrator escolheu mal. Se o time quiser a história
   "escolheu o barato e se queimou", o ajuste honesto é orçamento por subtarefa, e tem
   que ser declarado na tela.
3. A negociação fecha sempre em 2 rodadas nas medições. Falta um cenário com vendedor sem
   pressa e piso alto para mostrar rodada 4 e `OFFER_REJECTED`.
4. Não há teste de ponta a ponta com a API real dentro da suíte (custa dinheiro e demora).
   O que existe é o roteiro manual do README.
5. Um segundo cenário (aluguel, ou comprador investidor) não existe.
