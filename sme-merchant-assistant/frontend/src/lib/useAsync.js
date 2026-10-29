import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";

const toApiError = (e) => (e instanceof ApiError ? e : new ApiError(0, "unknown", "حدث خطأ غير متوقع"));

/**
 * Runs `fn` whenever `deps` change (or `reload()` is called).
 * `deps` must be JSON-serialisable (strings, numbers, ...). The previous data stays visible while reloading,
 * `loading` is derived from whether the stored result belongs to the current request, and stale responses are ignored.
 */
export function useAsync(fn, deps) {
  const [tick, setTick] = useState(0);
  const [result, setResult] = useState({ key: null, data: null, error: null });
  const key = `${JSON.stringify(deps)}#${tick}`;

  useEffect(() => {
    let alive = true;
    fn().then(
      (data) => alive && setResult({ key, data, error: null }),
      (e) => alive && setResult((prev) => ({ key, data: prev.data, error: toApiError(e) })),
    );
    return () => {
      alive = false;
    };
    // `fn` is intentionally not a dependency: callers describe what should re-run it through `deps`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const current = result.key === key;
  return { data: result.data, error: current ? result.error : null, loading: !current, reload };
}
