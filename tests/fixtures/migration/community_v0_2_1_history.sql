-- PaperSeek Community v0.2.1 SQLite migration input fixture.
-- Schema source: release commit 009a585a7b89e0b8792e795adc62bfecda646ace.
-- All rows are synthetic; this file was not derived from a user database.

PRAGMA foreign_keys = ON;
PRAGMA user_version = 0;

BEGIN TRANSACTION;

CREATE TABLE search_runs (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    source TEXT,
    final_query TEXT,
    db TEXT,
    field TEXT,
    total INTEGER,
    iterations INTEGER,
    status TEXT NOT NULL,
    error_message TEXT,
    params_json TEXT,
    history_json TEXT,
    citation_map_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE search_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    event_type TEXT,
    stage TEXT,
    status TEXT,
    message TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES search_runs(id) ON DELETE CASCADE
);

CREATE TABLE search_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    rank INTEGER,
    paper_uid TEXT,
    source TEXT,
    title TEXT,
    authors_json TEXT,
    year INTEGER,
    venue TEXT,
    doi TEXT,
    url TEXT,
    abstract TEXT,
    citation_count INTEGER,
    relevance_score REAL,
    relevance_reason TEXT,
    raw_json TEXT,
    FOREIGN KEY(run_id) REFERENCES search_runs(id) ON DELETE CASCADE
);

CREATE INDEX idx_search_runs_created_at ON search_runs(created_at DESC);
CREATE INDEX idx_search_events_run_id ON search_events(run_id);
CREATE INDEX idx_search_results_run_id ON search_results(run_id);

INSERT INTO search_runs (
    id, question, source, final_query, db, field, total, iterations, status,
    error_message, params_json, history_json, citation_map_json,
    created_at, started_at, finished_at
) VALUES (
    'run_v02_fixture_success',
    'How does reproducible metadata support evidence synthesis?',
    'openalex',
    '"reproducible metadata" AND "evidence synthesis"',
    'OPENALEX',
    '',
    2,
    1,
    'success',
    NULL,
    '{"citation_max_records":20,"citation_per_seed":3,"citation_seed_count":2,"data_source":"openalex","discipline_fields":[],"expand_citations":true,"fetch_abstracts":true,"has_crossref_email":false,"has_llm_api_key":false,"has_openalex_api_key":false,"has_openalex_email":false,"has_wos_api_key":false,"llm_api_type":"openai_chat","llm_base_url":"https://api.example.test/v1","llm_max_tokens":2048,"llm_model":"fixture-model","llm_provider":"openai","max_iterations":3,"ranking_candidate_limit":256,"retrieval_crossref_enrichment":false,"retrieval_embedding_model":"","retrieval_embedding_provider":"local","retrieval_lane_limit":1000,"retrieval_pool_max":3000,"retrieval_pool_min":5,"retrieval_reranker_model":"","retrieval_reranker_provider":"","retrieval_rrf_k":60,"search_field":"","target_max":1000,"target_min":100,"wos_db":"WOS"}',
    '[{"action":"accept","iteration":1,"message":"Accepted two synthetic records.","query":"reproducible metadata AND evidence synthesis","total":2}]',
    '{"added_candidates":1,"candidate_pool":2,"edges":[{"layer":"1","seed":"W-FIXTURE-1001","source":"W-FIXTURE-1001","target":"W-FIXTURE-1002","type":"references"}],"enabled":true,"initial_candidates":1,"nodes":[{"citations":12,"id":"W-FIXTURE-1001","roles":["seed","result"],"seed_uids":[],"title":"Reproducible Metadata for Evidence Synthesis","year":2024},{"citations":7,"id":"W-FIXTURE-1002","roles":["backward","result"],"seed_uids":["W-FIXTURE-1001"],"title":"Auditable Study Records","year":2022}],"seed_count":1,"status":"complete","supported":true}',
    '2026-07-03T09:00:00+08:00',
    '2026-07-03T09:00:00+08:00',
    '2026-07-03T09:01:30+08:00'
);

INSERT INTO search_runs (
    id, question, source, final_query, db, field, total, iterations, status,
    error_message, params_json, history_json, citation_map_json,
    created_at, started_at, finished_at
) VALUES (
    'run_v02_fixture_error',
    'Which metadata checks detect incomplete records?',
    'crossref',
    'metadata completeness checks',
    'CROSSREF',
    '',
    0,
    1,
    'error',
    'Synthetic upstream timeout.',
    '{"data_source":"crossref","expand_citations":false,"fetch_abstracts":true,"has_crossref_email":false,"has_llm_api_key":false,"max_iterations":3,"target_max":1000,"target_min":100}',
    '[]',
    '{"enabled":false,"status":"disabled"}',
    '2026-07-03T10:00:00+08:00',
    '2026-07-03T10:00:00+08:00',
    '2026-07-03T10:00:20+08:00'
);

