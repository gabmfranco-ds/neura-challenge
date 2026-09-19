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

## Estado real em 19/09, depois da branch `v1`

**Tudo abaixo saiu de rodada real contra a API, não de expectativa.**

| | antes do Agno | depois do Agno |
|---|---|---|
| rodadas medidas | 6 | 8 |
| chegaram a SHORTLIST | 6 de 6 | 8 de 8 |
| chegaram a COMPLETED | 6 de 6 | 4 de 8 (as outras 4 em `OFFER_REJECTED`) |
| tempo da frase à shortlist | 12,9 a 25,2 s | 5,1 a 25,1 s |
| tempo da rodada inteira | 32,4 s em média | 37,6 s em média (completas) |
| custo de inferência por rodada | US$ 0,0015 | US$ 0,0015 |
| chamadas em `auto` | 48 de 48 | 77 de 77 |
| plano B (queda para `text`) | 0 | 0 |

A queda de COMPLETED **não é regressão**: é a regra nova de negociação funcionando. Antes,
acordo fora da faixa do vendedor virava contrato; agora não vira. Quatro dessas rodadas
terminaram em `OFFER_REJECTED` porque o vendedor tem piso acima do que o comprador
autorizou, que é o comportamento certo.

**Troca de contratado: 3 em 8 rodadas** (mesma frequência antes e depois). Ela acontece na
busca, quando a verificação reprova parte da entrega e o Orchestrator contrata o
concorrente para completar a shortlist. **O que NÃO acontece:** o Orchestrator escolher o
agente barato primeiro. A política declarada "sem histórico verificado, comece pelo mais
barato e verifique" está no prompt e aparece na tela, e mesmo assim ele escolheu o
`Casa Verificada` em 8 de 8, dizendo no motivo que os critérios de aceite exigem
conferência de documento. O modelo está certo, e isso foi registrado como achado, não
corrigido à força.

**Negociação, nas 8 rodadas:** primeira oferta igual à `oferta_min` em 8 de 8; acordo
sempre na rodada 3 (a última); 4 violações de regra cometidas pelos modelos, todas
descartadas com repetição, 5 descartes no total.

**Memória:** o segundo comprador com pedido parecido pula a busca inteira. Medido: 5,1 s em
vez de 20,4 s, e a rodada sai cerca de 40% mais barata.

## Furos conhecidos (em ordem de importância para a nota)

1. **O acordo sempre sai na rodada 3**, que é a última. Com o limite em 3 e o comprador
   abrindo no mínimo, não sobra espaço para fechar antes. Se o júri contar rodadas, isso
   parece sorte, não estratégia.
2. **Metade das rodadas termina sem acordo.** É honesto (o piso do vendedor está acima da
   faixa autorizada), mas para a demo ao vivo convém escolher um imóvel com vendedor
   apressado. Os pisos estão em `dados/imoveis.json`, em `_privado_vendedor`.
3. **A troca de contratado nunca vem de escolha ruim**, só de reprovação parcial. Ver
   acima.
4. As condições de fechamento em `dados/criterios-fechamento.json` são uma lista inicial.
   Quem domina o assunto precisa corrigir.
5. Pitch de 4 minutos ainda não escrito.
6. Não há teste de ponta a ponta com a API real dentro da suíte: os 102 testes rodam sem
   rede, e a prova ao vivo é manual.

## O que mudou no contrato HTTP (o banco de avaliações precisa saber)

`GET /.well-known/agent-card.json` e `POST /tarefas` **não mudaram de forma**. O que mudou:

- `POST /orchestrator/rodadas/{id}/oferta` agora recebe
  `{"oferta_min": 1740000, "teto_preco": 1930000, "prazo_dias": 60}`. `oferta_min` é
  opcional: faltando, o Orchestrator assume 90% do teto e registra a suposição no evento.
  Mandar `oferta_min` maior que `teto_preco` devolve 400.
- `POST /orchestrator/rodadas/{id}/escolha` agora também aceita ser chamado quando a rodada
  está em `OFFER_REJECTED`: o comprador escolhe outro imóvel da mesma shortlist e a
  negociação recomeça.
- A entrada da skill `negociar_compra` ganhou `mandato.oferta_min`, `rodada`, `max_rodadas`
  e `correcao` (o motivo pelo qual a jogada anterior foi descartada). A de `negociar_venda`
  ganhou `rodada`, `max_rodadas` e `correcao`. Nenhum campo antigo saiu.
- Fichas ganharam campos declarados novos: `confere_documentos` (transaction) e
  `acesso_a_dados` (property).

## Agno: o que ele faz e o que ele não faz

Portado e no ar (`agno` 3.0.10). Um `Agent` por papel com `output_schema` Pydantic e
`use_json_mode`; o estado da rodada no `session_state` de um `Workflow`, persistido em
`neura-agno.db` pelo `SqliteDb` do Agno.

**Duas coisas o Agno não entrega** e um gancho no `httpx.AsyncClient` pega do corpo cru
(`nucleo/modelo.py`): o `usage.estimated_cost` (o `RunMetrics` vem com `cost=None`) e qual
modelo a NeuraLake escolheu (o Agno repete o `auto` que mandamos). Sem esse gancho não
existe carteira em dólar real nem o contador de roteamento na tela.

**Sem tool calling no caminho crítico**, medido: `auto` roteia para `text` e `text` falha no
turno `role:"tool"`.

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
