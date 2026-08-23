import { useEffect, useRef } from "react";

/**
 * Focus an element when a condition first becomes true, and not again until it
 * has been false.
 *
 * The 任务详情 focus rule is stated per phase — 知言 while any report is missing,
 * 立言 once every report is in — so focus must move when the phase changes and
 * stay put through the polling that happens inside a phase.
 */
export function useFocusWhen<T extends HTMLElement>(active: boolean) {
  const element = useRef<T>(null);
  const alreadyFocused = useRef(false);

  useEffect(() => {
    if (!active) {
      alreadyFocused.current = false;
      return;
    }
    if (alreadyFocused.current) return;
    alreadyFocused.current = true;
    element.current?.focus();
  }, [active]);

  return element;
}
