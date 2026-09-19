# NeuraLake API — o que funciona de verdade

Testado em 19/09/2026 contra `https://api.neuralake.cloud/v1/chat/completions`. Todo comando abaixo é reproduzível com `curl` e a variável `$KEY` (sua chave, nunca em texto puro).

```bash
KEY=$(cat /caminho/para/neuralake.txt | tr -d '\r\n')
```

## O que funciona

- **Chamada de ferramenta (`tools`/`tool_choice`)** funciona bem em `text`, `code`, `auto` e `multimodal`. Retorna `tool_calls` preenchido, formato OpenAI padrão.
- **Segundo turno com `role: "tool"`** é aceito e o modelo usa o resultado — **mas só testado funcionando em `code`**. Em `text` falhou (ver Armadilhas).
- **`response_format: {"type":"json_object"}`** aceito, devolve JSON válido.
- **`response_format: {"type":"json_schema"}`** aceito, devolve JSON que respeita o schema pedido (teste simples).
- **`stream: true`** funciona em `text`, `reasoning` e `multimodal` (não testei `code`, `reasoning-pro`, `auto` em stream, mas não há motivo para esperar diferença). Formato SSE clássico: `data: {...}` por pedaço, `data: [DONE]` no final.
- **Multimodal aceita imagem por URL pública** (imagem precisa responder com Content-Type de imagem de verdade) **e por base64 `data:image/...;base64,...`**. As duas formas testadas e aceitas.
- **10 chamadas em paralelo**: todas voltaram 200, nenhum 429. Não achei o teto de rate limit neste teste (pode existir um mais alto, não testei acima de 10).
- **`max_tokens` aceita valores absurdos** (999999) sem erro de validação — não há teto anunciado por parâmetro; o que existe é o teto de **contexto total** (input + output), esse sim rígido (ver tabela de limites).
- **Roteador `auto`** existe e responde, mas nos três testes feitos (pergunta trivial, pedido de código, problema de raciocínio em várias etapas) sempre roteou para **`text`**, nunca para `code` nem `reasoning`.

## O que NÃO funciona

- **`reasoning` nunca devolve `tool_calls` de verdade.** Testado 2x (com `tool_choice:"auto"` e com `tool_choice` forçado no nome da função): em ambos, `tool_calls` veio `[]` vazio e o modelo escreveu uma pseudo-sintaxe em texto livre (`!function_call:{"call":...}`) dentro do `content`/`<think>`. **Não dá para usar `reasoning` como agente que chama ferramenta.**
- **`role: "tool"` no turno seguinte falha em `text`** (testado 2x, mesmo resultado): o modelo responde "I cannot accomplish this task using the available functions." em vez de usar o resultado da ferramenta. Use `code` para esse padrão, ou trate `text` como só-de-ida (chama ferramenta, mas não fecha o loop).
- **`GET /v1/models`** → 404 (já sabido, confirmado de novo).
- **Cross Memory**: não existe parâmetro, header ou rota documentada em nenhuma página do site (home, `api.html`, `pricing.html`, `wonka.html`, playground, benchmark). Mandei `"cross_memory": true` no corpo e `X-Cross-Memory: true` no header — a API aceitou (200) mas ignorou silenciosamente, sem efeito visível no `usage`. **Não achei como ligar isso. Pode não existir de fato, só ser texto de marketing dos "93% de economia".**
- **MCP, A2A, x402**: zero menção em qualquer página do site verificada (home, `api.html`, `pricing.html`, `wonka.html`, playground `beta.neuraserver.cloud`, `bench.neuraserver.cloud`) e toda rota candidata testada devolveu 404 (`/v1/mcp`, `/mcp`, `/v1/a2a`, `/a2a`, `/v1/x402`, `/x402`, `/.well-known/mcp.json`, `/.well-known/x402`). **É marketing sem endpoint, ou não achei — não invente que existe.**
- **Imagem multimodal com URL inacessível ou MIME errado** falha com erro claro (ver seção Erros) — não trava silenciosamente.

## Tabela: custo e latência por capacidade (mesma pergunta curta)

Pergunta: "Em uma frase curta, o que é fotossíntese?" — `max_tokens: 150` para custo, `max_tokens: 10` para latência (chamada separada, mais barata).

