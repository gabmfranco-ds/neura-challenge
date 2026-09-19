# Spec v0 · Agent Marketplace de imóveis

> Hackathon NeuraLake "The Agent Economy", desafio 02. Entrega domingo 20/09 às 11h.
> Rascunho para o grupo rasgar. O que está aqui saiu das decisões de 19/09; o que o grupo
> mudar no painel (https://painel-arquitetura.vercel.app) manda sobre este arquivo.

## A frase

Um comprador escreve uma frase. Um agente consultor acha o imóvel certo contratando outros
agentes num marketplace, sem nenhum humano escolher quem faz o quê, e só paga pelo que foi
provado.

## Régua (toda decisão passa por aqui)

| Peso | Critério | O que aparece NA TELA para ganhar o ponto |
|---|---|---|
| 30% | Autonomia entre agentes (e desempate) | Contador "decisões sem humano: N · repasses: N · humanas: 0" + motivo de cada decisão |
| 25% | Demo ao vivo | Fluxo inteiro rodando; reprise gravada como reserva, sempre rotulada |
| 15% | Valor por token | `model="auto"` em tudo; custo real por decisão; segundo comprador sai mais barato |
| 15% | Valor de negócio | Lista de fechamento com critérios brasileiros reais; marketplace ganha por entrega verificada |
| 10% | Pitch de 4 min | Problema, demo, o que viria depois. Um apresentador, 3 ensaios |
| 5% | Confiança | O mesmo registro de decisões, mais o recibo de cada verificação |

## Jornada

Humano age em 2 momentos. Todo o resto é agente com agente.

1. **Pede** (humano): "Quero um apartamento de 2 quartos na Vila Mariana, até R$ 800 mil,
   financiado, tenho R$ 200 mil de entrada."
2. **Entende**: o consultor extrai os critérios. O que falta ele assume e declara; só
   pergunta se for impossível buscar sem aquilo. Quebra em 4 subtarefas: buscar imóveis,
   checar documentação, simular financiamento, avaliar preço.
3. **Descobre**: pergunta ao marketplace quem atende cada capacidade. Nunca por nome.
4. **Avalia**: compara ao menos 2 candidatos por capacidade (ficha, histórico de entregas
   verificadas, preço). Sem histórico, paga um teste pequeno antes. Grava o motivo.
5. **Contrata e delega**: fecha com orçamento e critérios de aceite. Os 4 rodam em paralelo.
6. **Verifica**: confere cada entrega por conta de código. O agente barato de documentação
   falha, o consultor retém o pagamento, rebaixa o histórico dele e contrata o concorrente.
7. **Responde**: 3 imóveis ranqueados, o motivo de cada um, custo total (preço + ITBI +
   cartório) e o que falta para fechar.
8. **Fecha** (humano diz "quero o segundo"): o consultor contrata o agente de contrato, que
   devolve a lista de fechamento com cada critério brasileiro provado ou pendente.

Regras que seguram os 30%: o humano nunca vê nome de agente antes da escolha; nenhum botão
de aprovar no meio; a falha vem de um agente ruim de verdade no catálogo, nunca de código
forçado.

## Peças

| Peça | O que faz | Pasta | Dono |
|---|---|---|---|
| Consultor | Laço de decisão, carteira, registro de decisões, verificação | `consultor/` | pessoa 1 |
| Marketplace | Catálogo de fichas, busca por capacidade, histórico | `marketplace/` | pessoa 2 |
| Agentes do catálogo | Busca, documentação (caro e barato), financiamento, preço, contrato | `agentes/` | pessoa 2 |
| Tela | Conversa do comprador, linha do tempo das decisões, carteiras, placar | `tela/` | pessoa 3 |
| Dados e critérios | Base de imóveis, documentos, critérios de contrato, pitch | `dados/` | pessoa 4 |

Ninguém escreve na pasta do outro. O contrato entre as pastas é o HTTP abaixo e só muda
com aviso no painel.

Stack: Python, FastAPI, sqlite, httpx. Tela em HTML e JS puros, sem build. Um comando sobe
tudo. Cada agente tem URL própria; o consultor só conhece a URL do marketplace.

## Contrato HTTP (congelar na primeira hora)

**Ficha do agente** (formato do Agent Card do A2A), em
`GET {url_do_agente}/.well-known/agent-card.json`:

```json
{
  "name": "Doc Expresso",
  "description": "Checa documentação de imóvel. Estratégia declarada: lê só a matrícula.",
  "url": "http://127.0.0.1:8800/agentes/doc-expresso",
  "skills": [{"id": "checar_documentacao", "description": "...",
              "entrada": {"imovel_id": "str", "criterios": ["str"]},
              "saida": {"afirmacoes": [{"criterio": 1, "texto": "", "citacao": "", "documento": ""}]}}],
  "preco_usd": 0.40,
  "capacidade_neuralake": "auto"
}
```

**Marketplace**

| Método | Rota | Devolve |
|---|---|---|
| GET | `/marketplace/agentes?capacidade=checar_documentacao` | fichas + `historico: {entregas, criterios_provados, criterios_pedidos, custo_medio_usd}` |
| POST | `/marketplace/agentes` | cadastra ficha (agente novo entra sozinho) |
| POST | `/marketplace/recibos` | consultor publica o recibo de uma entrega verificada; vira histórico |

**Agente contratado**: `POST {url}/tarefas` com `{skill, entrada, criterios_de_aceite,
orcamento_usd}` devolve `{saida, custo_usd}`.

**Consultor**

| Método | Rota | Devolve |
|---|---|---|
| POST | `/consultor/objetivos` | `{objetivo_id}` a partir de `{frase}` |
| POST | `/consultor/objetivos/{id}/escolha` | segundo ato, `{imovel_id}` |
| GET | `/consultor/objetivos/{id}` | estado, resposta final, placar |
| GET | `/consultor/decisoes?since=N` | `[{seq, ts, passo, tipo: decisao|repasse, de, para, motivo, custo_usd}]` |
| GET | `/consultor/carteiras` | saldo de cada agente |
| POST | `/consultor/objetivos/{id}/reprise` | reproduz rodada real gravada, com rótulo |

`passo` usa os mesmos 8 nomes do painel: `pede, entende, descobre, avalia, contrata,
verifica, responde, fecha`.

## Verificação por conta de código (nunca nota de LLM)

| Entrega | Como o consultor confere |
|---|---|
| Busca de imóveis | cada imóvel existe na base e bate com os filtros pedidos |
| Financiamento | o código refaz a parcela (Price ou SAC) e compara com tolerância |
| Documentação | citação conferida no documento fonte (motor do Aval, pronto) |
| Avaliação de preço | compara com a mediana do bairro na base |
| Lista de fechamento | cada critério com citação conferida, ou marcado pendente |

Pagamento: `pago = preço × critérios provados ÷ critérios pedidos`. O resto fica retido e
visível. Todo recibo vai para o histórico do marketplace.

## Dinheiro e eficiência

- Carteira em dólar por agente, debitada pelo `usage.estimated_cost` que a NeuraLake
  devolve em toda resposta. Nada de moeda inventada.
- `model="auto"` como padrão, porque a régua cita. **Medido por nós em 19/09: `auto`
  roteou sempre para `text`, e não achamos rota de Cross Memory.** Perguntar a um mentor.
  Se não existir, o consultor guarda o que já buscou (memória própria) e o segundo
  comprador com pedido parecido sai mais barato; mostramos os dois custos lado a lado.
- Armadilhas conhecidas da API: `reasoning` vaza `<think>` no texto e devolve corpo vazio
  com teto baixo; turno `role:"tool"` falha em `text` e funciona em `code`; erro vem em 3
  formatos; houve surto de 504 em `reasoning`. Guia completo em `docs/neuralake-api.md`.

## Dados

Base própria, roda sem rede. Uns 30 imóveis realistas em 3 ou 4 bairros. Para pelo menos 6
deles, documentos de exemplo (matrícula, certidões, IPTU) escritos por quem domina o
assunto. Dois com defeito plantado no documento (ônus na matrícula, certidão vencida) para
o agente bom achar. Os critérios de contrato no Brasil viram `dados/criterios.json`, um
por item, com o documento onde cada um se prova.

## Tela (o que o júri vê)

Esquerda: conversa do comprador. Centro: linha do tempo das decisões, agente para agente,
com o motivo. Direita: carteiras e o placar "sem humano / repasses / humanas: 0". Rodapé:
custo total da rodada em dólar. Interruptor ao vivo ou reprise, com rótulo sempre visível.

## O que vem pronto do Aval (projeto anterior do Gabriel, entra sob demanda)

Cliente da NeuraLake com as defesas (`app/neuralake.py`), conferência de citação
(`app/verificador.py`), carteira e recibo com hash (`app/rotas.py`, `app/db.py`), gravação e
reprise, 46 testes sem rede. Medido lá: agente que não lê a fonte tirou 0 de 5 e recebeu
$0, de verdade, em 2 rodadas. É a base da falha da demo.

## Ordem de trabalho

1. 0 a 1 h: congelar o contrato HTTP acima e a ficha. Cada um sobe a sua pasta com
   respostas de mentira.
2. 1 a 3 h: fluxo inteiro rodando com agentes de mentira, feio.
3. 3 a 8 h: trocar por agentes reais, um por vez.
4. 8 a 11 h: falha com troca de contratado, placar, custo na tela, segundo ato.
5. Domingo 8h: código congelado. Gravar reprise, ensaiar 3 vezes com relógio.

## Fora do escopo

Portal real de imóveis. Pagamento de verdade ou blockchain. Segundo cenário. Login.
Trocar de ferramenta de agente no meio. Tela bonita antes de o fluxo rodar.

## Regras duras

- Chave da NeuraLake só em variável de ambiente `NEURALAKE_API_KEY`. Nunca em arquivo,
  log, gravação ou git.
- Nenhum atalho de código que force o resultado de um agente. Agente ruim é ficha e
  instrução diferentes, o comportamento sai do modelo.
- Reprise nunca se passa por ao vivo.
- Dizer no palco o que veio pronto antes do evento.

## Em aberto

1. Cross Memory existe? O que `auto` faz de verdade? (mentor)
2. Nome do projeto.
3. Quem é pessoa 1, 2, 3 e 4.
4. Lista real dos critérios de contrato (quem domina escreve no painel, coluna "Fecha").
