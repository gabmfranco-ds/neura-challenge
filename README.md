# Neura Challenge

Um comprador escreve uma frase. Um agente consultor acha o imóvel certo contratando
outros agentes num marketplace, sem nenhum humano escolher quem faz o quê, e só paga
pelo que foi provado.

Spec completa: [SPEC.md](SPEC.md)

## Pastas

| Pasta | Dono |
|---|---|
| `consultor/` | a definir |
| `marketplace/` | a definir |
| `agentes/` | a definir |
| `tela/` | a definir |
| `dados/` | a definir |

## Regras duras

- Chave da NeuraLake só em variável de ambiente `NEURALAKE_API_KEY`. Nunca em arquivo,
  log, gravação ou git.
- Nenhum atalho de código que force o resultado de um agente. Agente ruim é ficha e
  instrução diferentes, o comportamento sai do modelo.
- Reprise nunca se passa por ao vivo.
- Dizer no palco o que veio pronto antes do evento.

## Como rodar

A definir na primeira hora (Python, FastAPI, um comando sobe tudo).
