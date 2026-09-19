# Consultor

O que mora aqui: o laço de decisão do agente consultor (entende, descobre, avalia,
contrata, verifica, responde, fecha), a carteira em dólar, o registro de decisões
(`/consultor/decisoes`) e a verificação por conta de código de cada entrega recebida
dos agentes do catálogo.

Dono: a definir.

Regra: só o dono escreve nesta pasta. O contrato com as outras pastas é o HTTP descrito
em `SPEC.md`, nunca import direto nem acesso a arquivo de outra pasta.

Primeira tarefa (hora 0 a 1): subir esta pasta com respostas de mentira que já obedecem
ao contrato HTTP (rotas `/consultor/objetivos`, `/consultor/decisoes`,
`/consultor/carteiras`), para o resto do time integrar em cima antes de qualquer lógica
real existir.
