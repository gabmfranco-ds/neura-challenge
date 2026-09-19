# Marketplace

O que mora aqui: o catálogo de fichas de agente (formato Agent Card do A2A), a busca por
capacidade (`GET /marketplace/agentes?capacidade=...`), o cadastro de agente novo
(`POST /marketplace/agentes`) e o histórico de entregas verificadas construído a partir
dos recibos que o consultor publica (`POST /marketplace/recibos`).

Dono: a definir.

Regra: só o dono escreve nesta pasta. O contrato com as outras pastas é o HTTP descrito
em `SPEC.md`, nunca import direto nem acesso a arquivo de outra pasta.

Primeira tarefa (hora 0 a 1): subir esta pasta com respostas de mentira que já obedecem
ao contrato HTTP (ficha de exemplo, busca por capacidade devolvendo histórico fixo),
para o resto do time integrar em cima antes de qualquer lógica real existir.
