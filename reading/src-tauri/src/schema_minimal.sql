CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT DEFAULT '未知作者',
            file_type TEXT NOT NULL,
            raw_content TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paragraphs (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chapter_id TEXT DEFAULT 'ch_1',
            order_index INTEGER NOT NULL,
            raw_text TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS sentences (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            paragraph_id TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            original TEXT NOT NULL,
            translation TEXT,
            deep_analysis_json TEXT,
            updated_at TEXT,
            FOREIGN KEY (doc_id) REFERENCES documents (id) ON DELETE CASCADE,
            FOREIGN KEY (paragraph_id) REFERENCES paragraphs (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS glossary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            term TEXT NOT NULL,
            category TEXT DEFAULT '专有名词',
            canonical_translation TEXT NOT NULL,
            notes TEXT,
            FOREIGN KEY (doc_id) REFERENCES documents (id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS vocabulary_book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            pos TEXT,
            translation TEXT NOT NULL,
            sentence_context TEXT,
            sentence_id TEXT,
            cultural_background TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sentences_doc ON sentences(doc_id);
        CREATE INDEX IF NOT EXISTS idx_sentences_para ON sentences(paragraph_id);
        CREATE INDEX IF NOT EXISTS idx_paragraphs_doc ON paragraphs(doc_id);
