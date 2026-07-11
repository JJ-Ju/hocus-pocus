
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    root_path TEXT,
    latest_revision INTEGER NOT NULL,
    live_revision INTEGER,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_root_path ON documents(root_path);
CREATE TABLE IF NOT EXISTS document_versions (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    live_revision INTEGER,
    content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(document_id, document_revision)
);
CREATE INDEX IF NOT EXISTS idx_document_versions_document
    ON document_versions(document_id, document_revision);
CREATE TABLE IF NOT EXISTS nodes (
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    root_path TEXT,
    node_uid TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT,
    type_name TEXT,
    category TEXT,
    parent_path TEXT,
    is_network INTEGER NOT NULL DEFAULT 0,
    flags_json TEXT NOT NULL,
    material_path TEXT,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(document_id, node_uid)
);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type_name);
CREATE INDEX IF NOT EXISTS idx_nodes_category ON nodes(category);
CREATE INDEX IF NOT EXISTS idx_nodes_root_path ON nodes(root_path);
CREATE TABLE IF NOT EXISTS edges (
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    edge_uid TEXT NOT NULL,
    kind TEXT NOT NULL,
    from_node_uid TEXT,
    to_node_uid TEXT,
    from_json TEXT NOT NULL,
    to_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(document_id, edge_uid)
);
CREATE TABLE IF NOT EXISTS parameter_bindings (
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    binding_uid TEXT NOT NULL,
    node_uid TEXT NOT NULL,
    parm_name TEXT NOT NULL,
    value_mode TEXT NOT NULL,
    value_json TEXT,
    expression TEXT,
    expression_language TEXT,
    channel_reference TEXT,
    code_blob_uid TEXT,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(document_id, binding_uid)
);
CREATE INDEX IF NOT EXISTS idx_parameter_bindings_node
    ON parameter_bindings(node_uid, parm_name);
CREATE TABLE IF NOT EXISTS code_blobs (
    document_id TEXT NOT NULL,
    document_revision INTEGER NOT NULL,
    code_blob_uid TEXT NOT NULL,
    language TEXT NOT NULL,
    target_json TEXT NOT NULL,
    body TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    PRIMARY KEY(document_id, code_blob_uid)
);
CREATE TABLE IF NOT EXISTS checkouts (
    checkout_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    document_kind TEXT NOT NULL,
    root_path TEXT,
    baseline_document_json TEXT NOT NULL,
    working_document_json TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkouts_document ON checkouts(document_id);
CREATE TABLE IF NOT EXISTS apply_commits (
    apply_commit_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    root_path TEXT,
    baseline_document_revision INTEGER,
    applied_document_revision INTEGER,
    mode TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS live_sync_state (
    scope_key TEXT PRIMARY KEY,
    dirty INTEGER NOT NULL DEFAULT 1,
    last_event TEXT,
    last_marked_revision INTEGER,
    last_synced_live_revision INTEGER,
    updated_at REAL NOT NULL
);
CREATE TABLE graph_store_migrations (version INTEGER PRIMARY KEY CHECK(version > 0), name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at REAL NOT NULL);
INSERT INTO graph_store_migrations VALUES (1, 'initial_graph_store', '7c5956eeb0a0877ee9761e821f18e09a9770d3ed2c5aa9820f3c232739f3b03a', 1700000000.0);
PRAGMA user_version=1;
INSERT INTO documents (document_id, kind, root_path, latest_revision, live_revision, content_hash, payload_json, source, created_at, updated_at) VALUES ('fixture:/geo', 'network', '/obj/geo', 1, 7, 'fixture-hash', '{"documentId":"fixture:/geo","kind":"network"}', 'fixture', 1700000000.0, 1700000000.0);
