# Contexto para quem chega agora

> Atualizado em 19/09/2026, fim da tarde. Leia isto antes de abrir o código.
> Entrega: domingo 20/09 às 11h. Código congela domingo às 9h.

## O projeto em uma frase

Um comprador de imóvel escreve uma frase. Agentes descobrem, avaliam, contratam, delegam e
verificam outros agentes num marketplace, negociam com o vendedor e fecham a compra, sem
nenhum humano escolher quem faz o quê.

Desafio 02 (Agent Marketplace) do hackathon NeuraLake "The Agent Economy".

## Como a nota é dada (toda decisão passa por aqui)

| Peso | Critério | O que fazemos para pontuar |
|---|---|---|
| 30% | Autonomia entre agentes (e desempate) | Placar na tela: decisões sem humano, repasses, intervenções humanas. Humano age em 3 momentos só |
| 25% | Demo ao vivo | Fluxo inteiro roda em cerca de 35 s. Reprise gravada como reserva, sempre rotulada |
| 15% | Valor por token | `model="auto"` em todas as chamadas (mentor: altamente desejável). Custo real na tela. Verificação por código gasta zero token |
| 15% | Valor de negócio | Condições brasileiras de fechamento conferidas antes de liberar pagamento |
| 10% | Pitch de 4 min | Problema, demo, o que viria depois |
| 5% | Confiança | Motivo de cada decisão em linguagem simples, recibo de cada verificação |

Resposta do mentor da NeuraLake: `auto` é altamente desejável. Cross Memory não é o caminho,
não citamos.

## Onde está cada coisa

| Branch | O que tem | Estado |
|---|---|---|
| `main` | spec v0, este contexto, guia da API | estável |
| `v1` | sistema funcionando de ponta a ponta (commit `7614359` é o ponto de retorno) | em evolução: porte para Agno e regra nova de negociação |
| `evals` | banco de avaliações contra a API real | em construção |

Ponto de retorno medido (commit `7614359`, API real, 19/09): da frase à shortlist em 22 s, da
oferta a `COMPLETED` em cerca de 10 s, custo de inferência US$ 0,0018, 8 de 8 chamadas em
`auto` (a NeuraLake roteou todas para `text`), 12 decisões sem humano, 25 repasses, 3
intervenções humanas, 8 verificações por código.

## Como rodar a v1

```
git fetch && git checkout v1
# ponha a chave em NEURALAKE_API_KEY (ambiente) ou num arquivo .env na raiz
./run.sh        # ou .\run.ps1 no Windows
# abrir http://127.0.0.1:8787
```

A chave nunca entra no git. `.env` está no `.gitignore`.

## Desenho (decidido pelo time)

```
COMPRADOR → Buyer Agent → Orchestrator → Registry (descobre por capacidade)
   → Property Agents (2 concorrentes) → Seller Agents → shortlist → COMPRADOR ESCOLHE
   → oferta com faixa → negociação Buyer x Seller → Transaction Agent → Payment Agent → concluído
```

Estados: `SEARCH → SHORTLIST → PROPERTY_SELECTED → OFFER_CREATED → OFFER_SENT → COUNTER_OFFER →
OFFER_ACCEPTED → KYC_PENDING → DOCUMENTS_VERIFIED → CONTRACT_SIGNED → FUNDS_LOCKED →
CONDITIONS_MET → PAYMENT_RELEASED → PROPERTY_TRANSFERRED → COMPLETED`, mais `OFFER_REJECTED`.

## Decisões travadas

1. **Registry com ficha no formato A2A.** Cada agente é um serviço HTTP com
   `GET /.well-known/agent-card.json` e `POST /tarefas`. O Orchestrator só conhece a URL do
   Registry e descobre por capacidade, nunca por nome.
2. **Dois concorrentes por capacidade**, com preço e estratégia declarada diferentes. O
   Orchestrator escolhe sozinho e grava o motivo.
