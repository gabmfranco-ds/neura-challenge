# dados

Dono: a definir.

## AVISO: tudo aqui é inventado

A base de imóveis, os documentos e os vendedores são **dados de demonstração inventados**
para o hackathon. Nenhum imóvel existe, nenhum CPF ou CNPJ é real (os que aparecem estão
mascarados), nenhuma matrícula corresponde a cartório de verdade e nenhum valor foi
conferido com o mercado. Nada aqui é orientação jurídica nem avaliação imobiliária.

## O que tem

| Arquivo | O que é |
|---|---|
| `imoveis.json` | 30 imóveis em Pinheiros, Vila Madalena, Vila Mariana, Moema e Perdizes |
| `documentos/SP****.txt` | documentos de 10 imóveis: matrícula, certidão de IPTU, certidão de distribuição e declaração de condomínio |
| `criterios-fechamento.json` | lista inicial das condições precedentes para fechar compra no Brasil |
| `reprise-exemplo/` | uma gravação real de rodada, reserva para o palco |

## Campos de cada imóvel

Públicos (o anúncio): `property_id`, `tipo`, `cidade`, `bairro`, `endereco`, `preco`,
`area`, `quartos`, `suites`, `vagas`, `andar`, `condominio_mensal`, `iptu_anual`,
`ano_construcao`, `aceita_financiamento`, `caracteristicas`, `seller_agent`,
`texto_anuncio`.

Da base, não do anúncio: `disponibilidade` (`available` ou `unavailable`) e
`motivo_indisponibilidade`. O anúncio nunca diz que o imóvel está reservado, igual à vida
real. É por isso que um agente que só lê anúncio erra aqui.

Privado do vendedor: `_privado_vendedor` com `piso_preco`, `pressa` (0 a 1) e
`motivo_venda`. **Só o Seller Agent daquele imóvel vê.** Nem o comprador, nem o
Orchestrator, nem a tela recebem esses números.

## O que foi plantado de propósito

| Imóvel | O que tem | Quem descobre |
|---|---|---|
| SP1003 | hipoteca ATIVA na matrícula (AV-8), sem termo de quitação | verificação por código, lendo a matrícula |
| SP1010 | certidão de distribuição vencida em 11/06/2026 | verificação por código, comparando a validade com hoje |
| SP1005 | `disponibilidade: unavailable` (proposta aceita de outro comprador) | verificação por código, contra a base |
| SP1017 | `disponibilidade: unavailable` (retirado do mercado) | idem |

Documentos limpos: SP1002, SP1004, SP1007, SP1008, SP1019, SP1022, SP1025.

## Formato dos documentos

Texto puro, quatro seções marcadas com `=== NOME ===`. O código de verificação
(`nucleo/verificacao.py`) lê o texto e decide, sem LLM:

- **matrícula**: linha `AV-` ou `R-` com palavra de ônus (hipoteca, penhora, usufruto,
  indisponibilidade, arresto, alienação fiduciária) mais `Situação: ATIVA` vira pendência;
  `Situação: CANCELADA` não vira;
- **validade**: `Validade até: DD/MM/AAAA` anterior a hoje vira pendência;
- **certidões**: `Resultado:` precisa dizer `NADA CONSTA`;
- **condomínio**: `Situação:` precisa dizer `ADIMPLENTE`.

Documento novo só precisa seguir esse formato. Não mexa nos marcadores sem avisar quem
cuida de `nucleo/`.

## Critérios de fechamento

`criterios-fechamento.json` é **lista inicial escrita por quem não é especialista**. Tem um
campo `em_aberto` com o que já sabemos que falta. Quem domina compra e venda de imóvel no
Brasil corrige, completa e corta o que estiver errado. Cada condição tem `prova`
(`documento`, `calculo` ou `simulado`) e `fase`, que é o estado da máquina em que ela
precisa estar pronta.
