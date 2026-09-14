import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Imperial Sales CRM",
  description: "Az Imperial Intelligence belső értékesítési munkafelülete.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="hu"><body>{children}</body></html>;
}
