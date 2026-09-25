import { NextResponse } from "next/server";
import { Readable } from "stream";
import { pipeline } from "stream/promises";
import fs from "fs";
import path from "path";

export async function POST(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const rootDir = path.resolve(process.cwd(), "..");
    const uploadsDir = path.join(rootDir, "output", "uploads");

    if (!fs.existsSync(uploadsDir)) {
      fs.mkdirSync(uploadsDir, { recursive: true });
    }

    const filenameParam = searchParams.get("filename");

    // Case 1: Streamed file payload with filename in query params
    if (filenameParam && request.body) {
      const cleanFilename = path
        .basename(decodeURIComponent(filenameParam))
        .replace(/[^a-zA-Z0-9._-]/g, "_");
      const targetPath = path.join(uploadsDir, cleanFilename);

      const nodeStream = Readable.fromWeb(request.body as any);
      const writeStream = fs.createWriteStream(targetPath);
      await pipeline(nodeStream, writeStream);

      const stats = fs.statSync(targetPath);
      return NextResponse.json({
        success: true,
        filePath: targetPath,
        relativePath: path.relative(rootDir, targetPath),
        fileName: cleanFilename,
        fileSize: stats.size,
      });
    }

    // Case 2: Standard multipart/form-data upload
    const formData = await request.formData();
    const file = formData.get("file") as File | null;

    if (!file) {
      return NextResponse.json(
        { error: "No video file provided for upload" },
        { status: 400 }
      );
    }

    const cleanFilename = path
      .basename(file.name)
      .replace(/[^a-zA-Z0-9._-]/g, "_");
    const targetPath = path.join(uploadsDir, cleanFilename);

    const buffer = Buffer.from(await file.arrayBuffer());
    await fs.promises.writeFile(targetPath, buffer);

    const stats = fs.statSync(targetPath);
    return NextResponse.json({
      success: true,
      filePath: targetPath,
      relativePath: path.relative(rootDir, targetPath),
      fileName: cleanFilename,
      fileSize: stats.size,
    });
  } catch (error: any) {
    console.error("File upload error:", error);
    return NextResponse.json(
      { error: "Failed to upload file", details: error?.message },
      { status: 500 }
    );
  }
}
