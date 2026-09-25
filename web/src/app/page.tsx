"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ProgressRing, ProgressBar } from "./components/ProgressIndicator";
import { FilePicker } from "./components/FilePicker";

interface Run {
  id: string;
  video_path: string;
  audio_path: string | null;
  status: string;
  current_stage: string;
  total_duration: number | null;
  progress_percent?: number;
  progress_message?: string;
  slides_count?: number;
  segments_count?: number;
  chunks_count?: number;
  transcribed_seconds?: number;
  created_at: string;
  updated_at: string;
}

const STAGES = [
  { id: "ingestion", name: "1. Ingestion", desc: "FFmpeg 16kHz audio extraction & frame sampling" },
  { id: "slide_detection", name: "2. Slide Detection", desc: "OpenCV SSIM perceptual transition filter" },
  { id: "transcription", name: "3. Transcription", desc: "Faster-Whisper (language='en', vad_filter=True)" },
  { id: "ocr", name: "4. Visual Path", desc: "Tesseract OCR with Ollama vision fallback" },
  { id: "alignment", name: "5. Alignment", desc: "Timeline synchronization of speech & slides" },
  { id: "summarization", name: "6. Summarization", desc: "10-15 min slide-aware Map-Reduce with Llama 3" },
  { id: "completed", name: "7. PDF Output", desc: "WeasyPrint academic study guide compilation" },
];

