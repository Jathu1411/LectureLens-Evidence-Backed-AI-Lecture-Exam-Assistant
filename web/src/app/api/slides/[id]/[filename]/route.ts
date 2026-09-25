import { NextResponse } from "next/server";
import path from "path";
import fs from "fs";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; filename: string }> }
) {
  try {
    const { id, filename } = await params;
    // Sanitize filename
    const safeFilename = path.basename(filename);
    const rootDir = path.resolve(process.cwd(), "..");
    const imagePath = path.join(rootDir, "output", id, "slides", safeFilename);

    if (!fs.existsSync(imagePath)) {
      return NextResponse.json({ error: "Slide image not found" }, { status: 404 });
    }

    const fileBuffer = fs.readFileSync(imagePath);
    return new NextResponse(fileBuffer, {
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": "public, max-age=86400, immutable",
      },
    });
  } catch (error: any) {
    console.error("Error serving slide:", error);
    return NextResponse.json({ error: "Failed to serve slide" }, { status: 500 });
  }
}
