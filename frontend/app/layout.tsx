import type { Metadata } from "next";
import { Fira_Sans, Fira_Code } from "next/font/google";
import "./globals.css";

// Recommended pairing (UI/UX Pro Max — Data-Dense Dashboard): Fira Sans for UI,
// Fira Code for SQL / numeric data. Self-hosted by next/font (no runtime calls).
const firaSans = Fira_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

const firaCode = Fira_Code({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Forecast Studio",
  description: "Natural-language analytics with verified SQL",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${firaSans.variable} ${firaCode.variable}`}>
      <body>{children}</body>
    </html>
  );
}
