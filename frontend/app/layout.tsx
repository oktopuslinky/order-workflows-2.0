import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "workflow-compiler",
  description: "Compile business workflow documents into runnable Temporal code.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="h-full flex flex-col">
        <Providers>
          <header className="flex items-center gap-4 border-b border-[var(--border)] bg-[var(--surface)] px-5 py-2.5">
            <Link href="/" className="font-semibold tracking-tight">
              workflow<span className="text-[var(--accent)]">·</span>compiler
            </Link>
            <span className="hidden font-mono text-[11px] tracking-tight text-[var(--faint)] sm:inline">
              document → spec → validate → approve → code
            </span>
            <nav className="ml-auto flex items-center gap-1 text-sm">
              <Link
                href="/"
                className="rounded-md px-2.5 py-1 text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
              >
                Projects
              </Link>
              <Link
                href="/guide"
                className="rounded-md px-2.5 py-1 text-[var(--muted)] hover:bg-[var(--surface-2)] hover:text-[var(--ink)]"
              >
                Guide
              </Link>
            </nav>
          </header>
          <main className="flex-1 min-h-0 overflow-auto">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
