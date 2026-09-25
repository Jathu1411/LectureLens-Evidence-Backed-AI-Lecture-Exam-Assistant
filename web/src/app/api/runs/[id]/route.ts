import { NextResponse } from "next/server";
import { exec } from "child_process";
import path from "path";
import util from "util";

const execPromise = util.promisify(exec);

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const rootDir = path.resolve(process.cwd(), "..");
    const pythonBin = path.join(rootDir, "venv", "bin", "python");

    const { stdout } = await execPromise(
      `"${pythonBin}" main.py run-details-json --run-id "${id}"`,
      { cwd: rootDir }
    );

    const jsonMatch = stdout.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return NextResponse.json({ error: "Run not found" }, { status: 404 });
    }
    const data = JSON.parse(jsonMatch[0]);
    if (data.error) {
      return NextResponse.json({ error: "Run not found" }, { status: 404 });
    }

    return NextResponse.json(data);
  } catch (error: any) {
    console.error("Error fetching run details:", error);
    return NextResponse.json(
      { error: "Failed to fetch run details", details: error?.message },
      { status: 500 }
    );
  }
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const rootDir = path.resolve(process.cwd(), "..");
    const pythonBin = path.join(rootDir, "venv", "bin", "python");

    // 1. Terminate any active process running for this runId
    try {
      await execPromise(`pkill -f "main.py.*${id}" || true`);
    } catch {
      // Ignore if no process is active
    }

    // 2. Call python main.py delete --run-id "{id}"
    await execPromise(
      `"${pythonBin}" main.py delete --run-id "${id}"`,
      { cwd: rootDir }
    );

    return NextResponse.json({
      success: true,
      message: `Run '${id}' and its artifacts successfully deleted.`,
    });
  } catch (error: any) {
    console.error("Error deleting run:", error);
    return NextResponse.json(
      { error: "Failed to delete run", details: error?.message },
      { status: 500 }
    );
  }
}
