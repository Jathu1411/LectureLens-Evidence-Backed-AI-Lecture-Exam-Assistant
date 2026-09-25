"use client";

import { useEffect, useState, use } from "react";
import Link from "next/link";
import { ProgressRing, ProgressBar } from "../../components/ProgressIndicator";

interface Slide {
  id: number;
  slide_index: number;
  timestamp: number;
  frame_path: string;
  ocr_text: string | null;
  ocr_confidence: number | null;
  source: string;
}

interface TimelineEntry {
  id: number;
  entry_index: number;
  start_time: number;
  end_time: number;
  slide_id: number | null;
  transcript_chunk: string;
  metadata: any;
}

interface ChunkSummary {
  id: number;
  chunk_index: number;
  start_time: number;
  end_time: number;
  summary_data: any;
  raw_llm_response: string;
}

interface FinalSummary {
  overview: string;
  key_points: string[];
  summary_text: string;
  structured_guide: any;
  pdf_path: string | null;
}

interface RunDetails {
  run: {
    id: string;
    video_path: string;
    audio_path: string | null;
    status: string;
    current_stage: string;
    total_duration: number | null;
    progress_percent?: number;
    progress_message?: string;
  };
  slides: Slide[];
  timeline: TimelineEntry[];
  chunks: ChunkSummary[];
  summary: FinalSummary | null;
}

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [data, setData] = useState<RunDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"guide" | "slides" | "timeline" | "control">("guide");
  const [actionMsg, setActionMsg] = useState("");
  const [isExecuting, setIsExecuting] = useState(false);

  const fetchDetails = async () => {
    try {
      const res = await fetch(`/api/runs/${id}`);
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch (err) {
      console.error("Failed to fetch run details:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDetails();
    const interval = setInterval(fetchDetails, 5000);
    return () => clearInterval(interval);
  }, [id]);

  const handleTriggerStage = async (stage: string) => {
    setIsExecuting(true);
    setActionMsg(`Starting stage: ${stage}...`);
    try {
      const res = await fetch("/api/pipeline/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          runId: id,
          videoPath: data?.run?.video_path,
          stage,
          resume: true,
        }),
      });
      if (res.ok) {
        setActionMsg(`Stage '${stage}' launched in background!`);
        fetchDetails();
      } else {
        setActionMsg(`Failed to launch stage: ${stage}`);
      }
    } catch (e: any) {
      setActionMsg(`Error: ${e.message}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleCancelRun = async () => {
    if (!window.confirm(`Are you sure you want to stop the active pipeline for "${id}"?`)) return;
    setIsExecuting(true);
    setActionMsg(`Stopping pipeline for ${id}...`);
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
      if (res.ok) {
        setActionMsg(`Pipeline cancelled.`);
        fetchDetails();
      } else {
        setActionMsg(`Failed to cancel pipeline.`);
      }
    } catch (e: any) {
      setActionMsg(`Error: ${e.message}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleDeleteRun = async () => {
    if (!window.confirm(`Are you sure you want to permanently delete run "${id}" and all its slides, study guides, and data? This action cannot be undone.`)) return;
    setIsExecuting(true);
    setActionMsg(`Deleting run ${id}...`);
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (res.ok) {
        window.location.href = "/";
      } else {
        setActionMsg(`Failed to delete run.`);
        setIsExecuting(false);
      }
    } catch (e: any) {
      setActionMsg(`Error: ${e.message}`);
      setIsExecuting(false);
    }
  };

  if (loading) {
    return (
      <main className="app-container" style={{ padding: "80px 0", textAlign: "center" }}>
        <p style={{ color: "var(--text-secondary)" }}>Loading run details for {id}...</p>
      </main>
    );
  }

  if (!data || !data.run) {
    return (
      <main className="app-container" style={{ padding: "80px 0", textAlign: "center" }}>
        <h2>Run Not Found</h2>
        <p style={{ color: "var(--text-secondary)", margin: "12px 0 24px" }}>
          No run with ID "{id}" was found in the database.
        </p>
        <Link href="/" className="btn btn-primary">Return to Dashboard</Link>
      </main>
    );
  }

  const { run, slides, timeline, summary } = data;

  const formatSec = (seconds: number) => {
    const s = Math.floor(seconds);
    const m = Math.floor(s / 60);
    const h = Math.floor(m / 60);
    return `${h > 0 ? `${h}h ` : ""}${m % 60}m ${s % 60}s`;
  };

  return (
    <main className="app-container">
      {/* Navbar */}
      <header className="navbar">
        <div className="nav-brand">
          <Link href="/" style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ color: "var(--text-muted)", fontSize: 18 }}>&larr;</span>
            <div className="brand-icon">L</div>
            <span className="brand-title">Lecture Notes Guide</span>
          </Link>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          {run.status === "in_progress" && (
            <button
              type="button"
              className="btn btn-secondary"
              style={{ color: "#fb7185", borderColor: "rgba(244,63,94,0.3)" }}
              onClick={handleCancelRun}
              disabled={isExecuting}
              title="Stop running pipeline"
            >
              ⏹ Stop Run
            </button>
          )}

          <button
            type="button"
            className="btn btn-secondary"
            style={{ color: "#f87171", borderColor: "rgba(239,68,68,0.3)" }}
            onClick={handleDeleteRun}
            disabled={isExecuting}
            title="Delete this run and all data"
          >
            🗑 Delete Run
          </button>

          {summary?.pdf_path ? (
            <a
              id="download-pdf-btn"
              href={`/api/runs/${id}/pdf`}
              download
              className="btn btn-primary"
            >
              📄 Download PDF
            </a>
          ) : (
            <button
              id="generate-pdf-btn"
              className="btn btn-secondary"
              onClick={() => handleTriggerStage("export-pdf")}
              disabled={isExecuting}
            >
              Generate PDF
            </button>
          )}
        </div>
      </header>

      {/* Header Info Card */}
      <section className="hero-card" style={{ padding: "24px 32px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
            <ProgressRing
              percent={run.progress_percent ?? (run.status === "completed" ? 100 : 0)}
              size={60}
              strokeWidth={5}
              isRunning={run.status === "in_progress"}
              status={run.status}
            />
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
                <h1 style={{ fontSize: 24, fontWeight: 800 }}>{id}</h1>
                <span className={`stage-status-tag tag-${run.status === "completed" ? "completed" : run.status === "failed" ? "failed" : "running"}`}>
                  {run.status.toUpperCase()}
                </span>
                {run.status === "in_progress" && <span className="live-pulse" title="Live processing active" />}
              </div>
              <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                Source: <strong>{run.video_path.split("/").pop()}</strong> &bull; Total Duration: <strong>{formatSec(run.total_duration || 0)}</strong> &bull; Current Stage: <strong>{run.current_stage}</strong>
              </p>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <button
              id="resume-pipeline-btn"
              className="btn btn-primary btn-sm"
              onClick={() => handleTriggerStage("all")}
              disabled={isExecuting}
            >
              ▶ Resume / Run Full Pipeline
            </button>
          </div>
        </div>

        {/* Live Progress Bar */}
        <div style={{ marginTop: 18 }}>
          <ProgressBar
            percent={run.progress_percent ?? (run.status === "completed" ? 100 : 0)}
            message={run.progress_message || (run.status === "in_progress" ? `Active Stage: ${run.current_stage}` : undefined)}
            isRunning={run.status === "in_progress"}
            status={run.status}
          />
        </div>

        {actionMsg && (
          <div style={{ marginTop: 14, padding: "10px 14px", background: "rgba(99, 102, 241, 0.15)", border: "1px solid rgba(99, 102, 241, 0.3)", borderRadius: 8, fontSize: 12, color: "#a5b4fc" }}>
            {actionMsg}
          </div>
        )}
      </section>

      {/* Tab Navigation */}
      <nav style={{ display: "flex", gap: 8, marginBottom: 24, borderBottom: "1px solid var(--border-subtle)", paddingBottom: 8 }} aria-label="Run view navigation">
        <button
          id="tab-guide-btn"
          className={`btn ${activeTab === "guide" ? "btn-primary" : "btn-secondary"} btn-sm`}
          onClick={() => setActiveTab("guide")}
        >
          📖 Comprehensive Study Guide
        </button>
        <button
          id="tab-slides-btn"
          className={`btn ${activeTab === "slides" ? "btn-primary" : "btn-secondary"} btn-sm`}
          onClick={() => setActiveTab("slides")}
        >
          🖼 Slide Gallery ({slides.length})
        </button>
        <button
          id="tab-timeline-btn"
          className={`btn ${activeTab === "timeline" ? "btn-primary" : "btn-secondary"} btn-sm`}
          onClick={() => setActiveTab("timeline")}
        >
          ⏱ Timeline & Audio Sync ({timeline.length})
        </button>
        <button
          id="tab-control-btn"
          className={`btn ${activeTab === "control" ? "btn-primary" : "btn-secondary"} btn-sm`}
          onClick={() => setActiveTab("control")}
        >
          ⚙ Stage Controls
        </button>
      </nav>

      {/* TAB 1: STUDY GUIDE */}
      {activeTab === "guide" && (
        <div>
          {summary ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
              {/* Executive Overview */}
              <section className="glass-panel" aria-labelledby="overview-title">
                <div className="panel-header">
                  <h2 className="panel-title" id="overview-title">Executive Overview</h2>
                </div>
                <p style={{ lineHeight: 1.7, color: "#e2e8f0" }}>{summary.overview}</p>
              </section>

              {/* Key Takeaways */}
              {summary.key_points && summary.key_points.length > 0 && (
                <section className="glass-panel" aria-labelledby="takeaways-title">
                  <div className="panel-header">
                    <h2 className="panel-title" id="takeaways-title">Key Takeaways & Core Insights</h2>
                  </div>
                  <div className="key-points-grid">
                    {summary.key_points.map((pt, idx) => (
                      <div key={idx} className="key-point-card">
                        <strong>Takeaway {idx + 1}:</strong> {pt}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* Full In-Depth Notes */}
              <section className="glass-panel" aria-labelledby="notes-title">
                <div className="panel-header">
                  <h2 className="panel-title" id="notes-title">Synthesized Lecture Notes & Modules</h2>
                </div>
                <div
                  style={{
                    lineHeight: 1.7,
                    whiteSpace: "pre-wrap",
                    fontFamily: "var(--font-sans)",
                    color: "#cbd5e1",
                  }}
                >
                  {summary.summary_text}
                </div>
              </section>
            </div>
          ) : (
            <section className="glass-panel" style={{ textAlign: "center", padding: "60px 20px" }}>
              <p style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>Study Guide Not Generated Yet</p>
              <p style={{ color: "var(--text-secondary)", marginBottom: 20 }}>
                Run the Map-Reduce summarization stage using local Llama 3 to compile the comprehensive notes.
              </p>
              <button
                id="run-summarize-btn"
                className="btn btn-primary"
                onClick={() => handleTriggerStage("summarize")}
                disabled={isExecuting}
              >
                Run Map-Reduce Summarization Now
              </button>
            </section>
          )}
        </div>
      )}

      {/* TAB 2: SLIDE GALLERY */}
      {activeTab === "slides" && (
        <section className="glass-panel">
          <div className="panel-header">
            <h2 className="panel-title">Detected Keyframe Slides ({slides.length})</h2>
            <button
              id="detect-slides-btn"
              className="btn btn-secondary btn-sm"
              onClick={() => handleTriggerStage("slides")}
              disabled={isExecuting}
            >
              Re-run Slide Detection
            </button>
          </div>

          {slides.length === 0 ? (
            <p style={{ color: "var(--text-muted)", padding: "40px 0", textAlign: "center" }}>
              No slides detected yet. Trigger Stage 2: Slide Detection.
            </p>
          ) : (
            <div className="slides-grid">
              {slides.map((s) => {
                const filename = s.frame_path.split("/").pop();
                return (
                  <div key={s.id} className="slide-grid-card">
                    <img
                      src={`/api/slides/${id}/${filename}`}
                      alt={`Slide ${s.slide_index}`}
                      className="slide-grid-img"
                    />
                    <div className="slide-grid-body">
                      <div className="slide-grid-title">
                        <span>Slide {s.slide_index}</span>
                        <span style={{ color: "var(--accent-cyan)", fontSize: 11 }}>
                          {formatSec(s.timestamp)}
                        </span>
                      </div>
                      <div className="slide-grid-ocr">
                        {s.ocr_text || "No text detected."}
                      </div>
                      <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-muted)" }}>
                        Source: {s.source}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* TAB 3: TIMELINE */}
      {activeTab === "timeline" && (
        <section className="glass-panel">
          <div className="panel-header">
            <h2 className="panel-title">Synchronized Timeline ({timeline.length} intervals)</h2>
            <button
              id="align-timeline-btn"
              className="btn btn-secondary btn-sm"
              onClick={() => handleTriggerStage("align")}
              disabled={isExecuting}
            >
              Re-align Timeline
            </button>
          </div>

          {timeline.length === 0 ? (
            <p style={{ color: "var(--text-muted)", padding: "40px 0", textAlign: "center" }}>
              Timeline has not been aligned yet.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {timeline.map((item) => {
                let meta = item.metadata;
                if (typeof meta === "string") {
                  try { meta = JSON.parse(meta); } catch {}
                }
                return (
                  <div
                    key={item.id}
                    style={{
                      padding: "16px",
                      background: "rgba(255, 255, 255, 0.02)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--radius-md)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 12, color: "var(--accent-cyan)" }}>
                      <span>
                        ⏱ <strong>{formatSec(item.start_time)}</strong> &rarr; <strong>{formatSec(item.end_time)}</strong>
                      </span>
                      {meta?.slide_index && (
                        <span>Slide Ref: <strong>Slide {meta.slide_index}</strong></span>
                      )}
                    </div>
                    {meta?.slide_ocr_text && (
                      <div style={{ padding: "8px 12px", background: "rgba(0,0,0,0.3)", borderRadius: 6, fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>
                        <strong>Slide Content:</strong> {meta.slide_ocr_text}
                      </div>
                    )}
                    <p style={{ fontSize: 14, color: "#f1f5f9", lineHeight: 1.6 }}>
                      {item.transcript_chunk || <span style={{ color: "var(--text-muted)" }}>[Silence / Music]</span>}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* TAB 4: STAGE CONTROL */}
      {activeTab === "control" && (
        <section className="glass-panel">
          <div className="panel-header">
            <h2 className="panel-title">Independent Stage Execution & Recovery</h2>
          </div>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, marginBottom: 20 }}>
            Re-run any single failed stage independently or resume progress seamlessly without repeating earlier stages.
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
            <div className="stage-item" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <div className="stage-name">Stage 1: Ingestion & Audio Extract</div>
              <div className="stage-desc" style={{ marginBottom: 12 }}>FFmpeg 16kHz mono audio extraction</div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerStage("ingest")}
                disabled={isExecuting}
              >
                Run Ingestion
              </button>
            </div>

            <div className="stage-item" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <div className="stage-name">Stage 2: Slide Detection</div>
              <div className="stage-desc" style={{ marginBottom: 12 }}>SSIM & perceptual hash frame transitions</div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerStage("slides")}
                disabled={isExecuting}
              >
                Run Slide Detection
              </button>
            </div>

            <div className="stage-item" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <div className="stage-name">Stage 3: Faster-Whisper ASR</div>
              <div className="stage-desc" style={{ marginBottom: 12 }}>Local Whisper speech transcription</div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerStage("transcribe")}
                disabled={isExecuting}
              >
                Run Transcription
              </button>
            </div>

            <div className="stage-item" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <div className="stage-name">Stage 4: Tesseract OCR + Vision</div>
              <div className="stage-desc" style={{ marginBottom: 12 }}>Optical character recognition on slides</div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerStage("ocr")}
                disabled={isExecuting}
              >
                Run OCR
              </button>
            </div>

            <div className="stage-item" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <div className="stage-name">Stage 5: Alignment</div>
              <div className="stage-desc" style={{ marginBottom: 12 }}>Synchronize speech transcript & slide timeline</div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerStage("align")}
                disabled={isExecuting}
              >
                Run Alignment
              </button>
            </div>

            <div className="stage-item" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <div className="stage-name">Stage 6: Map-Reduce Summarizer</div>
              <div className="stage-desc" style={{ marginBottom: 12 }}>Ollama Llama 3 chunk & synthesis prompts</div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerStage("summarize")}
                disabled={isExecuting}
              >
                Run Summarizer
              </button>
            </div>

            <div className="stage-item" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <div className="stage-name">Stage 7: WeasyPrint PDF Export</div>
              <div className="stage-desc" style={{ marginBottom: 12 }}>Compile HTML/CSS template to final PDF</div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleTriggerStage("export-pdf")}
                disabled={isExecuting}
              >
                Export PDF
              </button>
            </div>
          </div>
        </section>
      )}
    </main>
  );
}
