"use client";

import React from "react";

interface ProgressRingProps {
  percent: number;
  size?: number;
  strokeWidth?: number;
  isRunning?: boolean;
  status?: string;
  showText?: boolean;
}

export function ProgressRing({
  percent,
  size = 44,
  strokeWidth = 4,
  isRunning = false,
  status = "in_progress",
  showText = true,
}: ProgressRingProps) {
  const radius = Math.round((size - strokeWidth) / 2);
  const circumference = Number((2 * Math.PI * radius).toFixed(2));
  const clampedPercent = Math.max(0, Math.min(100, percent || 0));
  const strokeDashoffset = Number(
    (circumference - (circumference * clampedPercent) / 100).toFixed(2)
  );

  const isCompleted = status === "completed" || clampedPercent >= 100;
  const isFailed = status === "failed";

  const strokeColor = isCompleted
    ? "var(--accent-emerald)"
    : isFailed
    ? "var(--accent-rose)"
    : isRunning
    ? "url(#accentGrad)"
    : "var(--accent-primary)";

  return (
    <div className="progress-ring-container" style={{ width: size, height: size }}>
      <svg className="progress-ring" width={size} height={size}>
        <defs>
          <linearGradient id="accentGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#6366f1" />
            <stop offset="50%" stopColor="#a855f7" />
            <stop offset="100%" stopColor="#06b6d4" />
          </linearGradient>
        </defs>

        {/* Background Circle */}
        <circle
          className="progress-ring-bg"
          strokeWidth={strokeWidth}
          cx={size / 2}
          cy={size / 2}
          r={radius}
        />

        {/* Dynamic Foreground Arc */}
        <circle
          className={`progress-ring-bar ${isRunning && clampedPercent < 100 ? "spinning" : ""}`}
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeDasharray={`${circumference} ${circumference}`}
          style={{ strokeDashoffset: isRunning && clampedPercent === 0 ? circumference * 0.75 : strokeDashoffset }}
          cx={size / 2}
          cy={size / 2}
          r={radius}
        />

        {showText && (
          <text
            className="progress-ring-text"
            x={size / 2}
            y={size / 2}
            style={{
              fontSize: size <= 40 ? "9px" : "11px",
              fill: isCompleted ? "var(--accent-emerald)" : isFailed ? "var(--accent-rose)" : "var(--text-primary)",
            }}
          >
            {isCompleted ? "✓" : isFailed ? "!" : `${Math.round(clampedPercent)}%`}
          </text>
        )}
      </svg>
    </div>
  );
}

interface ProgressBarProps {
  percent: number;
  message?: string;
  isRunning?: boolean;
  status?: string;
}

export function ProgressBar({
  percent,
  message,
  isRunning = false,
  status = "in_progress",
}: ProgressBarProps) {
  const clampedPercent = Math.max(0, Math.min(100, percent || 0));
  const isFailed = status === "failed";
  const isCompleted = status === "completed" || clampedPercent >= 100;

  return (
    <div className="progress-bar-wrapper">
      <div className="progress-bar-track">
        <div
          className={`progress-bar-fill ${isRunning && !isCompleted && !isFailed ? "running" : ""}`}
          style={{
            width: `${clampedPercent}%`,
            background: isFailed
              ? "linear-gradient(90deg, #f43f5e 0%, #fb7185 100%)"
              : isCompleted
              ? "linear-gradient(90deg, #10b981 0%, #34d399 100%)"
              : undefined,
          }}
        />
      </div>
      <div className="progress-bar-meta">
        <span className="progress-msg">
          {isRunning && <span className="live-pulse" title="Active background process" />}
          <span>{message || (isCompleted ? "Completed" : isFailed ? "Failed" : "Processing...")}</span>
        </span>
        <span
          className="progress-pct"
          style={{
            color: isFailed ? "var(--accent-rose)" : isCompleted ? "var(--accent-emerald)" : "var(--accent-cyan)",
          }}
        >
          {Math.round(clampedPercent)}%
        </span>
      </div>
    </div>
  );
}
