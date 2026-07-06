import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Forecast Studio",
  description: "Natural-language analytics with verified SQL",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
