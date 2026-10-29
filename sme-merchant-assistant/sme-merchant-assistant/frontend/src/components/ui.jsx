import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";
export const cx = (...a) => a.filter(Boolean).join(" ");
const VARIANT = {
  primary: "bg-ink text-white hover:bg-[#1c3159] disabled:bg-[#7d8aa3]",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-page disabled:text-faint",
  danger: "bg-neg text-white hover:bg-[#a82a26] disabled:bg-[#d89a98]",
  ghost: "text-muted hover:bg-page hover:text-ink disabled:text-faint",
};
export function Button({ variant = "secondary", loading, className, children, disabled, ...rest }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex h-10 items-center justify-center gap-2 rounded-control px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed",
        VARIANT[variant],
        className,
      )}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}
export function Card({ title, actions, children, className, pad = true }) {
  return (
    <section className={cx("rounded-panel border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3 sm:px-5">
          <h2 className="text-base font-bold">{title}</h2>
          {actions}
        </header>
      )}
      <div className={pad ? "p-4 sm:p-5" : ""}>{children}</div>
    </section>
  );
}
const TONE = {
  neutral: "bg-page text-muted border-line",
  pos: "bg-pos-bg text-pos border-[#bfe5d4]",
  neg: "bg-neg-bg text-neg border-[#f2c5c3]",
  warn: "bg-warn-bg text-warn border-[#efd8ab]",
  info: "bg-info-bg text-info border-[#c5d6f2]",
};
export function Badge({ tone = "neutral", children, title }) {
  return (
    <span
      title={title}
      className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold", TONE[tone])}
    >
      {children}
    </span>
  );
}
export const inputCls = (invalid) =>
  cx(
    "h-10 w-full rounded-control border bg-surface px-3 text-ink placeholder:text-faint focus-visible:border-info disabled:bg-page disabled:text-faint",
    invalid ? "border-neg" : "border-line-strong",
  );
export function Field({ label, error, hint, children, className }) {
  return (
    <div className={className}>
      <label className="block">
        <span className="mb-1 block text-sm font-semibold">{label}</span>
        {children}
      </label>
      {error ? (
        <p role="alert" className="mt-1 text-sm text-neg">
          {error}
        </p>
      ) : hint ? (
        <p className="mt-1 text-xs text-muted">{hint}</p>
      ) : null}
    </div>
  );
}
export function Spinner({ label = "جارٍ التحميل…" }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-muted">
      <Loader2 className="size-5 animate-spin" aria-hidden />
      {label}
    </div>
  );
}
export function Skeleton({ className }) {
  return <div aria-hidden className={cx("animate-pulse rounded-control bg-line/70", className)} />;
}
export function ErrorBanner({ error, onRetry }) {
  const msg = typeof error === "string" ? error : error.message;
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-panel border border-[#f2c5c3] bg-neg-bg px-4 py-3 text-neg">
      <AlertTriangle className="size-5 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1 text-sm font-medium">{msg}</p>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry} className="h-9">
          <RefreshCw className="size-4" aria-hidden />
          إعادة المحاولة
        </Button>
      )}
    </div>
  );
}
export function EmptyState({ title, hint, action }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <p className="font-semibold">{title}</p>
      {hint && <p className="max-w-md text-sm text-muted">{hint}</p>}
      {action}
    </div>
  );
}
export function Segmented({ value, options, onChange, label }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-control border border-line-strong bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "h-9 rounded-[6px] px-3 text-sm font-semibold transition-colors",
            o.value === value ? "bg-ink text-white" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
export const th = "whitespace-nowrap border-b border-line bg-page px-3 py-2.5 text-start text-xs font-semibold text-muted";
export const td = "border-b border-line px-3 py-3 align-middle text-sm";
export function TableWrap({ children }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse">{children}</table>
    </div>
  );
}
