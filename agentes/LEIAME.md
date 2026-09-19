# Agentes do catálogo

O que mora aqui: os agentes que o consultor contrata via marketplace, busca de imóveis,
documentação (uma versão cara e uma barata, para a demo de falha), simulação de
financiamento e avaliação de preço, além do agente de contrato usado no segundo ato
(lista de fechamento). Cada agente expõe a própria ficha em
`GET {url}/.well-known/agent-card.json` e recebe tarefa em `POST {url}/tarefas`.

Dono: a definir.

Regra: só o dono escreve nesta pasta. O contrato com as outras pastas é o HTTP descrito
em `SPEC.md`, nunca import direto nem acesso a arquivo de outra pasta.

Primeira tarefa (hora 0 a 1): subir esta pasta com respostas de mentira que já obedecem
ao contrato (ficha + `/tarefas` devolvendo saída fixa), para o resto do time integrar em
cima antes de qualquer lógica real existir.
