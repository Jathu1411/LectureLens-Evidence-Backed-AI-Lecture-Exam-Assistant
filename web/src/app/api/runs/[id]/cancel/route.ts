import { NextResponse } from "next/server";
import { exec } from "child_process";
import path from "path";
import util from "util";

const execPromise = util.promisify(exec);

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const rootDir = path.resolve(process.cwd(), "..");
    const pythonBin = path.join(rootDir, "venv", "bin", "python");

    // 1. Terminate active process for this runId
    try {
      await execPromise(`pkill -f "main.py.*${id}" || true`);
    } catch {
      // Ignore
    }

    // 2. Call python main.py cancel --run-id "{id}"
    await execPromise(
      `"${pythonBin}" main.py cancel --run-id "${id}"`,
      { cwd: rootDir }
    );

    return NextResponse.json({
      success: true,
      message: `Run '${id}' has been cancelled.`,
    });
  } catch (error: any) {
    console.error("Error cancelling run:", error);
    return NextResponse.json(
      { error: "Failed to cancel run", details: error?.message },
      { status: 500 }
    );
  }
}