3. **Verificação por conta de código, nunca nota de LLM.** Filtros do pedido, mediana do
   bairro, documentos, faixa da negociação, condições antes de liberar pagamento. Paga na
   proporção do que foi provado, o resto fica retido e visível.
4. **Humano age em 3 momentos:** escreve a frase, escolhe o imóvel, dá a faixa da oferta.
   Nenhum botão de aprovar no meio.
5. **Negociação (regra de 19/09):** comprador dá `oferta_min` e `teto_preco`; vendedor tem
   piso e preço pedido. O Buyer Agent abre no mínimo e sobe aos poucos. O Seller Agent
   defende o pedido e cede aos poucos. Ninguém revela o próprio limite. **No máximo 3
   rodadas.** Sem acordo: `OFFER_REJECTED` com o motivo, e o comprador pode escolher outro
   imóvel. Tudo conferido por código.
6. **Fechamento simulado e rotulado.** KYC, contrato, escrow e liberação são máquina de
   estados com regra de código. Nada de pagamento real nem blockchain.
7. **`auto` em tudo.** Outra capacidade só como plano B quando `auto` falhar, e isso fica
   registrado. A tela mostra "chamadas em auto: N de N".
8. **Agno para gestão de estado.** O negócio inteiro mora no `session_state` de um Workflow
   do Agno, persistido em sqlite. Atenção: `auto` cai em `text`, onde o turno de ferramenta
   falha, então o fluxo usa saída estruturada em JSON, sem tool calling no caminho crítico.
9. **Dados próprios, sem rede.** 30 imóveis inventados em São Paulo, com documentos de
   exemplo, alguns com defeito plantado e alguns com piso alto para a rejeição acontecer de
   verdade.
10. **Banco de avaliações.** Tokens liberados pela NeuraLake para o desafio. Casos em
    arquivo, resultados em sqlite, checagens sempre por código, relatório que compara duas
    execuções.

## Regras duras

- Chave da NeuraLake só em variável de ambiente. Nunca em arquivo, log, gravação ou git.
  O repositório é público.
- Nenhum código que force o resultado de um agente. Agente ruim é ficha e instrução
  diferentes; o comportamento sai do modelo.
- Reprise nunca se passa por ao vivo.
- No palco, dizer o que veio pronto antes do evento e o que é simulado.
- Agentes de IA trabalham em branch com pull request. Ninguém faz commit direto na `main`.

## Furos conhecidos (em ordem de importância para a nota)

1. **A troca de contratado quase não acontece.** Na rodada medida, o Orchestrator escolheu
   direto o agente bom nas 3 capacidades. É o momento que mais vale nos 30%. Caminho
   honesto: regra de negócio declarada, como "sem histórico verificado, começa pelo mais
   barato e verifica". Em medição.
2. A tela ainda não passou por olho humano.
3. As condições de fechamento em `dados/criterios-fechamento.json` são uma lista inicial.
   Quem domina o assunto precisa corrigir.
4. Pitch de 4 minutos ainda não escrito.

## Fatias de entrega

- **Fatia 1 (tem que rodar sempre):** da frase à shortlist, com escolha autônoma,
  verificação por código e troca de contratado.
- **Fatia 2:** negociação real em até 3 rodadas e fechamento simulado.
- **Fatia 3:** vamos vendo. Candidatos: segundo comprador mais barato por memória, defeito
  plantado tirando imóvel da shortlist, agente novo entrando sozinho no Registry.

Relógio: hoje até 23h, domingo das 7h às 9h, congela às 9h. Das 9h às 11h só reprise,
ensaio e entrega.

## Armadilhas da API da NeuraLake

Guia completo em `docs/neuralake-api.md`. As que mais mordem: `reasoning` vaza `<think>` no
texto e devolve corpo vazio com teto baixo; corpo vazio pode vir com `finish_reason=="stop"`
(a defesa é repetir a chamada); o turno `role:"tool"` falha em `text`; erro vem em 3
formatos (string, objeto, HTML); já houve surto de 504. `usage.estimated_cost` vem em toda
resposta, em dólar.
