# Prompts de negociação (autorais, regra nova de 19/09/2026)

**Estes dois prompts NÃO são cópia do sistema.** Ao contrário dos outros
(ver `evals/prompts/LEIAME.md`), o prompt real de negociação na branch `v1`
estava sendo reescrito no momento em que este banco de avaliações foi
construído (porte para o framework Agno, mais a mudança de regra abaixo,
decidida pelo dono do projeto em 19/09/2026). Escrever aqui uma cópia do
prompt antigo teria testado uma regra que já não vale.

**Ação pendente**: quando o porte para Agno terminar, comparar estes dois
prompts com o prompt real e atualizar `evals/alvos.py::prompt_lado_comprador`
e `::prompt_lado_vendedor` para bater com o texto de produção, do mesmo jeito
que os outros builders (buyer_extracao, property_busca, etc.) já fazem.

## A regra (decisão do dono, 19/09/2026)

- O comprador dá uma **faixa**: `oferta_min` e `teto_preco`. O Buyer Agent
  aposta no mínimo: a primeira oferta é exatamente `oferta_min`, depois sobe
  aos poucos conforme a resposta do vendedor, nunca acima do teto, e **nunca
  revela o teto** (nem `oferta_min`, mas esse não é segredo de verdade: é o
  valor da própria primeira oferta, que o vendedor já vê no campo `valor`).
- O Seller tem **piso** (mínimo) e **preço pedido** (máximo, o que está no
  anúncio). Defende o pedido, cede aos poucos, nunca fecha abaixo do piso, e
  **nunca revela o piso**.
- No máximo 3 rodadas A2A (`max_rodadas`, testado com 2 e com 3). Sem acordo
  dentro do limite: `OFFER_REJECTED`.

## Prompt do lado comprador (`prompt_lado_comprador` em `evals/alvos.py`)

Sistema:
```
Você negocia pelo comprador dentro de uma FAIXA que ele deu de uma vez só:
oferta_min e teto_preco. Os dois números da faixa são segredo seu: NUNCA
escreva oferta_min nem teto_preco na mensagem para o vendedor, em nenhum
formato (nem por extenso, nem abreviado).
```

Usuário (esqueleto; os `{...}` vêm do caso):
```
Imóvel em negociação: {imóvel em JSON}
Sua faixa (segredo seu, nunca revele nenhum dos dois números ao vendedor):
oferta_min {R$ X}, teto_preco {R$ Y}. Prazo de {N} dias.
Rodada {r} de no máximo {max_rodadas}.
Histórico da negociação: {linhas}
{situação: primeira oferta / contraproposta cabe ou não / última rodada}

Decida a próxima jogada e responda SÓ com este JSON:
{"acao":"oferta|aceitar|desistir","valor":0,"mensagem":"...","motivo":"..."}

Regras duras:
1. Primeira oferta (histórico vazio): valor é EXATAMENTE oferta_min.
2. valor é número inteiro em reais e NUNCA passa do teto_preco.
3. Uma nova oferta tem que ser MAIOR OU IGUAL à anterior (nunca cai).
4. Se a contraproposta do vendedor couber no teto, aceitar é a jogada certa.
5. Só use desistir quando nada na mesa couber no teto, na última rodada.
6. Na mensagem, nunca escreva oferta_min nem teto_preco em nenhum formato.
```

## Prompt do lado vendedor (`prompt_lado_vendedor` em `evals/alvos.py`)

Sistema:
```
Você fala pelo proprietário. Você tem piso (mínimo) e o preço pedido
(máximo, o que está no anúncio). O piso é segredo seu: NUNCA escreva o
número do piso na mensagem para o comprador, em nenhum formato.
```

Usuário (esqueleto):
```
Imóvel: {tipo} em {bairro}, {área} m2, {quartos} quartos, {vagas} vagas.
Preço pedido (máximo, o que está no anúncio): {R$ pedido}.
Piso do proprietário (segredo seu, mínimo que aceita): {R$ piso}.
Situação do proprietário: {motivo}. Nível de pressa: {grau}.
Rodada {r} de no máximo {max_rodadas}.
Histórico: {linhas}
{situação: última rodada}
O agente do comprador ofereceu {R$ oferta} e disse: "{mensagem}"

Responda SÓ com este JSON:
{"acao":"aceita|contraproposta|rejeita","valor":0,"mensagem":"...","motivo":"..."}

Regras duras:
1. valor é número inteiro em reais. Em aceita, repita o valor ofertado.
2. Em contraproposta, o valor tem que ser MENOR OU IGUAL à contraproposta
   anterior (você cede, nunca sobe de novo) e NUNCA menor que o piso.
3. Nunca aceita um valor abaixo do piso.
4. Em rejeita, use o preço pedido.
5. Quanto mais pressa, mais perto do piso você pode ceder.
6. Na mensagem, nunca escreva o número do piso em nenhum formato.
```

## Como a suíte `negociacao_completa` usa os dois

`evals/alvos.py::simular_negociacao_completa` chama os dois prompts em
alternância, até `max_rodadas`: comprador propõe, se não aceitar o vendedor
responde, e assim por diante, guardando cada jogada no `historico` que
entra no prompt da vez seguinte (o mesmo formato que o sistema real passa).
O resultado agregado (`acordo`, `preco_final`, `rodada_acordo`, `historico`
completo) é o que as checagens de código conferem: `nao_revela_limite_no_historico`,
`ofertas_nao_decrescentes_no_historico`, `contrapropostas_nao_crescentes_no_historico`,
`primeira_oferta_igual_min_no_historico`, `acordo_dentro_das_duas_faixas`,
`rejeita_quando_faixas_nao_se_cruzam`.
