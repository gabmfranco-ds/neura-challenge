# Neura Challenge · Agent Marketplace de imóveis

Um comprador escreve uma frase e escolhe um imóvel. Todo o resto, achar quem faz o
trabalho, contratar, negociar preço com o vendedor, conferir documento e liberar
pagamento, é agente conversando com agente. Cada entrega só é paga na parte que o código
conseguiu provar.

Spec completa: [SPEC.md](SPEC.md) · Guia da API: [docs/neuralake-api.md](docs/neuralake-api.md)

## Rodar em 4 passos

```bash
# 1. a chave da NeuraLake, só no ambiente (o .env está no .gitignore)
export NEURALAKE_API_KEY="sua-chave"        # Windows: $env:NEURALAKE_API_KEY = "sua-chave"

# 2. um comando sobe tudo (cria a venv e instala o que faltar)
./run.sh                                     # Windows: .\run.ps1

# 3. abra a tela
#    http://127.0.0.1:8787

# 4. na tela: escreva a frase, clique em Procurar imóveis, escolha um imóvel da
#    shortlist e autorize a oferta com um teto. Depois disso é só assistir.
```

Se preferir a chave num arquivo, crie `.env` na raiz com `NEURALAKE_API_KEY=sua-chave`.
O `run.sh` e o `run.ps1` leem de lá. Sem a chave, os dois param com uma mensagem clara.

## O que você vai ver

- **no alto**: os 15 estados da compra, com o atual aceso;
- **esquerda**: a conversa do comprador, a shortlist com o motivo de cada imóvel e a
  negociação entre o agente do comprador e o agente do vendedor;
- **centro**: a linha do tempo agente para agente, com o motivo de cada decisão;
- **direita**: placar de autonomia, carteiras em dólar, razão do escrow e os recibos;
- **rodapé**: custo total da rodada, contador de chamadas em `auto` e o interruptor
  ao vivo ou reprise.

O humano age três vezes e só: a frase, a escolha do imóvel, o teto da oferta. Não existe
botão de aprovar no meio.

## Números de rodada real (19/09, 6 rodadas seguidas)

| | |
|---|---|
| chegaram a SHORTLIST | 6 de 6 |
| chegaram a COMPLETED | 6 de 6 |
| tempo médio da rodada inteira | 32,4 s |
| custo médio de inferência | US$ 0,0015 |
| chamadas em `auto` | 48 de 48 |
| segundo comprador (memória) | busca em 5,4 s em vez de 25,2 s, rodada 57% mais barata |

## Testes

```bash
.venv/Scripts/python -m pytest tests -q      # 77 testes, nenhum toca a rede
```

A suíte roda sem chave e sem internet. O que precisa de modelo usa dublê.

## Reserva para o palco

Se a rede cair na hora da demo, use o interruptor **Reprise** no rodapé: ele toca uma
rodada real gravada, com faixa roxa permanente dizendo que é reprise e a data. A reprise
não escreve no banco e não mexe em carteira. Já vem uma gravação de exemplo em
`dados/reprise-exemplo/`.

## Pastas

| Pasta | O que é | Dono |
|---|---|---|
| `orchestrator/` | descobre, avalia, contrata, delega, verifica | a definir |
| `registry/` | o marketplace de fichas e recibos | a definir |
| `agentes/` | os 8 papéis, cada um com ficha e URL | a definir |
| `nucleo/` | modelo, banco, estados, verificação, reprise | a definir |
| `tela/` | HTML, CSS e JS puros | a definir |
| `dados/` | base inventada, documentos, critérios | a definir |
| `tests/` | a suíte sem rede | a definir |

Cada uma tem um `LEIAME.md` com as regras. Leia o da sua antes de escrever.

## Regras duras

- **A chave só vive em `NEURALAKE_API_KEY`.** Nunca em arquivo, log, gravação ou commit.
  O repositório é público. Antes de commitar: `git grep -n -i "nlk-"` vazio.
- **Nenhum código força o resultado de um agente.** Agente diferente é ficha diferente.
- **Aceite de entrega é conta de código**, nunca nota de LLM.
- **Reprise nunca se passa por ao vivo.**
- **KYC, contrato, escritura e escrow são SIMULADOS**, e a tela diz isso.
- **Dizer no palco o que veio pronto antes do evento**: o cliente da NeuraLake com as
  defesas e a conferência de citação vieram do projeto Aval, do mesmo dono.
