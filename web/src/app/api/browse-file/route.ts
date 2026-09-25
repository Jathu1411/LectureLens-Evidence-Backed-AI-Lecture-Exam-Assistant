import { NextResponse } from "next/server";
import { execFile } from "child_process";
import path from "path";
import fs from "fs";

export async function POST() {
  try {
    const rootDir = path.resolve(process.cwd(), "..");
    const venvPython = path.join(rootDir, "venv", "bin", "python");
    const pythonBin = fs.existsSync(venvPython) ? venvPython : "python3";

    // Run file_picker helper in JSON mode with prompt
    const result = await new Promise<string>((resolve, reject) => {
      execFile(
        pythonBin,
        ["-m", "pipeline.file_picker", "--json", "--no-terminal", "--prompt", "Select a Lecture Video for Study Guide:"],
        {
          cwd: rootDir,
          timeout: 120000, // 2-minute window for user to pick
        },
        (error, stdout, stderr) => {
          if (stdout && stdout.trim()) {
            resolve(stdout.trim());
          } else if (error) {
            reject(new Error(stderr || error.message));
          } else {
            resolve(JSON.stringify({ success: false, cancelled: true }));
          }
        }
      );
    });

    try {
      const parsed = JSON.parse(result);
      return NextResponse.json(parsed);
    } catch {
      return NextResponse.json({
        success: false,
        error: "Failed to parse file picker output",
        raw: result,
      }, { status: 500 });
    }
  } catch (error: any) {
    console.error("Browse file error:", error);
    return NextResponse.json(
      { success: false, error: error.message || "Failed to open laptop file dialog" },
      { status: 500 }
    );
  }
}
