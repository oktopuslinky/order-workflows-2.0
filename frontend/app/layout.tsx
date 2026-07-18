import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UserMenu } from "@/components/UserMenu";
import { NavLink } from "@/components/NavLink";
import { AuthGuard } from "@/lib/auth";

// Runs before first paint: apply the saved theme (or the OS setting) to <html>
// so there is no light/dark flash and no hydration mismatch.
const themeScript = `(function(){try{var t=localStorage.getItem('theme');if(t!=='light'&&t!=='dark'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.dataset.theme=t;}catch(e){}})();`;

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
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
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
              <NavLink href="/">Projects</NavLink>
              <NavLink href="/guide">Guide</NavLink>
              <ThemeToggle />
              <UserMenu />
            </nav>
          </header>
          <main className="flex-1 min-h-0 overflow-auto">
            <AuthGuard>{children}</AuthGuard>
          </main>
        </Providers>
      </body>
    </html>
  );
}
