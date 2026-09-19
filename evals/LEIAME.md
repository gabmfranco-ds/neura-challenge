# Banco de avaliações do marketplace de imóveis (hackathon NeuraLake)

O que é: um banco sqlite consultável com o resultado de rodar os prompts e as
rotas HTTP reais do projeto (repo `neura-challenge`, branch `v1`) contra a
API real da NeuraLake, várias vezes, com checagem de qualidade sempre por
CÓDIGO (nunca nota de LLM). Serve para responder "o `model=auto` aguenta
cada tarefa do nosso fluxo, com que qualidade, custo e tempo?".

Este worktree (`neura-evals`, branch `evals`) é separado do worktree onde o
sistema está sendo construído (`neura-challenge`, branch `v1`). Só a pasta
`evals/` (e este `requirements-evals.txt`) pertence a este trabalho.

## Rodar em 3 comandos

```bash
cd neura-evals
python -m venv .venv && ./.venv/Scripts/pip install -r requirements-evals.txt   # 1. instala
export NEURALAKE_API_KEY="$(tr -d '\r\n' < /caminho/para/neuralake.txt)"        # 2. chave (só no shell, nunca em arquivo)
python -m evals.rodar --suite buyer_extracao --capacidade auto --repeticoes 5 --rotulo teste  # 3. roda
python -m evals.relatorio --execucao ultimo                                     # (opcional) gera o .md
```

`evals/rodar.py` sincroniza `evals/casos/*.jsonl` no banco sozinho antes de
rodar (não precisa chamar o carregador à parte). O banco fica em
`evals/evals.db`, criado na hora, e NÃO vai para o git (está no
`.gitignore` por `*.db`).

## Escrever um caso novo em 2 minutos

Abra o `.jsonl` da suíte (o nome do arquivo é o nome da suíte) e acrescente
uma linha JSON:

```json
{"nome": "meu_caso_novo", "alvo": "prompt", "entrada": {"frase": "..."},
 "checagens": [{"tipo": "json_valido"}, {"tipo": "igual", "campo": "pedido.tipo", "valor": "apartamento"}],
 "tags": ["minha_tag"]}
```

- `alvo`: `"prompt"` (chama a NeuraLake direto, prompt vem de `evals/alvos.py`)
  ou `"http"` (chama `POST {base}{rota}` do servidor do projeto; `entrada`
  precisa ter `rota` e `corpo`).