export default function Dashboard() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [videoPath, setVideoPath] = useState<string>("");
  const [runId, setRunId] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [message, setMessage] = useState<string>("");

  const fetchRuns = async () => {
    try {
      const res = await fetch("/api/runs");
      if (res.ok) {
        const data = await res.json();
        setRuns(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error("Failed to load runs:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
    const interval = setInterval(fetchRuns, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleStartPipeline = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!videoPath.trim()) return;

    setSubmitting(true);
    setMessage("");

    try {
      const res = await fetch("/api/pipeline/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          videoPath: videoPath.trim(),
          runId: runId.trim() || undefined,
          stage: "all",
          resume: true,
        }),
      });

      const data = await res.json();
      if (res.ok) {
        setMessage("Pipeline successfully launched in background! Watch the live progress below.");
        setVideoPath("");
        setRunId("");
        fetchRuns();
      } else {
        setMessage(`Error: ${data.error || "Failed to start pipeline"}`);
      }
    } catch (err: any) {
      setMessage(`Error: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteRun = async (runIdToDelete: string) => {
    if (!window.confirm(`Are you sure you want to permanently delete run "${runIdToDelete}" and all its slides, study guides, and data? This action cannot be undone.`)) {
      return;
    }
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runIdToDelete)}`, {
        method: "DELETE",
      });
      const data = await res.json();
      if (res.ok) {
        setRuns((prev) => prev.filter((r) => r.id !== runIdToDelete));
        setMessage(`Run "${runIdToDelete}" deleted successfully.`);
      } else {
        setMessage(`Error deleting run: ${data.error || "Unknown error"}`);
      }
    } catch (err: any) {
      setMessage(`Error: ${err.message}`);
    }
  };

  const handleCancelRun = async (runIdToCancel: string) => {
    if (!window.confirm(`Are you sure you want to stop the active pipeline for "${runIdToCancel}"?`)) {
      return;
    }
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runIdToCancel)}/cancel`, {
        method: "POST",
      });
      const data = await res.json();
      if (res.ok) {
        setMessage(`Run "${runIdToCancel}" cancelled.`);
        fetchRuns();
      } else {
        setMessage(`Error cancelling run: ${data.error || "Unknown error"}`);
      }
    } catch (err: any) {
      setMessage(`Error: ${err.message}`);
    }
  };

  const getStageStatus = (run: Run, stageId: string) => {
    const stageOrder = STAGES.map((s) => s.id);
    const runStageIndex = stageOrder.indexOf(run.current_stage);
    const thisStageIndex = stageOrder.indexOf(stageId);

    if (run.status === "completed") return "completed";
    if (run.status === "failed" && runStageIndex === thisStageIndex) return "failed";
    if (runStageIndex > thisStageIndex) return "completed";
    if (runStageIndex === thisStageIndex) return "in_progress";
    return "pending";
  };

  const latestRun = runs.length > 0 ? runs[0] : null;

  const formatDuration = (sec: number | null | undefined) => {
    if (!sec || sec <= 0) return "--";
    const s = Math.floor(sec);
    const m = Math.floor(s / 60);
    const h = Math.floor(m / 60);
    return `${h > 0 ? `${h}h ` : ""}${m % 60}m ${s % 60}s`;
  };

  return (
    <main className="app-container">
      {/* Top Navigation */}
      <header className="navbar">
        <div className="nav-brand">
          <div className="brand-icon">L</div>
          <div>
            <span className="brand-title">Lecture Notes Guide</span>
            <span className="brand-tag" style={{ marginLeft: 8 }}>100% OFFLINE</span>
          </div>
        </div>
        <div className="nav-status">
          <div className="status-pill">
            <span className="status-dot"></span>
            <span>Ollama: <strong>llama3:latest</strong></span>
          </div>
          <div className="status-pill">
            <span className="status-dot"></span>
            <span>Whisper: <strong>Local ASR</strong></span>
          </div>
        </div>
      </header>

      {/* Hero Banner */}
      <section className="hero-card">
        <h1 className="hero-title" id="page-heading">Local Lecture Video to PDF Study Guide Pipeline</h1>
        <p className="hero-subtitle">
          An offline, privacy-first processing pipeline engineered for 3+ hour lecture recordings.
          Extracts crisp slide transitions, transcribes speech with Faster-Whisper, reads slide formulas with Tesseract OCR & Ollama vision, aligns multimodal timelines, and generates comprehensive study guides using Llama 3 Map-Reduce.
        </p>
      </section>

      {/* Main Dashboard Grid */}
      <div className="dashboard-grid">
        {/* Left Column: Launch Form & Stepper */}
        <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
          {/* Start New Pipeline Card */}
          <section className="glass-panel" aria-labelledby="start-panel-title">
            <div className="panel-header">
              <h2 className="panel-title" id="start-panel-title">Launch Pipeline</h2>
            </div>
            <form onSubmit={handleStartPipeline}>
              <div className="form-group">
                <label className="form-label">Lecture Video Selection</label>
                <FilePicker
                  videoPath={videoPath}
                  onPathChange={setVideoPath}
                  onAutoRunIdSuggestion={(suggestedId) => {
                    if (!runId.trim()) {
                      setRunId(suggestedId);
                    }
                  }}
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="run-id-input">Run Identifier (Optional)</label>
                <input
                  id="run-id-input"
                  className="form-input"
                  type="text"
                  placeholder="e.g. bio101_lecture4"
                  value={runId}
                  onChange={(e) => setRunId(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  suppressHydrationWarning
                />
                <p className="form-help">Leave empty to auto-generate a clean ID from the video filename.</p>
              </div>

              {message && (
                <div
                  style={{
                    padding: "10px 14px",
                    borderRadius: "8px",
                    marginBottom: "16px",
                    fontSize: "13px",
                    background: message.startsWith("Error") ? "rgba(244, 63, 94, 0.15)" : "rgba(16, 185, 129, 0.15)",
                    color: message.startsWith("Error") ? "#fda4af" : "#6ee7b7",
                    border: "1px solid currentColor",
                  }}
                >
                  {message}
                </div>
              )}

              <button
                id="submit-pipeline-btn"
                type="submit"
                className="btn btn-primary"
                style={{ width: "100%" }}
                disabled={submitting || !videoPath.trim()}
                suppressHydrationWarning
              >
                {submitting ? "Launching..." : "Start Pipeline Run"}
              </button>
            </form>
          </section>

          {/* Active / Latest Run Progress Stepper */}
          {latestRun && (
            <section className="glass-panel" aria-labelledby="active-stage-title">
              <div className="panel-header">
                <h2 className="panel-title" id="active-stage-title">
                  Pipeline Progress Stepper
                </h2>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span
                    className={`stage-status-tag ${
                      latestRun.status === "completed"
                        ? "tag-completed"
                        : latestRun.status === "in_progress"
                        ? "tag-running"
                        : "tag-failed"
                    }`}
                  >
                    {latestRun.status.toUpperCase()}
                  </span>
                  {latestRun.status === "in_progress" && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ color: "#fb7185", borderColor: "rgba(244,63,94,0.3)" }}
                      onClick={() => handleCancelRun(latestRun.id)}
                      title="Stop running pipeline"
                    >
                      ⏹ Stop Run
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    style={{ color: "#f87171", borderColor: "rgba(239,68,68,0.3)" }}
                    onClick={() => handleDeleteRun(latestRun.id)}
                    title="Delete this run and all data"
                  >
                    🗑 Delete
                  </button>
                </div>
              </div>

              <div style={{ fontSize: "13px", color: "var(--text-secondary)", marginBottom: "12px" }}>
                Active Run: <strong>{latestRun.id}</strong>
              </div>

              {/* Overall Progress Bar */}
              <div style={{ marginBottom: "20px" }}>
                <ProgressBar
                  percent={latestRun.progress_percent || 0}
                  message={latestRun.progress_message}
                  isRunning={latestRun.status === "in_progress"}
                  status={latestRun.status}
                />
              </div>

              <div className="stages-stepper">
                {STAGES.map((s, idx) => {
                  const status = getStageStatus(latestRun, s.id);
                  const isCurrent = status === "in_progress";
                  return (
                    <div key={s.id} className={`stage-item ${status}`}>
                      <div className="stage-badge" style={{ padding: 0 }}>
                        {status === "completed" ? (
                          "✓"
                        ) : isCurrent ? (
                          <ProgressRing
                            percent={latestRun.progress_percent || 0}
                            size={28}
                            strokeWidth={3}
                            isRunning={true}
                            showText={false}
                          />
                        ) : (
                          idx + 1
                        )}
                      </div>
                      <div className="stage-details">
                        <div className="stage-name" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <span>{s.name}</span>
                          {isCurrent && <span className="live-pulse" />}
                        </div>
                        <div className="stage-desc">{s.desc}</div>
                      </div>
                      <span className={`stage-status-tag tag-${status === "in_progress" ? "running" : status}`}>
                        {status === "in_progress" ? "RUNNING" : status.toUpperCase()}
                      </span>
                    </div>
                  );
                })}
              </div>

              <div style={{ marginTop: "16px" }}>
                <Link href={`/runs/${latestRun.id}`} className="btn btn-secondary" style={{ width: "100%" }}>
                  Open Interactive Study Guide &rarr;
                </Link>
              </div>
            </section>
          )}
        </div>

        {/* Right Column: Historical Runs & Detailed Progress Cards */}
        <div>
          <section className="glass-panel" aria-labelledby="runs-list-title">
            <div className="panel-header">
              <h2 className="panel-title" id="runs-list-title">Pipeline Runs & Live Progress</h2>
              <button
                id="refresh-runs-btn"
                className="btn btn-secondary btn-sm"
                onClick={fetchRuns}
              >
                Refresh
              </button>
            </div>

            {loading ? (
              <div style={{ padding: "40px 0", textAlign: "center", color: "var(--text-muted)" }}>
                Loading pipeline runs...
              </div>
            ) : runs.length === 0 ? (
              <div style={{ padding: "40px 20px", textAlign: "center", color: "var(--text-secondary)" }}>
                <p style={{ fontSize: "16px", fontWeight: 600, marginBottom: "8px" }}>No runs recorded yet</p>
                <p style={{ fontSize: "13px" }}>
                  Provide a video path on the left to start generating your first PDF study guide.
                </p>
              </div>
            ) : (
              <div className="runs-list">
                {runs.map((r) => {
                  const isRunning = r.status === "in_progress";
                  const pct = r.progress_percent ?? (r.status === "completed" ? 100 : 0);

                  return (
                    <Link
                      href={`/runs/${r.id}`}
                      key={r.id}
                      className="run-card"
                      style={{ flexDirection: "column", alignItems: "stretch", gap: 10 }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div className="run-info">
                          <h4 style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span>{r.id}</span>
                            {isRunning && <span className="live-pulse" />}
                          </h4>
                          <div className="run-meta">
                            <span>Video: <strong>{r.video_path.split("/").pop()}</strong></span>
                            {r.total_duration && (
                              <span>Duration: <strong>{formatDuration(r.total_duration)}</strong></span>
                            )}
                            {r.slides_count !== undefined && r.slides_count > 0 && (
                              <span>Slides: <strong>{r.slides_count}</strong></span>
                            )}
                          </div>
                        </div>

                        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                          {isRunning && (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              style={{ padding: "4px 8px", fontSize: "12px", color: "#fb7185", borderColor: "rgba(244,63,94,0.3)" }}
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                handleCancelRun(r.id);
                              }}
                              title="Stop this run"
                            >
                              ⏹ Stop
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ padding: "4px 8px", fontSize: "12px", color: "#f87171", borderColor: "rgba(239,68,68,0.3)" }}
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              handleDeleteRun(r.id);
                            }}
                            title="Delete this run"
                          >
                            🗑 Delete
                          </button>
                          <ProgressRing
                            percent={pct}
                            size={46}
                            strokeWidth={4}
                            isRunning={isRunning}
                            status={r.status}
                          />
                          <span style={{ color: "var(--accent-primary)", fontSize: "18px" }}>&rarr;</span>
                        </div>
                      </div>

                      {/* Granular Progress Bar & Status Text */}
                      <ProgressBar
                        percent={pct}
                        message={r.progress_message || (isRunning ? `Processing stage: ${r.current_stage}` : undefined)}
                        isRunning={isRunning}
                        status={r.status}
                      />
                    </Link>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
