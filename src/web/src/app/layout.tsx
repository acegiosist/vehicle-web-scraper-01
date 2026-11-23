import { Suspense } from "react";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AiRunNotice } from "@/components/ai-runs/ai-run-notice";
import { SiteHeader } from "@/components/site-header";

import "./globals.css";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Revisión de conflictos", template: "%s · Revisión KB" },
  description: "Decisiones humanas sobre la base de conocimiento de vehículos",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <SiteHeader />
        <div className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
          {/* a DB read: streamed in, it never holds up the page */}
          <Suspense fallback={null}>
            <AiRunNotice />
          </Suspense>
          {children}
        </div>
      </body>
    </html>
  );
}