- `checagens`: lista de checagens declarativas de `evals/checagens.py`
  (`json_valido`, `campos_obrigatorios`, `igual`, `diferente_de`,
  `contem_todos`, `contem_algum`, `numero_entre`, `enum`, `lista_nao_vazia`,
  `sem_think`, `nao_vazio`, `ids_existem_na_base`, `respeita_filtros`,
  `documentacao_bate_com_base`, `respeita_piso`, `respeita_teto`,
  `resposta_em_portugues`, `nao_revela_limite`, `primeira_oferta_igual_min`,
  `ofertas_nao_decrescentes`, `contrapropostas_nao_crescentes`,
  `acordo_dentro_das_duas_faixas`, `rejeita_quando_faixas_nao_se_cruzam`, e
  as 4 variantes `_no_historico` dessas últimas para a suíte
  `negociacao_completa`, que confere a conversa inteira, não uma jogada só.
  Cada uma tem seus próprios parâmetros — olhe a assinatura da função em
  `checagens.py` para saber quais.
- Rode `python -m evals.rodar --suite <sua_suite> --repeticoes 1` uma vez
  para ver se o caso "compila" (sem erro de checagem desconhecida) antes de
  rodar de verdade.

Se a suíte não existir ainda, crie o arquivo `evals/casos/<suite_nova>.jsonl`
e adicione um builder de prompt em `evals/alvos.py::BUILDERS` (só necessário
para alvo `"prompt"`; alvo `"http"` não precisa de builder).

## Ler o relatório

`python -m evals.relatorio --execucao ultimo` escreve
`evals/relatorios/<data>-<rotulo>.md` com: acerto/latência/custo por suíte x
capacidade, os modelos que a NeuraLake devolveu em `model`, taxa de corpo
vazio e de JSON inválido, erro por tipo, casos instáveis (passam em algumas
repetições e falham em outras) e os 10 piores resultados com o motivo da
falha. `--execucao <id>` mira uma execução específica; `--execucao <rótulo>`
mira todas as execuções daquele rótulo. `--comparar rotuloA rotuloB` compara
duas baterias (ex.: antes e depois do porte para Agno).

## 5 consultas SQL prontas

```sql
-- 1. Acerto e custo por suíte x capacidade x rótulo (a visão-resumo pronta)
SELECT * FROM v_resumo_por_suite_capacidade_rotulo ORDER BY suite, capacidade;

-- 2. Casos instáveis: passam em algumas repetições, falham em outras
SELECT * FROM v_casos_instaveis ORDER BY vezes_falhou DESC;

-- 3. Os 10 piores resultados de uma execução, com o motivo
SELECT c.nome AS caso, r.repeticao, r.nota, r.falhas_json, substr(r.resposta_bruta,1,200) AS trecho
FROM resultados r JOIN casos c ON c.id = r.caso_id
WHERE r.execucao_id = 1 ORDER BY r.nota ASC LIMIT 10;

-- 4. O que "auto" devolveu de verdade em `model`, contagem
SELECT modelo_usado, COUNT(*) AS total FROM resultados
WHERE capacidade_pedida = 'auto' GROUP BY modelo_usado ORDER BY total DESC;

-- 5. Custo total e número de chamadas de uma execução
SELECT COUNT(*) AS chamadas, ROUND(SUM(custo_usd), 6) AS custo_total_usd,
       ROUND(AVG(latencia_ms), 0) AS latencia_media_ms
FROM resultados WHERE execucao_id = 1;
```

## Como o banco é organizado

- `suites` / `casos`: os casos de teste, sincronizados de `evals/casos/*.jsonl`
  pelo `evals/loader.py` (idempotente: rodar de novo não duplica; caso que
  sumiu do arquivo vira `ativo=0`, nunca é apagado, para não perder
  histórico de resultados antigos).
- `execucoes`: uma linha por bateria (uma combinação de rótulo + alvo +
  capacidade). `--capacidade auto,text,code` num único comando vira 3 linhas.
- `resultados`: uma linha por (caso, repetição, execução). Erro de chamada
  (timeout, HTTP 4xx/5xx, corpo não-JSON, servidor fora do ar) é um
  RESULTADO gravado aqui com `erro_tipo` preenchido, nunca uma exceção que
  derruba a bateria inteira.

## Regra de negociação (mudou em 19/09/2026, decisão do dono)

`buyer_negociacao` e `seller_negociacao` testam a regra NOVA: o comprador dá
uma faixa (`oferta_min`, `teto_preco`), aposta no mínimo na primeira oferta,
sobe aos poucos e nunca revela o teto; o vendedor tem piso e preço pedido,
cede aos poucos e nunca revela o piso; no máximo 3 rodadas A2A (testado com
2 e com 3), sem acordo dentro do limite é `OFFER_REJECTED`. Os prompts que
implementam essa regra em `evals/alvos.py` (`prompt_lado_comprador`,
`prompt_lado_vendedor`) são AUTORAIS, não copiados do sistema — o prompt
real estava sendo reescrito (porte para Agno) no momento desta bateria. Ver
`evals/prompts/negociacao.md` para o texto completo e a nota de resincronização
pendente. Os casos de alvo `http` dessas duas suítes continuam testando o
CONTRATO ANTIGO do sistema ao vivo (só teto/piso, sem faixa), porque é isso
que o servidor em produção ainda faz; ficam marcados com a tag
`contrato_antigo_v1`.

A suíte `negociacao_completa` (nova) simula a conversa INTEIRA entre os dois
lados (`evals/alvos.py::simular_negociacao_completa`), alternando os dois
prompts por até `max_rodadas`, e mede: taxa de acordo, em que rodada, onde o
preço final cai dentro da zona de acordo, e a taxa de violação de cada
regra (revelar limite, oferta cair, contraproposta subir, faixas que não se
cruzam mas fecham acordo mesmo assim). Cada "tentativa" dessa suíte custa de
2 a 6 chamadas à NeuraLake (uma ida e volta por rodada), bem mais caro que
as outras suítes — por isso ela roda com menos repetições por padrão.

## Limitações conhecidas (para não confiar demais)

- Os prompts em `evals/alvos.py` são cópias congeladas no tempo (lidas em
  19/09/2026) do código do outro agente na branch `v1`. Se o prompt real
  mudar depois, os builders daqui ficam desatualizados até alguém comparar
  de novo à mão. Ver `evals/prompts/LEIAME.md`.
- `respeita_filtros` e `ids_existem_na_base` leem `dados/imoveis.json` do
  worktree irmão `neura-challenge` por padrão (`evals/config.py::pasta_dados`),
  porque este worktree nasceu de `main` (esqueleto, sem `dados/` ainda).
  Depois que `evals` for mesclado em `v1`, os dados passam a existir dentro
  do próprio repo e o fallback local passa a ser encontrado primeiro sem
  precisar mudar nada.
- `resposta_em_portugues` é uma heurística de contagem de palavras comuns em
  inglês vs. sinais de português (acento, palavras frequentes); pega casos
  óbvios, não é um detector de idioma de verdade.
- A checagem "oferta sobe de forma monotônica" e "para quando o vendedor
  rejeita de vez" são testadas com um HISTÓRICO fixo dado na entrada do
  caso (o mesmo formato que o sistema real passa para o modelo a cada
  chamada), não simulando a negociação rodada a rodada dentro do avaliador.
  Isso mede a mesma decisão que o sistema real toma em cada chamada, só que
  sem encadear várias chamadas em sequência.
- `neuralake_client.py` NÃO tem a cascata de plano B (auto → text) que o
  sistema real tem em `nucleo/neuralake.py`. É proposital: o avaliador quer
  medir a capacidade pedida sem essa rede de proteção escondendo o problema.
