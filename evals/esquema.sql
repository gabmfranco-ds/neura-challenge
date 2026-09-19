-- Esquema do banco de avaliações (evals/evals.db). Versionado aqui; o .db em si NÃO vai
-- para o git (veja .gitignore). Rodar evals/loader.py ou evals/rodar.py aplica este
-- arquivo automaticamente e é seguro rodar de novo (tudo com IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS suites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    descricao TEXT
);

CREATE TABLE IF NOT EXISTS casos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suite_id INTEGER NOT NULL REFERENCES suites(id),
    nome TEXT NOT NULL,
    entrada_json TEXT NOT NULL,
    esperado_json TEXT,
    checagens_json TEXT NOT NULL,
    tags TEXT,
    criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ativo INTEGER NOT NULL DEFAULT 1,
    UNIQUE (suite_id, nome)
);

CREATE TABLE IF NOT EXISTS execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iniciada_em TEXT NOT NULL,
    terminada_em TEXT,
    rotulo TEXT NOT NULL,
    alvo TEXT NOT NULL,               -- 'prompt' ou 'http'
    capacidade TEXT NOT NULL,         -- auto | text | code | reasoning | reasoning-pro | multimodal
    git_ref TEXT,
    observacao TEXT
);

CREATE TABLE IF NOT EXISTS resultados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao_id INTEGER NOT NULL REFERENCES execucoes(id),
    caso_id INTEGER NOT NULL REFERENCES casos(id),
    repeticao INTEGER NOT NULL,
    passou INTEGER NOT NULL,          -- 0/1
    nota REAL NOT NULL,               -- fração de checagens que passaram, 0..1
    falhas_json TEXT NOT NULL,        -- lista de {checagem, motivo}
    saida_json TEXT,                  -- objeto estruturado que o avaliador conseguiu extrair
    resposta_bruta TEXT,              -- corpo da resposta da API (sem cabeçalhos, sem chave)
    modelo_usado TEXT,                -- campo "model" que a NeuraLake devolveu
    capacidade_pedida TEXT,
    latencia_ms INTEGER,
    tokens_entrada INTEGER,
    tokens_saida INTEGER,
    custo_usd REAL,
    erro_tipo TEXT,                   -- null | timeout | http_erro | corpo_vazio | json_invalido |
                                       -- rede | alvo_fora_do_ar
    http_status INTEGER,
    criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS ix_resultados_execucao ON resultados(execucao_id);
CREATE INDEX IF NOT EXISTS ix_resultados_caso ON resultados(caso_id);
CREATE INDEX IF NOT EXISTS ix_casos_suite ON casos(suite_id);

-- ================================================================ visões

-- Taxa de acerto, p50/p95 de latência e custo médio por suite x capacidade x rótulo.
-- sqlite não tem PERCENTILE_CONT nativo: p50/p95 aproximado por posição ordenada.
DROP VIEW IF EXISTS v_resumo_por_suite_capacidade_rotulo;
CREATE VIEW v_resumo_por_suite_capacidade_rotulo AS
SELECT
    s.nome AS suite,
    e.capacidade,
    e.rotulo,
    e.alvo,
    COUNT(*) AS total_execucoes_de_caso,
    SUM(r.passou) AS total_passou,
    ROUND(1.0 * SUM(r.passou) / COUNT(*), 4) AS taxa_acerto,
    ROUND(AVG(r.nota), 4) AS nota_media,
    ROUND(AVG(r.custo_usd), 6) AS custo_medio_usd,
    ROUND(SUM(r.custo_usd), 6) AS custo_total_usd,
    ROUND(AVG(r.latencia_ms), 1) AS latencia_media_ms,
    SUM(CASE WHEN r.erro_tipo IS NOT NULL THEN 1 ELSE 0 END) AS total_erros
FROM resultados r
JOIN casos c ON c.id = r.caso_id
JOIN suites s ON s.id = c.suite_id
JOIN execucoes e ON e.id = r.execucao_id
GROUP BY s.nome, e.capacidade, e.rotulo, e.alvo;

-- Casos instáveis: passam em algumas repetições e falham em outras, na MESMA execução.
DROP VIEW IF EXISTS v_casos_instaveis;
CREATE VIEW v_casos_instaveis AS
SELECT
    r.execucao_id,
    s.nome AS suite,
    c.nome AS caso,
    c.id AS caso_id,
    COUNT(*) AS repeticoes,
    SUM(r.passou) AS vezes_passou,
    COUNT(*) - SUM(r.passou) AS vezes_falhou
FROM resultados r
JOIN casos c ON c.id = r.caso_id
JOIN suites s ON s.id = c.suite_id
GROUP BY r.execucao_id, c.id
HAVING vezes_passou > 0 AND vezes_falhou > 0;

-- Latência: guarda todas as linhas ordenadas por execução para o relatório calcular
-- p50/p95 em Python (mais simples e mais correto que aproximar em SQL puro).
DROP VIEW IF EXISTS v_latencias;
CREATE VIEW v_latencias AS
SELECT r.execucao_id, s.nome AS suite, e.capacidade, e.rotulo, r.latencia_ms
FROM resultados r
JOIN casos c ON c.id = r.caso_id
JOIN suites s ON s.id = c.suite_id
JOIN execucoes e ON e.id = r.execucao_id
WHERE r.latencia_ms IS NOT NULL;

-- Modelos que "auto" escolheu de verdade (campo `model` devolvido pela API).
DROP VIEW IF EXISTS v_modelos_escolhidos;
CREATE VIEW v_modelos_escolhidos AS
SELECT r.execucao_id, e.capacidade AS capacidade_da_execucao, r.capacidade_pedida,
       r.modelo_usado, COUNT(*) AS total
FROM resultados r
JOIN execucoes e ON e.id = r.execucao_id
GROUP BY r.execucao_id, r.modelo_usado;