| capacidade | modelo devolvido em `model` | completion_tokens (max 150) | custo (USD) | latência (max 10, ~s) | observação |
|---|---|---|---|---|---|
| `text` | text | 20 | $0.0000083 | 1.46s | resposta completa |
| `code` | code | 43 | $0.0000496 | 0.80s | resposta completa |
| `reasoning` | reasoning | 150 (cortado) | $0.000331 | 1.44s | `<think>` consumiu o budget inteiro, resposta cortada no meio do raciocínio |
| `reasoning-pro` | reasoning-pro | 150 (cortado) | $0.00054225 | 1.63s | `reasoning_content` sozinho encheu tudo, `content` veio **vazio** |
| `multimodal` | multimodal | 150 (cortado) | $0.00054225 | 1.36s | mesmo problema: `reasoning_content` come o budget, `content` vazio |
| `auto` | text (roteou) | 20 | $0.0000083 | 1.85s | idêntico a `text` porque foi para lá |

**Implicação prática**: `reasoning`, `reasoning-pro` e `multimodal` sempre gastam tokens em raciocínio invisível/visível antes de responder. Com `max_tokens` baixo (150 ou menos) essas três capacidades **não terminam a resposta**. Testado depois: `multimodal` só terminou de responder com `max_tokens: 800` (484 completion_tokens gastos, a maior parte em `reasoning_content`).

## 1. Chamada de ferramenta

```bash
curl -sS -X POST https://api.neuralake.cloud/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"text","messages":[{"role":"user","content":"Qual o clima em Sao Paulo agora?"}],
      "tools":[{"type":"function","function":{"name":"get_weather","description":"Retorna o clima de uma cidade","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}],
      "tool_choice":"auto","max_tokens":100}'
```
Resposta (text, funcionou):
```json
"tool_calls":[{"id":"chatcmpl-tool-8e49d411216528b1","type":"function","function":{"name":"get_weather","arguments":"{\"city\": \"Sao Paulo\"}"}}]
```

Mesmo teste em `reasoning` (com `tool_choice` forçado no nome da função, `max_tokens:400`):
```json
"content":"\n!function_call:{\"call\": \"add\", \"arguments\": {\"a\": 2, \"b\": 3}}","tool_calls":[]
```
`tool_calls` vazio — a "chamada" veio como texto solto, não estruturada. Reproduzido 2x, mesmo padrão.

Turno seguinte com `role:"tool"`:
```bash
curl -sS -X POST https://api.neuralake.cloud/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"code","messages":[
        {"role":"user","content":"Rode a ferramenta para somar 2 e 3"},
        {"role":"assistant","content":null,"tool_calls":[{"id":"call_1","type":"function","function":{"name":"add","arguments":"{\"a\": 2, \"b\": 3}"}}]},
        {"role":"tool","tool_call_id":"call_1","content":"5"}],
      "tools":[{"type":"function","function":{"name":"add","description":"Soma dois numeros","parameters":{"type":"object","properties":{"a":{"type":"number"},"b":{"type":"number"}},"required":["a","b"]}}}],
      "max_tokens":60}'
```
Resposta (`code`, funcionou): `"content":"A soma de 2 e 3 é igual a 5."`
O mesmo payload em `text` devolveu `"content":"I cannot accomplish this task using the available functions."` — reproduzido 2x.

## 2. JSON obrigatório

```bash
curl -sS -X POST https://api.neuralake.cloud/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"text","messages":[{"role":"user","content":"Devolva um objeto JSON com nome e idade de uma pessoa fictícia."}],"response_format":{"type":"json_object"},"max_tokens":60}'
```
Resposta: `"content":"{\n  \"nome\": \"João Silva\",\n  \"idade\": 30\n}"` — aceito, JSON válido.

`json_schema` também aceito (mesmo formato de request do OpenAI, com `json_schema.name` e `json_schema.schema`), devolveu objeto com os campos do schema pedido. Não testei schema aninhado nem `strict:true` — só o caso simples.

## 3. Transmissão contínua (stream)

```bash
curl -sS -N -X POST https://api.neuralake.cloud/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"text","messages":[{"role":"user","content":"Conte de 1 a 5"}],"stream":true,"max_tokens":40}'
```
Pedaços chegam como:
```
data: {"...","choices":[{"index":0,"delta":{"role":"assistant","content":"","...},"finish_reason":null}],"usage":null}
...
data: {"...","choices":[{"index":0,"delta":{"role":null,"content":"1, 2, 3, 4, 5",...},"finish_reason":"stop"}],"usage":{...}}
data: {"...","choices":[],"usage":{"...","estimated_cost":0.000006,...}}
data: [DONE]
```
Em `reasoning`, o `<think>` vem token a token dentro de `delta.content` (mesmo tag literal que no modo não-stream). Em `multimodal`, o pensamento vem em `delta.reasoning_content` (campo separado) e o stream manda um comentário SSE de manutenção de conexão: `: ping - <timestamp>` antes dos dados — **se o seu parser de SSE só trata linhas `data:`, tudo bem, mas se ele quebra em qualquer linha não-vazia, essa linha de ping derruba o parser.**

