"use client";

import React, { useState, useRef } from "react";

interface FilePickerProps {
  videoPath: string;
  onPathChange: (path: string) => void;
  onAutoRunIdSuggestion?: (suggestedId: string) => void;
}

interface UploadedFileInfo {
  name: string;
  size: number;
  formattedSize: string;
  path: string;
  isDirectPath?: boolean;
}

export function FilePicker({
  videoPath,
  onPathChange,
  onAutoRunIdSuggestion,
}: FilePickerProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isBrowsingLaptop, setIsBrowsingLaptop] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadedInfo, setUploadedInfo] = useState<UploadedFileInfo | null>(null);
  const [uploadError, setUploadError] = useState<string>("");
  const [showManualInput, setShowManualInput] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  const generateCleanRunId = (filename: string): string => {
    const base = filename.substring(0, filename.lastIndexOf(".")) || filename;
    return base
      .toLowerCase()
      .replace(/[^a-z0-9_-]/g, "_")
      .replace(/_+/g, "_")
      .slice(0, 30);
  };

  // 1. Native Laptop File Dialog (Zero Upload Overhead)
  const handleBrowseLaptop = async () => {
    setUploadError("");
    setIsBrowsingLaptop(true);

    try {
      const res = await fetch("/api/browse-file", {
        method: "POST",
      });

      const data = await res.json();
      if (res.ok && data.success && data.filePath) {
        const info: UploadedFileInfo = {
          name: data.fileName,
          size: data.fileSize,
          formattedSize: data.formattedSize || formatFileSize(data.fileSize),
          path: data.filePath,
          isDirectPath: true,
        };
        setUploadedInfo(info);
        onPathChange(data.filePath);

        if (onAutoRunIdSuggestion) {
          onAutoRunIdSuggestion(generateCleanRunId(data.fileName));
        }
      } else if (data.cancelled) {
        // User clicked Cancel in Finder
      } else {
        setUploadError(data.error || "Failed to select file from laptop");
      }
    } catch (err: any) {
      setUploadError(err.message || "Failed to communicate with local file picker service.");
    } finally {
      setIsBrowsingLaptop(false);
    }
  };

  // 2. Standard Browser Upload for Drag & Drop
  const uploadFile = (file: File) => {
    setUploadError("");
    setIsUploading(true);
    setUploadProgress(0);

    const xhr = new XMLHttpRequest();
    const url = `/api/upload?filename=${encodeURIComponent(file.name)}`;

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        setUploadProgress(percent);
      }
    });

    xhr.addEventListener("load", () => {
      setIsUploading(false);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const res = JSON.parse(xhr.responseText);
          if (res.success && res.filePath) {
            const info: UploadedFileInfo = {
              name: file.name,
              size: file.size,
              formattedSize: formatFileSize(file.size),
              path: res.filePath,
              isDirectPath: false,
            };
            setUploadedInfo(info);
            onPathChange(res.filePath);

            if (onAutoRunIdSuggestion) {
              const suggestedId = generateCleanRunId(file.name);
              onAutoRunIdSuggestion(suggestedId);
            }
          } else {
            setUploadError(res.error || "Upload failed");
          }
        } catch {
          setUploadError("Invalid response from server");
        }
      } else {
        setUploadError(`Upload failed with status code ${xhr.status}`);
      }
    });

    xhr.addEventListener("error", () => {
      setIsUploading(false);
      setUploadError("Network error occurred during file upload.");
    });

    xhr.open("POST", url, true);
    xhr.send(file);
  };

  const handleFileSelect = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const file = files[0];
    uploadFile(file);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelect(e.dataTransfer.files);
    }
  };

  const handleClearSelection = () => {
    setUploadedInfo(null);
    onPathChange("");
    setUploadError("");
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleUseSample = () => {
    const samplePath = "sample_data/demo_lecture.mp4";
    onPathChange(samplePath);
    setUploadedInfo({
      name: "demo_lecture.mp4",
      size: 474492,
      formattedSize: "463.4 KB",
      path: samplePath,
      isDirectPath: true,
    });
    if (onAutoRunIdSuggestion) {
      onAutoRunIdSuggestion("demo_lecture_sample");
    }
  };

  return (
    <div className="file-picker-wrapper">
      {/* Hidden File Input for Browser Upload Fallback */}
      <input
        ref={fileInputRef}
        type="file"
        accept="video/mp4,video/x-matroska,video/quicktime,video/webm,video/*,.mp4,.mkv,.mov,.webm,.avi"
        style={{ display: "none" }}
        onChange={(e) => handleFileSelect(e.target.files)}
      />

      {/* Main Drag and Drop & Finder Zone */}
      {!uploadedInfo && !videoPath ? (
        <div
          className={`dropzone-container ${isDragging ? "dropzone-active" : ""}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {isBrowsingLaptop ? (
            <div className="upload-progress-container" style={{ textAlign: "center", padding: "16px 0" }}>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 48,
                  height: 48,
                  borderRadius: "50%",
                  background: "rgba(56, 189, 248, 0.15)",
                  color: "#38bdf8",
                  marginBottom: 12,
                  animation: "pulse 1.5s infinite ease-in-out",
                }}
              >
                <svg
                  width="26"
                  height="26"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                  <line x1="8" y1="21" x2="16" y2="21" />
                  <line x1="12" y1="17" x2="12" y2="21" />
                </svg>
              </div>
              <h3 style={{ fontSize: "15px", fontWeight: 600, color: "var(--text-primary)", marginBottom: 4 }}>
                Opening Finder on your Mac...
              </h3>
              <p style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                Select your lecture video file from your laptop.
              </p>
            </div>
          ) : isUploading ? (
            <div className="upload-progress-container" onClick={(e) => e.stopPropagation()}>
              <div className="upload-progress-header">
                <span className="upload-progress-title">Importing lecture video...</span>
                <span className="upload-progress-pct">{uploadProgress}%</span>
              </div>
              <div className="upload-progress-bar-bg">
                <div
                  className="upload-progress-bar-fill"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <p className="upload-progress-hint">Saving locally for offline processing</p>
            </div>
          ) : (
            <div className="dropzone-content">
              {/* Primary: Select from Laptop */}
              <button
                id="btn-select-laptop-file"
                type="button"
                className="btn btn-laptop-primary"
                onClick={handleBrowseLaptop}
              >
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
                  <line x1="8" y1="21" x2="16" y2="21" />
                  <line x1="12" y1="17" x2="12" y2="21" />
                </svg>
                <span>Select from Laptop (Finder)</span>
                <span className="badge-direct">Instant</span>
              </button>

              <div className="dropzone-divider">
                <span>OR</span>
              </div>

              <div
                className="dropzone-sub-area"
                onClick={() => fileInputRef.current?.click()}
                title="Click to browse via browser or drag files here"
              >
                <div className="dropzone-text-group">
                  <p className="dropzone-primary-text">
                    Drag & drop video here, or click to upload
                  </p>
                  <p className="dropzone-secondary-text">
                    Supports MP4, MKV, MOV, WebM, AVI (3+ hour lectures)
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : (
        /* Selected File Card */
        <div className="selected-file-card">
          <div className="selected-file-main">
            <div className="selected-file-icon">
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polygon points="23 7 16 12 23 17 23 7" />
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
              </svg>
            </div>
            <div className="selected-file-meta">
              <div className="selected-file-name-row">
                <span className="selected-file-name">
                  {uploadedInfo?.name || videoPath.split("/").pop() || "Selected Video"}
                </span>
                <span className={`selected-file-badge ${uploadedInfo?.isDirectPath ? "badge-direct-ready" : ""}`}>
                  {uploadedInfo?.isDirectPath ? "LAPTOP DIRECT" : "READY"}
                </span>
              </div>
              <div className="selected-file-details">
                {uploadedInfo?.formattedSize && (
                  <span className="selected-file-size">{uploadedInfo.formattedSize} • </span>
                )}
                <span className="selected-file-path" title={videoPath}>
                  {videoPath}
                </span>
              </div>
            </div>
          </div>

          <div className="selected-file-actions">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleBrowseLaptop}
              title="Pick a different video file from laptop"
            >
              Browse
            </button>
            <button
              type="button"
              className="btn btn-danger-icon"
              onClick={handleClearSelection}
              title="Remove selection"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Error Message */}
      {uploadError && (
        <div className="upload-error-banner">
          <span>⚠️ {uploadError}</span>
        </div>
      )}

      {/* Auxiliary Options: Sample Video & Manual Path toggle */}
      <div className="file-picker-footer">
        <button
          type="button"
          className="link-subtle"
          onClick={handleUseSample}
        >
          ✨ Use demo lecture sample
        </button>

        <button
          type="button"
          className="link-subtle"
          onClick={() => setShowManualInput(!showManualInput)}
        >
          {showManualInput ? "Hide manual path" : "Or enter path manually"}
        </button>
      </div>

      {/* Manual Path input (for pre-existing external drives or direct paths) */}
      {showManualInput && (
        <div className="manual-path-container">
          <label className="form-label" htmlFor="manual-video-path">
            Direct File Path
          </label>
          <input
            id="manual-video-path"
            type="text"
            className="form-input"
            placeholder="/Users/username/Videos/lecture.mp4"
            value={videoPath}
            onChange={(e) => {
              onPathChange(e.target.value);
              setUploadedInfo({
                name: e.target.value.split("/").pop() || "Video",
                size: 0,
                formattedSize: "",
                path: e.target.value,
                isDirectPath: true,
              });
            }}
          />
          <p className="form-help">
            Useful if your video is stored on an external SSD or custom drive mount.
          </p>
        </div>
      )}
    </div>
  );
}
