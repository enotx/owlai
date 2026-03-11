// frontend/src/app/layout.tsx

import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { BackendProvider } from "@/contexts/backend-context";
import { OnboardingProvider } from "@/contexts/onboarding-context";
import { DatabaseProvider } from "@/contexts/database-context";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Owl.AI - An AI Data Analyst",
  description: "AI-driven data analysis tool powered by Pandas",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} font-sans antialiased`}
      >
        <BackendProvider>
          <DatabaseProvider>
            <OnboardingProvider>
              {children}
            </OnboardingProvider>
          </DatabaseProvider>
        </BackendProvider>
      </body>
    </html>
  );
}