## 4. Limites

**Contexto (input + output), medido pelo próprio erro da API ao estourar** (mesmo texto grande, só troquei o `model`):

| capacidade | teto de contexto (tokens) |
|---|---|
| `text` | 131072 |
| `auto` | 131072 (mesmo teto de `text`) |
| `reasoning` | 163840 |
| `reasoning-pro` | 262144 |
| `multimodal` | 262144 |
| `code` | não achei o teto — aceitou 260018 tokens de input sem erro (custou $0.078, não fui além) |

Comando usado para achar o teto de `text`:
```bash
# arquivo com ~1.95M caracteres de input
curl -sS -X POST https://api.neuralake.cloud/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  --data-binary @contexto_grande.json
```
Erro devolvido:
```json
{"error":{"message":"This model's maximum context length is 131072 tokens. However, you requested 10 output tokens and your prompt contains at least 131063 input tokens...","code":null}}
```
Erro do `reasoning` no mesmo texto (tokenizado diferente — capacidades diferentes contam tokens de forma diferente para o mesmo texto):
```json
{"error":{"message":"Input too long: 260014 input tokens, limit is 163840 for this model","code":"context_length_exceeded"}}
```

**`max_tokens`**: sem teto aparente — `999999` foi aceito em `text`, `reasoning-pro` e `multimodal` sem erro (o modelo só para quando termina a resposta). `max_tokens: 0` dá erro 422 (`"Input should be greater than 0"`).

**Rate limit**: disparei 10 chamadas em paralelo em `text`, todas voltaram 200 em 0.9–1.4s. Nenhum 429 observado. Não testei volumes maiores (20, 50 em paralelo) — se o hackathon vai bater muito volume, vale testar isso de novo com folga.

## 5. Custo por capacidade

Ver tabela na seção "O que funciona" acima. Comando usado (repetir trocando `model`):
```bash
curl -sS -X POST https://api.neuralake.cloud/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"text","messages":[{"role":"user","content":"Em uma frase curta, o que e fotossintese?"}],"max_tokens":150}'
```

## 6. Roteador `auto`

Três pedidos, três respostas — todos vieram com `"model":"text"` no roteamento de saída:
- Pergunta trivial ("o que é fotossíntese?") → `text`
- Pedido de código ("função Python para checar número primo") → `text` (e respondeu com código Python correto)
- Problema de raciocínio em várias etapas (dois trens se encontrando) → `text` (resolveu corretamente, passo a passo)

```bash
curl -sS -X POST https://api.neuralake.cloud/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Escreva uma funcao em Python que verifica se um numero e primo."}],"max_tokens":200}'
```
`"model":"text"` na resposta, mesmo sendo um pedido de código. **Não vi o roteador escolher `code` nem `reasoning` em nenhum dos três testes.** Se seu app depende do roteador escolher a capacidade "certa" automaticamente, não confie — force o `model` manualmente.

## 7. Multimodal

Por URL pública (imagem de verdade, Content-Type correto):
```bash
curl -sS -X POST https://api.neuralake.cloud/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"multimodal","messages":[{"role":"user","content":[{"type":"text","text":"Descreva esta imagem em poucas palavras"},{"type":"image_url","image_url":{"url":"https://httpbin.org/image/jpeg"}}]}],"max_tokens":800}'
```
Funcionou — descreveu corretamente a imagem (um chacal). Com `max_tokens:300` o `content` veio **vazio** (o raciocínio interno consumiu tudo); só com `max_tokens:800` saiu resposta final.

Por base64 (`data:image/png;base64,...`): aceito e processado (não deu erro), mas a imagem de teste era um PNG de 1x1 pixel e o modelo "viu" a cor errada — problema do teste (imagem degenerada), não da API.

URL inacessível (imagem do Wikipedia commons, bloqueou o hotlink):
```json
{"error":{"message":"Failed to download one or more images. Ensure URLs are reachable and serve a supported image MIME type (image/jpeg, image/png, image/webp, image/gif).","type":"invalid_request_error"}}
```

## 8. Erros

