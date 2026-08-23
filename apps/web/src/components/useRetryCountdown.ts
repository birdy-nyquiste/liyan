import { useEffect, useState } from "react";

function secondsUntil(allowedAt: string | null, nowMs: number): number {
  if (!allowedAt) return 0;
  return Math.max(0, Math.ceil((new Date(allowedAt).getTime() - nowMs) / 1000));
}

/** Render only the retry moment supplied by the server; browser state owns no policy. */
export function useRetryCountdown(allowedAt: string | null, onElapsed: () => void): number {
  const [seconds, setSeconds] = useState(() => secondsUntil(allowedAt, Date.now()));

  useEffect(() => {
    setSeconds(secondsUntil(allowedAt, Date.now()));
    if (!allowedAt) return;
    const ticker = setInterval(() => {
      const left = secondsUntil(allowedAt, Date.now());
      setSeconds(left);
      if (left === 0) {
        clearInterval(ticker);
        onElapsed();
      }
    }, 1000);
    return () => clearInterval(ticker);
  }, [allowedAt, onElapsed]);

  return seconds;
}
