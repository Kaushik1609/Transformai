import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ThemeProvider } from "@/components/theme";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "TransformIQ — One source, every format",
  description:
    "TransformIQ turns one source and one instruction into many communication-ready output formats.",
};

const THEME_BOOTSTRAP = `(function(){try{var t=localStorage.getItem('transformiq:theme')||'system';var d=t==='dark'||(t==='system'&&window.matchMedia('(prefers-color-scheme: dark)').matches);var r=document.documentElement;if(d){r.classList.add('dark');}else{r.classList.remove('dark');}}catch(e){}})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        <script
          dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }}
        />
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
