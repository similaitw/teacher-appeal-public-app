import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "教師申訴評議書公開查詢",
  description: "教育部教師申訴評議書公開資料查詢與閱讀介面",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant">
      <body>{children}</body>
    </html>
  );
}
