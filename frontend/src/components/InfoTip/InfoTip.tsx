/**
 * The small circular (?) next to anything that may need explaining (F20).
 */
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import styles from "./InfoTip.module.css";

/** Props for {@link InfoTip}. */
export interface InfoTipProps {
  /** The explanation: short and simple. */
  text: string;
  /** What it explains, for the button's accessible name ("About <label>"). */
  label: string;
}

/** Gap between the (?) and the bubble, and the minimum distance from the window edge. */
const GAP = 8;

/**
 * A (?) button that shows a short explanation while hovered or focused, and
 * toggles on click (for touch). Escape hides it. The bubble is rendered into
 * <body> with fixed positioning so scrolling panels and modals never clip it;
 * it sits above the (?) when there's room, otherwise below.
 */
export function InfoTip({ text, label }: InfoTipProps) {
  const id = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number; below: boolean } | null>(null);

  const show = useCallback(() => setOpen(true), []);
  const hide = useCallback(() => {
    setOpen(false);
    setPosition(null);
  }, []);

  // Measure after the bubble renders, then place it within the window.
  useLayoutEffect(() => {
    if (!open || !buttonRef.current || !bubbleRef.current) return;
    const anchor = buttonRef.current.getBoundingClientRect();
    const bubble = bubbleRef.current.getBoundingClientRect();
    const below = anchor.top - bubble.height - GAP < GAP;
    const top = below ? anchor.bottom + GAP : anchor.top - bubble.height - GAP;
    const centred = anchor.left + anchor.width / 2 - bubble.width / 2;
    const left = Math.min(Math.max(GAP, centred), window.innerWidth - bubble.width - GAP);
    setPosition({ top, left, below });
  }, [open, text]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", hide, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", hide, true);
    };
  }, [open, hide]);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={styles.trigger}
        aria-label={`About ${label}`}
        aria-describedby={open ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={() => (open ? hide() : show())}
      >
        <span aria-hidden="true">?</span>
      </button>
      {open &&
        createPortal(
          <div
            ref={bubbleRef}
            id={id}
            role="tooltip"
            className={`${styles.bubble} ${position ? styles.visible : ""}`}
            style={position ? { top: position.top, left: position.left } : undefined}
          >
            {text}
          </div>,
          document.body,
        )}
    </>
  );
}
