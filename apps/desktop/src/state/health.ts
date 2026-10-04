import { useEffect, useState } from "react";

export type HealthState<T> = { online: boolean | null; data: T | null; error: string | null };

/** Poll a health endpoint every `intervalMs`. `online` is null until the first answer. */
export function useHealth<T>(fetcher: (signal: AbortSignal) => Promise<T>, intervalMs = 3000): HealthState<T> {
  const [st, setSt] = useState<HealthState<T>>({ online: null, data: null, error: null });
  useEffect(() => {
    let alive = true;
    let ctrl: AbortController | null = null;
    setSt({ online: null, data: null, error: null });
    const tick = async () => {
      ctrl?.abort();
      ctrl = new AbortController();
      try {
        const data = await fetcher(ctrl.signal);
        if (alive) setSt({ online: true, data, error: null });
      } catch (e) {
        if (alive) setSt({ online: false, data: null, error: e instanceof Error ? e.message : String(e) });
      }
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
      ctrl?.abort();
    };
  }, [fetcher, intervalMs]);
  return st;
}
