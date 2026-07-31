-- Apply after v1.sql to construct the canonical persisted v2 starting fixture.
CREATE TABLE apply_operation_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    apply_commit_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    operation_index INTEGER,
    operation_type TEXT,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX idx_apply_operation_audit_commit
    ON apply_operation_audit(apply_commit_id, operation_index);
INSERT INTO apply_operation_audit (
    apply_commit_id, phase, operation_index, operation_type,
    status, payload_json, created_at
) VALUES (
    'fixture-commit-v1', 'apply', 0, 'create_node',
    'completed', '{"fixture":"v2"}', 1700000001.0
);
INSERT INTO graph_store_migrations VALUES (
    2, 'apply_operation_audit',
    '00d2b9ea8869677789618e421f26df74417a3f2809f25a9b54db7b68319321c0',
    1700000001.0
);
PRAGMA user_version=2;