| caso | HTTP | formato |
|---|---|---|
| chave inválida | 401 | `{"error":"Unauthorized or invalid API key."}` (string simples) |
| capacidade inexistente (`model:"supermodel-9000"`) | 400 | `{"error":"Modelo não suportado. Use 'auto' ou um dos aliases: text, code, reasoning, reasoning-pro, multimodal."}` (string simples) |
| JSON malformado no corpo | 400 | **página HTML de stack trace do Express/body-parser**, não JSON — se seu código só faz `response.json()` sem checar `Content-Type`, vai quebrar |
| campo obrigatório faltando (`messages` ausente) | 422 | `{"error":{"message":"Field required","type":"invalid_request_error","param":"messages","code":"missing_required_parameter"}}` (objeto estruturado, estilo OpenAI) |
| `max_tokens:0` | 422 | `{"error":{"message":"Input should be greater than 0","param":"max_tokens","code":null}}` |
| contexto estourado | 400 | `{"error":{"message":"...","code":"context_length_exceeded"}}` |

**O formato do erro não é consistente**: às vezes `error` é string, às vezes é objeto com `message`/`type`/`param`/`code`, às vezes é uma página HTML inteira. **Seu parser de erro precisa checar o `Content-Type` da resposta antes de tentar `JSON.parse`, e tratar `typeof error` tanto string quanto objeto.**

## 9. Cross Memory

Site fala em "carrega o estado da tarefa entre trocas de modelo" e "até 93% de economia de tokens em fluxos multi-modelo", sem expor nenhum parâmetro, header ou rota.

Testado:
```bash
curl -sS -X POST https://api.neuralake.cloud/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -H "X-Cross-Memory: true" \
  -d '{"model":"text","messages":[{"role":"user","content":"oi"}],"max_tokens":5,"cross_memory":true}'
```
Resultado: 200, sem erro, mas sem nenhum sinal no `usage` de que algo mudou. **Não achei como ativar isso de propósito — nem sei se existe como feature controlável ou é só otimização interna automática (ou marketing).** Não assuma que dá pra ligar/desligar.

## 10. Protocolos (MCP, A2A, x402)

Verificado em: `neuralake.com.br` (home, `api.html`, `pricing.html`, `wonka.html`), `beta.neuraserver.cloud`, `bench.neuraserver.cloud`. Nenhuma menção a MCP, A2A ou x402 em nenhuma dessas páginas.

Rotas candidatas testadas, todas 404:
```
/v1/mcp  /mcp  /v1/a2a  /a2a  /v1/x402  /x402  /.well-known/mcp.json  /.well-known/x402
```
**Conclusão: é marketing do briefing do hackathon sem endpoint correspondente encontrado, ou está em algum lugar que não achei. Não use nenhum desses três protocolos como se existissem na API — não achei nada de concreto.**

## Armadilhas

- **`reasoning` não serve para agente com ferramenta.** `tool_calls` nunca vem preenchido, sai texto solto tipo `!function_call:{...}`. Se seu papel amanhã precisa de tool calling confiável, use `text`, `code`, `auto` ou `multimodal` — não `reasoning`.
- **`reasoning`, `reasoning-pro` e `multimodal` comem `max_tokens` com pensamento antes de responder.** Com budget baixo (150 ou menos) a resposta final some (`content` vazio ou cortado no meio). Para essas três, use `max_tokens` generoso (500+, idealmente 800+ para multimodal).
- **`role:"tool"` no segundo turno falha em `text`** (some com "I cannot accomplish this task"). Use `code` para fechar o loop de tool calling, ou não force esse padrão em `text`.
- **Erro de corpo malformado volta como página HTML, não JSON.** Se seu client faz `response.json()` sem checar status/content-type primeiro, vai estourar exceção de parse em vez de mostrar o erro real.
- **Formato de erro muda por tipo de falha** (string vs. objeto estruturado vs. HTML). Trate os três casos.
- **`auto` não necessariamente escolhe a capacidade "óbvia".** Em três testes (trivial, código, raciocínio complexo) sempre caiu em `text`. Se você precisa de `code` ou `reasoning` de propósito, force o `model` manualmente em vez de confiar no roteador.
- **Cada capacidade tokeniza diferente.** O mesmo texto conta tokens diferentes dependendo do `model` — não assuma que o teto de contexto de uma capacidade vale para outra, e não estime tokens de uma capacidade usando a contagem de outra.
- **Imagem por URL falha se o host bloquear hotlink** (Wikipedia bloqueou, httpbin não). Se for usar imagem de teste amanhã, teste a URL antes de depender dela ao vivo, ou use base64.
- **Cross Memory não tem controle conhecido.** Não prometa "ligar" essa economia de tokens para o júri — não achei como.
- **MCP/A2A/x402 não têm endpoint.** Não construa nada em cima disso amanhã.
