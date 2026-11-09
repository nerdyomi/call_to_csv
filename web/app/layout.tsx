import type { Metadata } from "next";
import { Inter, Noto_Sans_Bengali } from "next/font/google";
import "./globals.css";
import Nav from "@/components/Nav";
import Gate from "@/components/Gate";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const bengali = Noto_Sans_Bengali({ subsets: ["bengali"], variable: "--font-bengali", display: "swap" });

export const metadata: Metadata = {
  title: "iFarmer Call Insights",
  description: "Upload KYC call recordings, get transcripts, fields and answers.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${bengali.variable}`}>
      <body className="min-h-screen antialiased">
        <Nav />
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
          <Gate>{children}</Gate>
        </main>
      </body>
    </html>
  );
}
