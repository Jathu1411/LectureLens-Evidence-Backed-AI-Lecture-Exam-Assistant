import { NextResponse } from "next/server";
import { exec } from "child_process";
import path from "path";
import util from "util";

const execPromise = util.promisify(exec);

export async function GET() {
  try {
    const rootDir = path.resolve(process.cwd(), "..");
    const pythonBin = path.join(rootDir, "venv", "bin", "python");

    const { stdout } = await execPromise(`"${pythonBin}" main.py runs-json`, {
      cwd: rootDir,
    });

    const jsonMatch = stdout.match(/\[[\s\S]*\]/);
    if (!jsonMatch) {
      return NextResponse.json([]);
    }
    const runs = JSON.parse(jsonMatch[0]);
    return NextResponse.json(runs);
  } catch (error: any) {
    console.error("Error fetching runs:", error);
    return NextResponse.json(
      { error: "Failed to fetch runs", details: error?.message },
      { status: 500 }
    );
  }
}
