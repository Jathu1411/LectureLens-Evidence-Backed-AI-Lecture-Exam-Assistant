import { NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";
import fs from "fs";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { videoPath, runId, stage, mode = "process", resume = true } = body;

    if (!videoPath && !runId) {
      return NextResponse.json(
        { error: "Either videoPath or runId is required" },
        { status: 400 }
      );
    }

    const rootDir = path.resolve(process.cwd(), "..");
    const venvPython = path.join(rootDir, "venv", "bin", "python");
    const pythonBin = fs.existsSync(venvPython) ? venvPython : "python3";

    let args: string[] = [];
    if (!stage || stage === "all") {
      if (mode === "process") {
        args = ["main.py", "process", videoPath];
        if (runId) args.push("--run-id", runId);
        if (!resume) args.push("--no-resume");
      } else {
        args = ["main.py", "run", "--video", videoPath];
        if (runId) args.push("--run-id", runId);
        if (!resume) args.push("--no-resume");
      }
    } else {
      args = ["main.py", stage, "--run-id", runId];
      if (videoPath) args.push("--video", videoPath);
    }

    // Prevent conflicting concurrent duplicate processes for the same run
    if (runId) {
      try {
        const { execSync } = await import("child_process");
        execSync(`pkill -f "main.py.*${runId}" || true`);
      } catch {
        // Ignore if no existing process
      }
    }

    // Spawn process in background so web UI stays responsive
    const child = spawn(pythonBin, args, {
      cwd: rootDir,
      detached: true,
      stdio: "ignore",
    });

    child.unref();

    return NextResponse.json({
      success: true,
      message: `Pipeline command launched: ${args.join(" ")}`,
      pid: child.pid,
    });
  } catch (error: any) {
    console.error("Error triggering pipeline:", error);
    return NextResponse.json(
      { error: "Failed to launch pipeline", details: error?.message },
      { status: 500 }
    );
  }
}
