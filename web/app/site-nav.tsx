import Link from "next/link";
import { FileArchive, MessagesSquare, Search } from "lucide-react";

type NavKey = "search" | "analysis" | "package";

const NAV_ITEMS: Array<{ key: NavKey; href: string; label: string; icon: typeof Search }> = [
  { key: "search", href: "/", label: "查詢", icon: Search },
  { key: "analysis", href: "/analysis", label: "AI 分析結果", icon: MessagesSquare },
  { key: "package", href: "/package", label: "AI 分析包", icon: FileArchive },
];

/** 全站導覽；本站只有公開資料，沒有登入功能。 */
export function SiteNav({ current }: { current?: NavKey }) {
  return (
    <nav className="site-nav" aria-label="主要功能">
      {NAV_ITEMS.map(({ key, href, label, icon: Icon }) => (
        <Link
          className={`button secondary site-nav-link${key === current ? " current" : ""}`}
          href={href}
          key={key}
          aria-current={key === current ? "page" : undefined}
        >
          <Icon size={17} aria-hidden="true" />
          {label}
        </Link>
      ))}
    </nav>
  );
}
