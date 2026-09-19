# orchestrator

Dono: a definir. (Esta pasta era `consultor/` no esqueleto.)

O laço que faz o desafio pontuar: **descobre, avalia, contrata, delega e verifica**, sem
humano no meio.

| Arquivo | O que faz |
|---|---|
| `motor.py` | o laço inteiro, os dois fluxos e a contabilidade dos recibos |
| `rotas.py` | as rotas HTTP que a tela chama |
| `memoria.py` | memória de buscas já verificadas (segundo comprador sai mais barato) |

## Regras que não se quebram aqui

1. **Não existe nome de agente neste código.** Quem precisa de trabalho pergunta ao
   Registry por CAPACIDADE (`buscar_imoveis`, `conduzir_transacao` e as outras). Se
   aparecer `if agente == "Casa Verificada"`, o desafio já foi perdido.
2. **Aceite de entrega é conta de código**, em `nucleo/verificacao.py`. Nota de LLM não
   aprova nada e não libera pagamento.
3. **O humano age em três momentos**: a frase, a escolha do imóvel, o teto da oferta.
   Nenhum botão de aprovar no meio. Se você precisar de um, o desenho está errado.
4. **Todo evento leva motivo em português simples.** É o que o júri lê na tela.

## Como uma contratação acontece

```
_descobrir(capacidade)        GET  /registry/agentes?capacidade=...
_avaliar_e_contratar(...)     1 chamada ao modelo com ficha + histórico + preço
_delegar(card, skill, ...)    POST {url_do_agente}/tarefas
verificacao.conferir_*(...)   conta de código, zero token
_pagar(...)                   pago = preco x provados / pedidos, recibo no Registry
```

Reprovou? O laço volta ao começo com o concorrente e diz por quê. É o `while` em
`_buscar_com_marketplace` e o bloco de substituto em `_transacionar` e `_pagar_imovel`.

## Onde mexer

- capacidade da NeuraLake do Orchestrator: `NEURA_CAP_ORCHESTRATOR` (padrão `auto`);
- tamanho da shortlist: `ALVO_SHORTLIST` e `MINIMO_SHORTLIST`;
- rodadas de negociação: `MAX_RODADAS_NEGOCIACAO`.
