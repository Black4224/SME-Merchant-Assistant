import { CheckCircle2, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useState } from "react";
const Ctx = createContext(() => {});
export const useToast = () => useContext(Ctx);
export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((text, tone = "ok") => {
    const id = Date.now() + Math.random();
    setItems((s) => [...s, { id, text, tone }]);
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), 4500);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 start-4 z-[60] flex max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex items-center gap-2 rounded-control border border-line bg-ink px-4 py-2.5 text-sm font-medium text-white shadow-lg"
          >
            {t.tone === "ok" ? (
              <CheckCircle2 className="size-4 text-[#52d6a5]" aria-hidden />
            ) : (
              <XCircle className="size-4 text-[#ff9a96]" aria-hidden />
            )}
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
