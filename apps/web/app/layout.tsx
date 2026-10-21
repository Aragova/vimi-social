import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ViMi Social",
  description: "AI-assisted multi-platform content operations",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
