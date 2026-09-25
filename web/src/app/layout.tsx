import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lecture Notes Guide — Offline Video to PDF Study Guide Pipeline",
  description: "A local, offline pipeline converting recorded lecture videos into structured PDF study guides.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
