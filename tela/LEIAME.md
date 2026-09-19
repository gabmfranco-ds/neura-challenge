# tela

Dono: a definir.

HTML, CSS e JS puros. Sem build, sem framework, sem CDN. Servida pelo próprio FastAPI em
`http://127.0.0.1:8787`.

| Arquivo | O que é |
|---|---|
| `index.html` | a estrutura: trilho no alto, três colunas, rodapé |
| `estilo.css` | escuro, feito para telão |
| `app.js` | polling de eventos e desenho |

## O que o júri vê

- **alto**: a máquina de estados como trilho, com o estado atual aceso;
- **esquerda**: a conversa do comprador (frase, shortlist com motivo, escolha, teto da
  oferta) e a negociação entre agentes;
- **centro**: a linha do tempo agente para agente, com o motivo de cada decisão;
- **direita**: placar de autonomia, carteiras, escrow e recibos;
- **rodapé**: custo total em dólar, contador de chamadas em `auto` e o interruptor
  ao vivo ou reprise.

## Três regras duras

1. **`[hidden] { display: none !important; }` é a PRIMEIRA regra do CSS.** Classe com
   `display:flex` anulando `hidden` já quebrou tela antes. Não tire daí.
2. **Dado dinâmico entra por `textContent`.** Nada de `innerHTML`: o texto vem de modelo
   de linguagem e de documento, e não é confiável.
3. **Reprise nunca se passa por ao vivo.** Enquanto o modo for reprise, a faixa roxa fica
   no alto com a data da gravação. Ela não some com o scroll.

## Como a tela conversa com o resto

Só com `/orchestrator/*`. Ela não conhece agente nem Registry. Polling de 1 segundo em
`/orchestrator/eventos?since=N&rodada_id=...`, mais o estado da rodada e as carteiras.
