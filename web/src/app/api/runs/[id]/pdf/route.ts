import { NextResponse } from "next/server";
import path from "path";
import fs from "fs";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const rootDir = path.resolve(process.cwd(), "..");
    const pdfPath = path.join(rootDir, "output", id, "study_guide.pdf");

    if (!fs.existsSync(pdfPath)) {
      return NextResponse.json(
        { error: "PDF not found for this run" },
        { status: 404 }
      );
    }

    const fileBuffer = fs.readFileSync(pdfPath);
    return new NextResponse(fileBuffer, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="study_guide_${id}.pdf"`,
      },
    });
  } catch (error: any) {
    console.error("Error downloading PDF:", error);
    return NextResponse.json(
      { error: "Failed to download PDF", details: error?.message },
      { status: 500 }
    );
  }
}