INSERT INTO search_runs (
    id, question, source, final_query, db, field, total, iterations, status,
    error_message, params_json, history_json, citation_map_json,
    created_at, started_at, finished_at
) VALUES (
    'run_v02_fixture_running',
    'How are review protocols registered?',
    'arxiv',
    'review protocol registration',
    'ARXIV',
    '',
    NULL,
    0,
    'running',
    NULL,
    '{"data_source":"arxiv","expand_citations":true,"fetch_abstracts":true,"has_llm_api_key":false,"max_iterations":3,"target_max":1000,"target_min":100}',
    '[]',
    '{}',
    '2026-07-03T11:00:00+08:00',
    '2026-07-03T11:00:00+08:00',
    NULL
);

INSERT INTO search_events (
    id, run_id, event_type, stage, status, message, payload_json, created_at
) VALUES
    (1, 'run_v02_fixture_success', 'status', 'search', 'running', 'Synthetic search started.', '{"message":"Synthetic search started.","stage":"search","status":"running","type":"status"}', '2026-07-03T09:00:01+08:00'),
    (2, 'run_v02_fixture_success', 'status', 'complete', 'success', 'Synthetic search completed.', '{"message":"Synthetic search completed.","stage":"complete","status":"success","type":"status"}', '2026-07-03T09:01:30+08:00'),
    (3, 'run_v02_fixture_error', 'error', 'search', 'error', 'Synthetic upstream timeout.', '{"message":"Synthetic upstream timeout.","stage":"search","status":"error","type":"error"}', '2026-07-03T10:00:20+08:00'),
    (4, 'run_v02_fixture_running', 'status', 'search', 'running', 'Synthetic search remains in the old runtime state.', '{"message":"Synthetic search remains in the old runtime state.","stage":"search","status":"running","type":"status"}', '2026-07-03T11:00:01+08:00');

INSERT INTO search_results (
    id, run_id, rank, paper_uid, source, title, authors_json, year, venue,
    doi, url, abstract, citation_count, relevance_score, relevance_reason, raw_json
) VALUES (
    1,
    'run_v02_fixture_success',
    1,
    'W-FIXTURE-1001',
    'openalex',
    'Reproducible Metadata for Evidence Synthesis',
    '["Fixture Author A","Fixture Author B"]',
    2024,
    'Journal of Synthetic Evidence',
    '10.5555/paperseek.fixture.1001',
    'https://example.test/papers/1001',
    'A synthetic abstract about reproducible metadata.',
    12,
    9.0,
    'Directly addresses the synthetic research question.',
    '{"abstract":"A synthetic abstract about reproducible metadata.","authors":["Fixture Author A","Fixture Author B"],"authors_text":"Fixture Author A; Fixture Author B","citation_count":12,"citations":"12","document_types":["article"],"doi":"10.5555/paperseek.fixture.1001","id":"W-FIXTURE-1001","keywords":"metadata; evidence synthesis","links":{"landing_page":"https://example.test/papers/1001","record":"https://example.test/records/1001"},"provider":"openalex","publication_type":"article","publish_year":2024,"rank":1,"reasoning":"Directly addresses the synthetic research question.","relevance_reason":"Directly addresses the synthetic research question.","relevance_score":9.0,"score":9.0,"source":"Journal of Synthetic Evidence","title":"Reproducible Metadata for Evidence Synthesis","uid":"W-FIXTURE-1001","url":"https://example.test/papers/1001","venue":"Journal of Synthetic Evidence","year":2024}'
);

INSERT INTO search_results (
    id, run_id, rank, paper_uid, source, title, authors_json, year, venue,
    doi, url, abstract, citation_count, relevance_score, relevance_reason, raw_json
) VALUES (
    2,
    'run_v02_fixture_success',
    2,
    'W-FIXTURE-1002',
    'openalex',
    'Auditable Study Records',
    '["Fixture Author C"]',
    2022,
    'Synthetic Methods Quarterly',
    '10.5555/paperseek.fixture.1002',
    'https://example.test/papers/1002',
    'A synthetic abstract about auditable study records.',
    7,
    7.5,
    'Provides a synthetic citation-expanded result.',
    '{"abstract":"A synthetic abstract about auditable study records.","authors":["Fixture Author C"],"authors_text":"Fixture Author C","citation_count":7,"citations":"7","document_types":["article"],"doi":"10.5555/paperseek.fixture.1002","id":"W-FIXTURE-1002","keywords":"audit; study records","links":{"landing_page":"https://example.test/papers/1002","record":"https://example.test/records/1002"},"provider":"openalex","publication_type":"article","publish_year":2022,"rank":2,"reasoning":"Provides a synthetic citation-expanded result.","relevance_reason":"Provides a synthetic citation-expanded result.","relevance_score":7.5,"score":7.5,"source":"Synthetic Methods Quarterly","title":"Auditable Study Records","uid":"W-FIXTURE-1002","url":"https://example.test/papers/1002","venue":"Synthetic Methods Quarterly","year":2022}'
);

COMMIT;
