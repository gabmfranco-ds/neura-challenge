# Prompts usados nas avaliações

Os prompts de sistema e de usuário não ficam soltos em texto aqui: eles são
montados em código, em `evals/alvos.py`, porque dependem de dados do caso
(frase do comprador, histórico de negociação, candidatos do marketplace...).
Isso evita ter duas cópias do mesmo prompt (uma em `.md`, outra em `.py`) que
podem se descolar uma da outra.

Cada função de `evals/alvos.py` diz, no docstring, de qual arquivo do repo
`neura-challenge` (branch `v1`, lida em 19/09/2026) ela foi adaptada:

| Suíte | Função em `alvos.py` | Copiado/adaptado de |
|---|---|---|
| `buyer_extracao` | `build_buyer_extracao` | `agentes/buyer/agente.py::_entender` |
| `buyer_negociacao` | `build_buyer_negociacao` | `agentes/buyer/agente.py::_negociar` |
| `seller_negociacao` | `build_seller_negociacao` | `agentes/seller/agente.py::executar` |
| `property_busca` | `build_property_busca` | `agentes/property/agente.py::executar` |
| `orchestrator_escolha` | `build_orchestrator_escolha` | `orchestrator/motor.py::_avaliar_e_contratar` |
| `api_saude` | `build_api_saude` | não copiado de lugar nenhum: prompts genéricos, escritos para medir a API pura (texto, código, raciocínio, extração de JSON), sem depender do sistema |

O prompt de sistema em si (`sistema()` em `alvos.py`) é cópia de
`agentes/comum.py::sistema`. As fichas reduzidas em `alvos.FICHAS` são cópia
dos campos relevantes de `agentes/catalogo.py::FICHAS_FIXAS`.

Se o outro agente mudar esses prompts na branch `v1` depois de 19/09/2026,
`evals/alvos.py` fica desatualizado até alguém comparar de novo à mão — é uma
cópia congelada no tempo da leitura, não um link vivo. Isso é intencional
(o objetivo aqui era medir o sistema como ele estava naquele momento), mas
vale registrar como limitação conhecida no LEIAME principal.
