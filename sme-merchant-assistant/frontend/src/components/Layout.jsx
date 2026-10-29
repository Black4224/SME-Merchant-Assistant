import { ArrowLeftRight, ChartColumn, LayoutDashboard, Menu, MessageSquareText, Settings as SettingsIcon, Users, X } from "lucide-react";
import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useSettings } from "../lib/settings";
import { Badge, ErrorBanner, cx } from "./ui";
const NAV = [
  { to: "/", label: "لوحة التحكم", icon: LayoutDashboard, end: true },
  { to: "/assistant", label: "المساعد الذكي", icon: MessageSquareText },
  { to: "/transactions", label: "المعاملات", icon: ArrowLeftRight },
  { to: "/customers", label: "الزبائن والديون", icon: Users },
  { to: "/reports", label: "التقارير", icon: ChartColumn },
  { to: "/settings", label: "الإعدادات", icon: SettingsIcon },
];
export function Layout({ children }) {
  const [open, setOpen] = useState(false);
  const { settings, error, reload } = useSettings();
  return (
    <div className="min-h-screen md:flex">
      {open && <div className="fixed inset-0 z-30 bg-ink/40 md:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <aside
        aria-label="التنقل الرئيسي"
        className={cx(
          "fixed inset-y-0 start-0 z-40 flex w-64 flex-col border-e border-line bg-surface transition-transform md:sticky md:top-0 md:h-screen md:translate-x-0",
          open ? "translate-x-0" : "max-md:translate-x-full",
        )}
      >
        <div className="flex items-center justify-between gap-2 px-5 py-5">
          <div className="flex items-center gap-2.5">
            <span className="grid size-9 place-items-center rounded-control bg-ink text-white" aria-hidden>
              <ChartColumn className="size-5 text-[#52d6a5]" />
            </span>
            <span className="text-lg font-bold leading-tight">مساعد التاجر</span>
          </div>
          <button
            className="rounded-control p-1.5 text-muted hover:bg-page md:hidden"
            onClick={() => setOpen(false)}
            aria-label="إغلاق القائمة"
          >
            <X className="size-5" />
          </button>
        </div>
        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              onClick={() => setOpen(false)}
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cx(
                  "flex h-11 items-center gap-3 rounded-control px-3 text-sm font-semibold transition-colors",
                  isActive ? "bg-ink text-white" : "text-muted hover:bg-page hover:text-ink",
                )
              }
            >
              <Icon className="size-5 shrink-0" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        {settings?.is_demo_data && (
          <p className="m-3 rounded-control border border-[#efd8ab] bg-warn-bg px-3 py-2 text-xs leading-6 text-warn">
            {settings.demo_notice_ar ?? "البيانات الحالية تجريبية."}
          </p>
        )}
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-surface/95 px-4 backdrop-blur sm:px-6">
          <button className="rounded-control p-2 text-ink hover:bg-page md:hidden" onClick={() => setOpen(true)} aria-label="فتح القائمة">
            <Menu className="size-5" />
          </button>
          <p className="min-w-0 flex-1 truncate font-bold">{settings?.business_name ?? ""}</p>
          {settings?.is_demo_data && <Badge tone="warn">بيانات تجريبية</Badge>}
        </header>
        <main className="mx-auto w-full max-w-7xl space-y-5 px-4 py-5 sm:px-6 sm:py-6">
          {error && <ErrorBanner error={error} onRetry={reload} />}
          {children}
        </main>
      </div>
    </div>
  );
}
export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
