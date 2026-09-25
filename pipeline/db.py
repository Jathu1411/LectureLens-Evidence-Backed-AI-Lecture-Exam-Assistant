"""
Database persistence layer for pipeline intermediate state.
Supports PostgreSQL (via psycopg v3) with auto-schema creation and incremental checkpointing.
Also provides a fallback SQLite interface when running in standalone mode.
"""

import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from pipeline.config import (
    DB_TYPE,
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
    SQLITE_PATH,
)

logger = logging.getLogger("pipeline.db")


class Database:
    """Handles incremental persistence for runs, segments, slides, and summaries."""

    def __init__(self):
        self.db_type = DB_TYPE
        self._pg_conn = None
        self._sqlite_conn = None
        self._init_connection()

    def _init_connection(self):
        """Attempts to connect to PostgreSQL first, falling back to SQLite if requested/unavailable."""
        if self.db_type == "postgres":
            try:
                import psycopg
                from psycopg.rows import dict_row

                self._pg_conn = psycopg.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    dbname=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD or None,
                    row_factory=dict_row,
                    autocommit=True,
                )
                logger.info(f"Connected to PostgreSQL database '{DB_NAME}' at {DB_HOST}:{DB_PORT}")
                self._init_postgres_schema()
                return
            except Exception as e:
                logger.warning(
                    f"PostgreSQL connection to {DB_NAME} failed ({e}). "
                    f"Falling back to local SQLite at {SQLITE_PATH} to maintain pipeline execution."
                )
                self.db_type = "sqlite"

        # Fallback to SQLite
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._sqlite_conn = sqlite3.connect(str(SQLITE_PATH), check_same_thread=False)
        self._sqlite_conn.row_factory = sqlite3.Row
        logger.info(f"Connected to SQLite database at {SQLITE_PATH}")
        self._init_sqlite_schema()

    def _init_postgres_schema(self):
        """Creates the required tables in PostgreSQL with JSONB columns and proper indexes."""
        with self._pg_conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id VARCHAR(64) PRIMARY KEY,
                video_path TEXT NOT NULL,
                audio_path TEXT,
                status VARCHAR(32) DEFAULT 'pending',
                current_stage VARCHAR(32),
                total_duration FLOAT,
                progress_percent FLOAT DEFAULT 0.0,
                progress_message TEXT DEFAULT '',
                config JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ALTER TABLE runs ADD COLUMN IF NOT EXISTS progress_percent FLOAT DEFAULT 0.0;
            ALTER TABLE runs ADD COLUMN IF NOT EXISTS progress_message TEXT DEFAULT '';

            CREATE TABLE IF NOT EXISTS audio_segments (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE,
                segment_index INT,
                start_time FLOAT NOT NULL,
                end_time FLOAT NOT NULL,
                text TEXT NOT NULL,
                words JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_audio_segments_run_time 
                ON audio_segments(run_id, start_time);

            CREATE TABLE IF NOT EXISTS slides (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE,
                slide_index INT,
                timestamp FLOAT NOT NULL,
                frame_path TEXT NOT NULL,
                ocr_text TEXT,
                ocr_confidence FLOAT,
                source VARCHAR(32) DEFAULT 'tesseract',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_slides_run_time 
                ON slides(run_id, timestamp);

            CREATE TABLE IF NOT EXISTS timeline_entries (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE,
                entry_index INT,
                start_time FLOAT NOT NULL,
                end_time FLOAT NOT NULL,
                slide_id INT,
                transcript_chunk TEXT,
                metadata JSONB
            );
            CREATE INDEX IF NOT EXISTS idx_timeline_run_time 
                ON timeline_entries(run_id, start_time);

            CREATE TABLE IF NOT EXISTS chunk_summaries (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE,
                chunk_index INT NOT NULL,
                start_time FLOAT NOT NULL,
                end_time FLOAT NOT NULL,
                summary_data JSONB NOT NULL,
                raw_llm_response TEXT,
                status VARCHAR(32) DEFAULT 'completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (run_id, chunk_index)
            );

            CREATE TABLE IF NOT EXISTS final_summaries (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE UNIQUE,
                overview TEXT,
                key_points JSONB,
                summary_text TEXT,
                structured_guide JSONB,
                pdf_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            ALTER TABLE slides ADD COLUMN IF NOT EXISTS phash VARCHAR(64);
            ALTER TABLE slides ADD COLUMN IF NOT EXISTS cluster_id INT;
            ALTER TABLE slides ADD COLUMN IF NOT EXISTS roi_bbox JSONB;
            ALTER TABLE slides ADD COLUMN IF NOT EXISTS quality_score FLOAT DEFAULT 0.0;
            ALTER TABLE slides ADD COLUMN IF NOT EXISTS is_diagram BOOLEAN DEFAULT FALSE;
            ALTER TABLE slides ADD COLUMN IF NOT EXISTS first_seen FLOAT;
            ALTER TABLE slides ADD COLUMN IF NOT EXISTS last_seen FLOAT;
            ALTER TABLE slides ADD COLUMN IF NOT EXISTS appearance_count INT DEFAULT 1;

            CREATE TABLE IF NOT EXISTS lecture_windows (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE,
                window_index INT NOT NULL,
                start_seconds FLOAT NOT NULL,
                end_seconds FLOAT NOT NULL,
                effective_start_seconds FLOAT NOT NULL,
                effective_end_seconds FLOAT NOT NULL,
                status VARCHAR(32) DEFAULT 'PENDING',
                error_message TEXT,
                retry_count INT DEFAULT 0,
                timings JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (run_id, window_index)
            );

            CREATE TABLE IF NOT EXISTS semantic_sections (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE,
                window_index INT,
                section_index INT NOT NULL,
                title TEXT,
                start_seconds FLOAT NOT NULL,
                end_seconds FLOAT NOT NULL,
                summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS concepts (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE,
                window_index INT,
                name TEXT NOT NULL,
                category VARCHAR(64) NOT NULL,
                definition TEXT,
                explanation TEXT,
                start_seconds FLOAT NOT NULL,
                end_seconds FLOAT NOT NULL,
                slide_id INT REFERENCES slides(id) ON DELETE SET NULL,
                evidence_references JSONB,
                confidence VARCHAR(16) DEFAULT 'MEDIUM',
                status VARCHAR(32) DEFAULT 'unverified',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS exam_signals (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE,
                window_index INT,
                signal_type VARCHAR(32) NOT NULL,
                text TEXT NOT NULL,
                timestamp FLOAT NOT NULL,
                source_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS verification_records (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE,
                concept_id INT,
                claim TEXT NOT NULL,
                status VARCHAR(32) NOT NULL,
                evidence JSONB,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS lecture_statistics (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(64) REFERENCES runs(id) ON DELETE CASCADE UNIQUE,
                stats_json JSONB NOT NULL,
                real_time_factor FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

    def _init_sqlite_schema(self):
        """Creates equivalent schema in SQLite."""
        cur = self._sqlite_conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            video_path TEXT NOT NULL,
            audio_path TEXT,
            status TEXT DEFAULT 'pending',
            current_stage TEXT,
            total_duration REAL,
            progress_percent REAL DEFAULT 0.0,
            progress_message TEXT DEFAULT '',
            config TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """)
        # Safe migration for existing SQLite database
        try:
            cur.execute("ALTER TABLE runs ADD COLUMN progress_percent REAL DEFAULT 0.0")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE runs ADD COLUMN progress_message TEXT DEFAULT ''")
        except Exception:
            pass
        cur.executescript("""

        CREATE TABLE IF NOT EXISTS audio_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            segment_index INTEGER,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            text TEXT NOT NULL,
            words TEXT,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audio_segments_run_time ON audio_segments(run_id, start_time);

        CREATE TABLE IF NOT EXISTS slides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            slide_index INTEGER,
            timestamp REAL NOT NULL,
            frame_path TEXT NOT NULL,
            ocr_text TEXT,
            ocr_confidence REAL,
            source TEXT DEFAULT 'tesseract',
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_slides_run_time ON slides(run_id, timestamp);

        CREATE TABLE IF NOT EXISTS timeline_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            entry_index INTEGER,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            slide_id INTEGER,
            transcript_chunk TEXT,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS chunk_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            chunk_index INTEGER NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            summary_data TEXT NOT NULL,
            raw_llm_response TEXT,
            status TEXT DEFAULT 'completed',
            created_at TEXT,
            UNIQUE (run_id, chunk_index)
        );

        CREATE TABLE IF NOT EXISTS final_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE,
            overview TEXT,
            key_points TEXT,
            summary_text TEXT,
            structured_guide TEXT,
            pdf_path TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS lecture_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            window_index INTEGER NOT NULL,
            start_seconds REAL NOT NULL,
            end_seconds REAL NOT NULL,
            effective_start_seconds REAL NOT NULL,
            effective_end_seconds REAL NOT NULL,
            status TEXT DEFAULT 'PENDING',
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            timings TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE (run_id, window_index)
        );

        CREATE TABLE IF NOT EXISTS semantic_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            window_index INTEGER,
            section_index INTEGER NOT NULL,
            title TEXT,
            start_seconds REAL NOT NULL,
            end_seconds REAL NOT NULL,
            summary TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            window_index INTEGER,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            definition TEXT,
            explanation TEXT,
            start_seconds REAL NOT NULL,
            end_seconds REAL NOT NULL,
            slide_id INTEGER,
            evidence_references TEXT,
            confidence TEXT DEFAULT 'MEDIUM',
            status TEXT DEFAULT 'unverified',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS exam_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            window_index INTEGER,
            signal_type TEXT NOT NULL,
            text TEXT NOT NULL,
            timestamp REAL NOT NULL,
            source_id TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS verification_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            concept_id INTEGER,
            claim TEXT NOT NULL,
            status TEXT NOT NULL,
            evidence TEXT,
            notes TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS lecture_statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE,
            stats_json TEXT NOT NULL,
            real_time_factor REAL,
            created_at TEXT,
            updated_at TEXT
        );
        """)
        # Safe migrations for slides table in SQLite
        for col_def in [
            ("phash", "TEXT"),
            ("cluster_id", "INTEGER"),
            ("roi_bbox", "TEXT"),
            ("quality_score", "REAL DEFAULT 0.0"),
            ("is_diagram", "INTEGER DEFAULT 0"),
            ("first_seen", "REAL"),
            ("last_seen", "REAL"),
            ("appearance_count", "INTEGER DEFAULT 1"),
        ]:
            try:
                cur.execute(f"ALTER TABLE slides ADD COLUMN {col_def[0]} {col_def[1]}")
            except Exception:
                pass
        self._sqlite_conn.commit()

    # --- Run Management ---

    def create_or_get_run(self, run_id: str, video_path: str, config_dict: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        now = datetime.utcnow().isoformat()
        cfg_json = json.dumps(config_dict or {})

        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
                row = cur.fetchone()
                if row:
                    return dict(row)
                cur.execute(
                    """
                    INSERT INTO runs (id, video_path, status, current_stage, config, created_at, updated_at)
                    VALUES (%s, %s, 'in_progress', 'created', %s, %s, %s)
                    RETURNING *
                    """,
                    (run_id, video_path, cfg_json, now, now)
                )
                return dict(cur.fetchone())
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            cur.execute(
                """
                INSERT INTO runs (id, video_path, status, current_stage, config, created_at, updated_at)
                VALUES (?, ?, 'in_progress', 'created', ?, ?, ?)
                """,
                (run_id, video_path, cfg_json, now, now)
            )
            self._sqlite_conn.commit()
            cur.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            return dict(cur.fetchone())

    def update_run_stage(
        self,
        run_id: str,
        stage: str,
        status: str = "in_progress",
        audio_path: Optional[str] = None,
        duration: Optional[float] = None,
        total_duration: Optional[float] = None,
        progress_percent: Optional[float] = None,
        progress_message: Optional[str] = None,
    ):
        if duration is None and total_duration is not None:
            duration = total_duration
        now = datetime.utcnow().isoformat()
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE runs 
                    SET current_stage = %s, status = %s,
                        audio_path = COALESCE(%s, audio_path),
                        total_duration = COALESCE(%s, total_duration),
                        progress_percent = COALESCE(%s, progress_percent),
                        progress_message = COALESCE(%s, progress_message),
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (stage, status, audio_path, duration, progress_percent, progress_message, now, run_id)
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute(
                """
                UPDATE runs 
                SET current_stage = ?, status = ?,
                    audio_path = COALESCE(?, audio_path),
                    total_duration = COALESCE(?, total_duration),
                    progress_percent = COALESCE(?, progress_percent),
                    progress_message = COALESCE(?, progress_message),
                    updated_at = ?
                WHERE id = ?
                """,
                (stage, status, audio_path, duration, progress_percent, progress_message, now, run_id)
            )
            self._sqlite_conn.commit()

    def update_run_progress(self, run_id: str, percent: float, message: str, stage: Optional[str] = None):
        """Updates progress percentage (0-100) and user-facing status message."""
        now = datetime.utcnow().isoformat()
        pct = max(0.0, min(100.0, float(percent)))
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                if stage:
                    cur.execute(
                        "UPDATE runs SET progress_percent = %s, progress_message = %s, current_stage = %s, updated_at = %s WHERE id = %s",
                        (pct, message, stage, now, run_id)
                    )
                else:
                    cur.execute(
                        "UPDATE runs SET progress_percent = %s, progress_message = %s, updated_at = %s WHERE id = %s",
                        (pct, message, now, run_id)
                    )
        else:
            cur = self._sqlite_conn.cursor()
            if stage:
                cur.execute(
                    "UPDATE runs SET progress_percent = ?, progress_message = ?, current_stage = ?, updated_at = ? WHERE id = ?",
                    (pct, message, stage, now, run_id)
                )
            else:
                cur.execute(
                    "UPDATE runs SET progress_percent = ?, progress_message = ?, updated_at = ? WHERE id = ?",
                    (pct, message, now, run_id)
                )
            self._sqlite_conn.commit()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM runs WHERE id = %s", (run_id,))
                row = cur.fetchone()
                return dict(row) if row else None
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_runs(self) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM runs ORDER BY created_at DESC")
                raw_runs = [dict(r) for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM runs ORDER BY created_at DESC")
            raw_runs = [dict(r) for r in cur.fetchall()]

        # Compute dynamic live progress & statistics
        for r in raw_runs:
            run_id = r["id"]
            slides = self.get_slides(run_id)
            segments = self.get_audio_segments(run_id)
            chunks = self.get_chunk_summaries(run_id)
            total_sec = r.get("total_duration") or 0.0

            r["slides_count"] = len(slides)
            r["segments_count"] = len(segments)
            r["chunks_count"] = len(chunks)

            transcribed_sec = max([s["end_time"] for s in segments], default=0.0)
            r["transcribed_seconds"] = round(transcribed_sec, 1)

            stage = r.get("current_stage", "created")
            status = r.get("status", "pending")

            stored_pct = float(r.get("progress_percent") or 0.0)
            stored_msg = r.get("progress_message") or ""

            # Calculate derived progress percentage if not explicitly recorded
            if status == "completed":
                calc_pct = 100.0
                calc_msg = "Completed • PDF Study Guide Ready"
            elif stage == "ingestion":
                calc_pct = max(stored_pct, 10.0)
                calc_msg = stored_msg or "Extracting audio & probing video frames..."
            elif stage == "slide_detection":
                slide_pct = (max([s["timestamp"] for s in slides], default=0.0) / total_sec) if total_sec > 0 else 0.5
                calc_pct = max(stored_pct, round(10.0 + slide_pct * 15.0, 1))
                calc_msg = stored_msg or f"Detecting slides: {len(slides)} distinct slides identified"
            elif stage == "transcription":
                trans_pct = (transcribed_sec / total_sec) if total_sec > 0 else 0.4
                calc_pct = max(stored_pct, round(25.0 + trans_pct * 30.0, 1))
                calc_msg = stored_msg or f"Transcribing audio: {round(transcribed_sec)}s / {round(total_sec)}s ({int(trans_pct*100)}%)"
            elif stage == "ocr":
                ocr_count = sum(1 for s in slides if s.get("ocr_text"))
                ocr_pct = (ocr_count / max(1, len(slides)))
                calc_pct = max(stored_pct, round(55.0 + ocr_pct * 15.0, 1))
                calc_msg = stored_msg or f"OCR extraction: {ocr_count} of {len(slides)} slides read"
            elif stage == "alignment":
                calc_pct = max(stored_pct, 72.0)
                calc_msg = stored_msg or "Synchronizing spoken speech with active slide frames..."
            elif stage == "summarization":
                calc_pct = max(stored_pct, 85.0)
                calc_msg = stored_msg or "Synthesizing study guide via local Llama 3 Map-Reduce..."
            elif stage == "completed":
                calc_pct = 100.0
                calc_msg = "Completed • PDF Study Guide Ready"
            else:
                calc_pct = stored_pct
                calc_msg = stored_msg or (f"Stage: {stage}")

            r["progress_percent"] = round(calc_pct, 1)
            r["progress_message"] = calc_msg

        return raw_runs

    # --- Incremental Transcription Segments ---

    def get_latest_transcription_time(self, run_id: str) -> float:
        """Returns the max end_time recorded so far to resume Whisper transcription."""
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT MAX(end_time) as max_time FROM audio_segments WHERE run_id = %s", (run_id,))
                row = cur.fetchone()
                return float(row["max_time"]) if row and row["max_time"] is not None else 0.0
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT MAX(end_time) as max_time FROM audio_segments WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            return float(row["max_time"]) if row and row["max_time"] is not None else 0.0

    def insert_audio_segments(self, run_id: str, segments: List[Dict[str, Any]]):
        """Incrementally inserts audio segments."""
        if not segments:
            return
        now = datetime.utcnow().isoformat()
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO audio_segments (run_id, segment_index, start_time, end_time, text, words, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            run_id,
                            s.get("index", 0),
                            s["start"],
                            s["end"],
                            s["text"],
                            json.dumps(s.get("words", [])),
                            now,
                        )
                        for s in segments
                    ],
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.executemany(
                """
                INSERT INTO audio_segments (run_id, segment_index, start_time, end_time, text, words, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        s.get("index", 0),
                        s["start"],
                        s["end"],
                        s["text"],
                        json.dumps(s.get("words", [])),
                        now,
                    )
                    for s in segments
                ],
            )
            self._sqlite_conn.commit()

    def get_audio_segments(self, run_id: str) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM audio_segments WHERE run_id = %s ORDER BY start_time ASC", (run_id,))
                return [dict(r) for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM audio_segments WHERE run_id = ? ORDER BY start_time ASC", (run_id,))
            return [dict(r) for r in cur.fetchall()]

    # --- Incremental Slides Management ---

    def get_latest_slide_timestamp(self, run_id: str) -> float:
        """Returns max slide timestamp to resume slide detection."""
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT MAX(timestamp) as max_time FROM slides WHERE run_id = %s", (run_id,))
                row = cur.fetchone()
                return float(row["max_time"]) if row and row["max_time"] is not None else 0.0
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT MAX(timestamp) as max_time FROM slides WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            return float(row["max_time"]) if row and row["max_time"] is not None else 0.0

    def insert_slide(
        self,
        run_id: str,
        slide_index: int,
        timestamp: float,
        frame_path: str,
        phash: Optional[str] = None,
        cluster_id: Optional[int] = None,
        roi_bbox: Optional[Dict[str, Any]] = None,
        quality_score: float = 0.0,
        is_diagram: bool = False,
        first_seen: Optional[float] = None,
        last_seen: Optional[float] = None,
        appearance_count: int = 1,
    ) -> int:
        now = datetime.utcnow().isoformat()
        first_s = first_seen if first_seen is not None else timestamp
        last_s = last_seen if last_seen is not None else timestamp
        roi_json = json.dumps(roi_bbox) if roi_bbox else None

        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO slides (
                        run_id, slide_index, timestamp, frame_path, phash, cluster_id,
                        roi_bbox, quality_score, is_diagram, first_seen, last_seen, appearance_count, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        run_id, slide_index, timestamp, frame_path, phash, cluster_id,
                        roi_json, quality_score, is_diagram, first_s, last_s, appearance_count, now
                    )
                )
                row = cur.fetchone()
                return row["id"] if row else 0
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute(
                """
                INSERT INTO slides (
                    run_id, slide_index, timestamp, frame_path, phash, cluster_id,
                    roi_bbox, quality_score, is_diagram, first_seen, last_seen, appearance_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, slide_index, timestamp, frame_path, phash, cluster_id,
                    roi_json, quality_score, 1 if is_diagram else 0, first_s, last_s, appearance_count, now
                )
            )
            self._sqlite_conn.commit()
            return cur.lastrowid or 0

    def update_slide_appearance(self, slide_id: int, last_seen: float, appearance_count: int):
        """Updates recurrence for an existing slide cluster."""
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute(
                    "UPDATE slides SET last_seen = %s, appearance_count = %s WHERE id = %s",
                    (last_seen, appearance_count, slide_id)
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute(
                "UPDATE slides SET last_seen = ?, appearance_count = ? WHERE id = ?",
                (last_seen, appearance_count, slide_id)
            )
            self._sqlite_conn.commit()

    def get_slides(self, run_id: str) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM slides WHERE run_id = %s ORDER BY timestamp ASC", (run_id,))
                slides = [dict(r) for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM slides WHERE run_id = ? ORDER BY timestamp ASC", (run_id,))
            slides = [dict(r) for r in cur.fetchall()]

        for s in slides:
            if isinstance(s.get("roi_bbox"), str):
                try:
                    s["roi_bbox"] = json.loads(s["roi_bbox"])
                except Exception:
                    pass
        return slides

    def get_unique_slides(self, run_id: str) -> List[Dict[str, Any]]:
        """Returns distinct slides clustered by cluster_id or slide_index without duplicates."""
        all_slides = self.get_slides(run_id)
        seen_clusters = set()
        unique = []
        for s in all_slides:
            cid = s.get("cluster_id") or s["slide_index"]
            if cid not in seen_clusters:
                seen_clusters.add(cid)
                unique.append(s)
        return unique

    def update_slide_ocr(self, slide_id: int, ocr_text: str, confidence: float, source: str = "tesseract"):
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE slides
                    SET ocr_text = %s, ocr_confidence = %s, source = %s
                    WHERE id = %s
                    """,
                    (ocr_text, confidence, source, slide_id)
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute(
                """
                UPDATE slides
                SET ocr_text = ?, ocr_confidence = ?, source = ?
                WHERE id = ?
                """,
                (ocr_text, confidence, source, slide_id)
            )
            self._sqlite_conn.commit()

    # --- Timeline Alignment ---

    def insert_timeline_entries(self, run_id: str, entries: List[Dict[str, Any]]):
        if not entries:
            return
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("DELETE FROM timeline_entries WHERE run_id = %s", (run_id,))
                cur.executemany(
                    """
                    INSERT INTO timeline_entries (run_id, entry_index, start_time, end_time, slide_id, transcript_chunk, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            run_id,
                            e.get("index", i),
                            e["start_time"],
                            e["end_time"],
                            e.get("slide_id"),
                            e.get("transcript_chunk", ""),
                            json.dumps(e.get("metadata", {})),
                        )
                        for i, e in enumerate(entries)
                    ]
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("DELETE FROM timeline_entries WHERE run_id = ?", (run_id,))
            cur.executemany(
                """
                INSERT INTO timeline_entries (run_id, entry_index, start_time, end_time, slide_id, transcript_chunk, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        e.get("index", i),
                        e["start_time"],
                        e["end_time"],
                        e.get("slide_id"),
                        e.get("transcript_chunk", ""),
                        json.dumps(e.get("metadata", {})),
                    )
                    for i, e in enumerate(entries)
                ]
            )
            self._sqlite_conn.commit()

    def get_timeline_entries(self, run_id: str) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM timeline_entries WHERE run_id = %s ORDER BY start_time ASC", (run_id,))
                return [dict(r) for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM timeline_entries WHERE run_id = ? ORDER BY start_time ASC", (run_id,))
            return [dict(r) for r in cur.fetchall()]

    # --- Map-Reduce Chunk Summaries ---

    def get_completed_chunk_indices(self, run_id: str) -> List[int]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT chunk_index FROM chunk_summaries WHERE run_id = %s ORDER BY chunk_index ASC", (run_id,))
                return [r["chunk_index"] for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT chunk_index FROM chunk_summaries WHERE run_id = ? ORDER BY chunk_index ASC", (run_id,))
            return [r["chunk_index"] for r in cur.fetchall()]

    def upsert_chunk_summary(self, run_id: str, chunk_index: int, start_time: float, end_time: float, summary_data: Dict[str, Any], raw_llm: str = ""):
        now = datetime.utcnow().isoformat()
        sum_json = json.dumps(summary_data)
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chunk_summaries (run_id, chunk_index, start_time, end_time, summary_data, raw_llm_response, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, chunk_index) DO UPDATE
                    SET summary_data = EXCLUDED.summary_data,
                        raw_llm_response = EXCLUDED.raw_llm_response,
                        created_at = EXCLUDED.created_at
                    """,
                    (run_id, chunk_index, start_time, end_time, sum_json, raw_llm, now)
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO chunk_summaries (run_id, chunk_index, start_time, end_time, summary_data, raw_llm_response, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, chunk_index, start_time, end_time, sum_json, raw_llm, now)
            )
            self._sqlite_conn.commit()

    def get_chunk_summaries(self, run_id: str) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM chunk_summaries WHERE run_id = %s ORDER BY chunk_index ASC", (run_id,))
                results = []
                for r in cur.fetchall():
                    d = dict(r)
                    if isinstance(d.get("summary_data"), str):
                        d["summary_data"] = json.loads(d["summary_data"])
                    results.append(d)
                return results
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM chunk_summaries WHERE run_id = ? ORDER BY chunk_index ASC", (run_id,))
            results = []
            for r in cur.fetchall():
                d = dict(r)
                if isinstance(d.get("summary_data"), str):
                    d["summary_data"] = json.loads(d["summary_data"])
                results.append(d)
            return results

    # --- Final Summary & PDF ---

    def upsert_final_summary(self, run_id: str, overview: str, key_points: List[str], summary_text: str, structured_guide: Dict[str, Any], pdf_path: Optional[str] = None):
        now = datetime.utcnow().isoformat()
        kp_json = json.dumps(key_points)
        guide_json = json.dumps(structured_guide)

        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO final_summaries (run_id, overview, key_points, summary_text, structured_guide, pdf_path, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE
                    SET overview = EXCLUDED.overview,
                        key_points = EXCLUDED.key_points,
                        summary_text = EXCLUDED.summary_text,
                        structured_guide = EXCLUDED.structured_guide,
                        pdf_path = COALESCE(EXCLUDED.pdf_path, final_summaries.pdf_path),
                        updated_at = EXCLUDED.updated_at
                    """,
                    (run_id, overview, kp_json, summary_text, guide_json, pdf_path, now, now)
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute(
                """
                INSERT INTO final_summaries (run_id, overview, key_points, summary_text, structured_guide, pdf_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE
                SET overview = excluded.overview,
                    key_points = excluded.key_points,
                    summary_text = excluded.summary_text,
                    structured_guide = excluded.structured_guide,
                    pdf_path = COALESCE(excluded.pdf_path, final_summaries.pdf_path),
                    updated_at = excluded.updated_at
                """,
                (run_id, overview, kp_json, summary_text, guide_json, pdf_path, now, now)
            )
            self._sqlite_conn.commit()

    def get_final_summary(self, run_id: str) -> Optional[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM final_summaries WHERE run_id = %s", (run_id,))
                row = cur.fetchone()
                if not row:
                    return None
                d = dict(row)
                if isinstance(d.get("key_points"), str):
                    d["key_points"] = json.loads(d["key_points"])
                if isinstance(d.get("structured_guide"), str):
                    d["structured_guide"] = json.loads(d["structured_guide"])
                return d
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM final_summaries WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            if isinstance(d.get("key_points"), str):
                d["key_points"] = json.loads(d["key_points"])
            if isinstance(d.get("structured_guide"), str):
                d["structured_guide"] = json.loads(d["structured_guide"])
            return d

    # --- Virtual Windows & Execution State ---

    def create_or_get_windows(self, run_id: str, windows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Inserts planned lecture windows if they do not already exist, returning current window states."""
        existing = self.get_windows(run_id)
        if existing:
            return existing

        now = datetime.utcnow().isoformat()
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO lecture_windows (
                        run_id, window_index, start_seconds, end_seconds,
                        effective_start_seconds, effective_end_seconds, status, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', %s, %s)
                    ON CONFLICT (run_id, window_index) DO NOTHING
                    """,
                    [
                        (
                            run_id,
                            w["window_index"],
                            w["start_seconds"],
                            w["end_seconds"],
                            w["effective_start_seconds"],
                            w["effective_end_seconds"],
                            now,
                            now,
                        )
                        for w in windows
                    ]
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.executemany(
                """
                INSERT OR IGNORE INTO lecture_windows (
                    run_id, window_index, start_seconds, end_seconds,
                    effective_start_seconds, effective_end_seconds, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                [
                    (
                        run_id,
                        w["window_index"],
                        w["start_seconds"],
                        w["end_seconds"],
                        w["effective_start_seconds"],
                        w["effective_end_seconds"],
                        now,
                        now,
                    )
                    for w in windows
                ]
            )
            self._sqlite_conn.commit()
        return self.get_windows(run_id)

    def update_window_status(
        self,
        run_id: str,
        window_index: int,
        status: str,
        error_message: Optional[str] = None,
        timings: Optional[Dict[str, Any]] = None,
    ):
        now = datetime.utcnow().isoformat()
        timings_json = json.dumps(timings) if timings else None
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE lecture_windows
                    SET status = %s,
                        error_message = %s,
                        timings = COALESCE(%s, timings),
                        updated_at = %s
                    WHERE run_id = %s AND window_index = %s
                    """,
                    (status, error_message, timings_json, now, run_id, window_index)
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute(
                """
                UPDATE lecture_windows
                SET status = ?,
                    error_message = ?,
                    timings = COALESCE(?, timings),
                    updated_at = ?
                WHERE run_id = ? AND window_index = ?
                """,
                (status, error_message, timings_json, now, run_id, window_index)
            )
            self._sqlite_conn.commit()

    def get_windows(self, run_id: str) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM lecture_windows WHERE run_id = %s ORDER BY window_index ASC", (run_id,))
                rows = [dict(r) for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM lecture_windows WHERE run_id = ? ORDER BY window_index ASC", (run_id,))
            rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            if isinstance(r.get("timings"), str):
                try:
                    r["timings"] = json.loads(r["timings"])
                except Exception:
                    pass
        return rows

    def get_window(self, run_id: str, window_index: int) -> Optional[Dict[str, Any]]:
        windows = self.get_windows(run_id)
        for w in windows:
            if w["window_index"] == window_index:
                return w
        return None

    # --- Semantic Sections ---

    def insert_semantic_sections(self, run_id: str, sections: List[Dict[str, Any]]):
        if not sections:
            return
        now = datetime.utcnow().isoformat()
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO semantic_sections (
                        run_id, window_index, section_index, title, start_seconds, end_seconds, summary, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            run_id,
                            s.get("window_index", 0),
                            s.get("section_index", i + 1),
                            s.get("title", ""),
                            s["start_seconds"],
                            s["end_seconds"],
                            s.get("summary", ""),
                            now,
                        )
                        for i, s in enumerate(sections)
                    ]
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.executemany(
                """
                INSERT INTO semantic_sections (
                    run_id, window_index, section_index, title, start_seconds, end_seconds, summary, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        s.get("window_index", 0),
                        s.get("section_index", i + 1),
                        s.get("title", ""),
                        s["start_seconds"],
                        s["end_seconds"],
                        s.get("summary", ""),
                        now,
                    )
                    for i, s in enumerate(sections)
                ]
            )
            self._sqlite_conn.commit()

    def get_semantic_sections(self, run_id: str, window_index: Optional[int] = None) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                if window_index is not None:
                    cur.execute(
                        "SELECT * FROM semantic_sections WHERE run_id = %s AND window_index = %s ORDER BY start_seconds ASC",
                        (run_id, window_index)
                    )
                else:
                    cur.execute("SELECT * FROM semantic_sections WHERE run_id = %s ORDER BY start_seconds ASC", (run_id,))
                return [dict(r) for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            if window_index is not None:
                cur.execute(
                    "SELECT * FROM semantic_sections WHERE run_id = ? AND window_index = ? ORDER BY start_seconds ASC",
                    (run_id, window_index)
                )
            else:
                cur.execute("SELECT * FROM semantic_sections WHERE run_id = ? ORDER BY start_seconds ASC", (run_id,))
            return [dict(r) for r in cur.fetchall()]

    # --- Structured Concepts & Knowledge ---

    def insert_concepts(self, run_id: str, concepts: List[Dict[str, Any]]):
        if not concepts:
            return
        now = datetime.utcnow().isoformat()
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO concepts (
                        run_id, window_index, name, category, definition, explanation,
                        start_seconds, end_seconds, slide_id, evidence_references, confidence, status, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            run_id,
                            c.get("window_index", 0),
                            c["name"],
                            c.get("category", "concept"),
                            c.get("definition", ""),
                            c.get("explanation", ""),
                            c.get("start_seconds", 0.0),
                            c.get("end_seconds", 0.0),
                            c.get("slide_id"),
                            json.dumps(c.get("evidence_references", [])),
                            c.get("confidence", "MEDIUM"),
                            c.get("status", "unverified"),
                            now,
                        )
                        for c in concepts
                    ]
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.executemany(
                """
                INSERT INTO concepts (
                    run_id, window_index, name, category, definition, explanation,
                    start_seconds, end_seconds, slide_id, evidence_references, confidence, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        c.get("window_index", 0),
                        c["name"],
                        c.get("category", "concept"),
                        c.get("definition", ""),
                        c.get("explanation", ""),
                        c.get("start_seconds", 0.0),
                        c.get("end_seconds", 0.0),
                        c.get("slide_id"),
                        json.dumps(c.get("evidence_references", [])),
                        c.get("confidence", "MEDIUM"),
                        c.get("status", "unverified"),
                        now,
                    )
                    for c in concepts
                ]
            )
            self._sqlite_conn.commit()

    def get_concepts(self, run_id: str, window_index: Optional[int] = None) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                if window_index is not None:
                    cur.execute(
                        "SELECT * FROM concepts WHERE run_id = %s AND window_index = %s ORDER BY start_seconds ASC",
                        (run_id, window_index)
                    )
                else:
                    cur.execute("SELECT * FROM concepts WHERE run_id = %s ORDER BY start_seconds ASC", (run_id,))
                rows = [dict(r) for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            if window_index is not None:
                cur.execute(
                    "SELECT * FROM concepts WHERE run_id = ? AND window_index = ? ORDER BY start_seconds ASC",
                    (run_id, window_index)
                )
            else:
                cur.execute("SELECT * FROM concepts WHERE run_id = ? ORDER BY start_seconds ASC", (run_id,))
            rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            if isinstance(r.get("evidence_references"), str):
                try:
                    r["evidence_references"] = json.loads(r["evidence_references"])
                except Exception:
                    pass
        return rows

    # --- Lecturer Emphasis Signals ---

    def insert_exam_signals(self, run_id: str, signals: List[Dict[str, Any]]):
        if not signals:
            return
        now = datetime.utcnow().isoformat()
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO exam_signals (run_id, window_index, signal_type, text, timestamp, source_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            run_id,
                            s.get("window_index", 0),
                            s["signal_type"],
                            s["text"],
                            s["timestamp"],
                            s.get("source_id", ""),
                            now,
                        )
                        for s in signals
                    ]
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.executemany(
                """
                INSERT INTO exam_signals (run_id, window_index, signal_type, text, timestamp, source_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        s.get("window_index", 0),
                        s["signal_type"],
                        s["text"],
                        s["timestamp"],
                        s.get("source_id", ""),
                        now,
                    )
                    for s in signals
                ]
            )
            self._sqlite_conn.commit()

    def get_exam_signals(self, run_id: str) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM exam_signals WHERE run_id = %s ORDER BY timestamp ASC", (run_id,))
                return [dict(r) for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM exam_signals WHERE run_id = ? ORDER BY timestamp ASC", (run_id,))
            return [dict(r) for r in cur.fetchall()]

    # --- Verification Records ---

    def insert_verification_records(self, run_id: str, records: List[Dict[str, Any]]):
        if not records:
            return
        now = datetime.utcnow().isoformat()
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO verification_records (run_id, concept_id, claim, status, evidence, notes, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            run_id,
                            r.get("concept_id"),
                            r["claim"],
                            r["status"],
                            json.dumps(r.get("evidence", [])),
                            r.get("notes", ""),
                            now,
                        )
                        for r in records
                    ]
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.executemany(
                """
                INSERT INTO verification_records (run_id, concept_id, claim, status, evidence, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        r.get("concept_id"),
                        r["claim"],
                        r["status"],
                        json.dumps(r.get("evidence", [])),
                        r.get("notes", ""),
                        now,
                    )
                    for r in records
                ]
            )
            self._sqlite_conn.commit()

    def get_verification_records(self, run_id: str) -> List[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM verification_records WHERE run_id = %s ORDER BY id ASC", (run_id,))
                rows = [dict(r) for r in cur.fetchall()]
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM verification_records WHERE run_id = ? ORDER BY id ASC", (run_id,))
            rows = [dict(r) for r in cur.fetchall()]

        for r in rows:
            if isinstance(r.get("evidence"), str):
                try:
                    r["evidence"] = json.loads(r["evidence"])
                except Exception:
                    pass
        return rows

    # --- Lecture Statistics ---

    def upsert_lecture_statistics(self, run_id: str, stats_json: Dict[str, Any], real_time_factor: float):
        now = datetime.utcnow().isoformat()
        s_json = json.dumps(stats_json)
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO lecture_statistics (run_id, stats_json, real_time_factor, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE
                    SET stats_json = EXCLUDED.stats_json,
                        real_time_factor = EXCLUDED.real_time_factor,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (run_id, s_json, real_time_factor, now, now)
                )
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute(
                """
                INSERT INTO lecture_statistics (run_id, stats_json, real_time_factor, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE
                SET stats_json = excluded.stats_json,
                    real_time_factor = excluded.real_time_factor,
                    updated_at = excluded.updated_at
                """,
                (run_id, s_json, real_time_factor, now, now)
            )
            self._sqlite_conn.commit()

    def get_lecture_statistics(self, run_id: str) -> Optional[Dict[str, Any]]:
        if self.db_type == "postgres":
            with self._pg_conn.cursor() as cur:
                cur.execute("SELECT * FROM lecture_statistics WHERE run_id = %s", (run_id,))
                row = cur.fetchone()
                if not row:
                    return None
                d = dict(row)
                if isinstance(d.get("stats_json"), str):
                    d["stats_json"] = json.loads(d["stats_json"])
                return d
        else:
            cur = self._sqlite_conn.cursor()
            cur.execute("SELECT * FROM lecture_statistics WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            if isinstance(d.get("stats_json"), str):
                d["stats_json"] = json.loads(d["stats_json"])
            return d

    def cancel_run(self, run_id: str) -> bool:
        """Marks an active run as cancelled."""
        self.update_run_stage(
            run_id=run_id,
            stage="cancelled",
            status="failed",
            progress_message="Cancelled by user",
        )
        return True

    def delete_run(self, run_id: str, remove_artifacts: bool = True) -> bool:
        """Deletes a run and all its associated records from all database tables and filesystem."""
        try:
            if self.db_type == "postgres":
                with self._pg_conn.cursor() as cur:
                    cur.execute("""
                        SELECT table_name 
                        FROM information_schema.columns 
                        WHERE table_schema = 'public' AND column_name = 'run_id'
                    """)
                    rows = cur.fetchall()
                    for r in rows:
                        t = r["table_name"] if isinstance(r, dict) else r[0]
                        cur.execute(f"DELETE FROM {t} WHERE run_id = %s", (run_id,))
                    cur.execute("DELETE FROM runs WHERE id = %s", (run_id,))
            else:
                cur = self._sqlite_conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in cur.fetchall()]
                for t in tables:
                    if t == "runs" or t.startswith("sqlite_"):
                        continue
                    cur.execute(f"PRAGMA table_info({t})")
                    cols = [c[1] for c in cur.fetchall()]
                    if "run_id" in cols:
                        cur.execute(f"DELETE FROM {t} WHERE run_id = ?", (run_id,))
                cur.execute("DELETE FROM runs WHERE id = ?", (run_id,))
                self._sqlite_conn.commit()

            if remove_artifacts:
                from pipeline.config import OUTPUT_DIR
                run_dir = Path(OUTPUT_DIR) / run_id
                if run_dir.exists() and run_dir.is_dir():
                    shutil.rmtree(run_dir, ignore_errors=True)

            logger.info(f"Run '{run_id}' successfully deleted from database and filesystem.")
            return True
        except Exception as e:
            logger.error(f"Error deleting run '{run_id}': {e}", exc_info=True)
            return False

