/**
 * Python -> UI events, the same in every mode: `pdfmanager:<name>` CustomEvents
 * on `window`, with the payload in `event.detail`. The desktop window gets them
 * from Python directly; browser mode's HTTP client and the dev mock dispatch
 * them with {@link emitEvent} (browser mode after polling the app's status).
 */
import type { PdfManagerEvents } from "./types";

/** Name of an event Python can send. */
export type EventName = keyof PdfManagerEvents;

/** Prefix of the DOM events Python dispatches on `window`. */
export const EVENT_PREFIX = "pdfmanager:";

/**
 * Subscribes to an event from Python.
 *
 * Every mode dispatches `pdfmanager:<name>` CustomEvents on `window` with the
 * payload in `event.detail`.
 *
 * @param name - Event name, e.g. `"jobProgress"`.
 * @param handler - Called with the event payload.
 * @returns A function that removes the listener.
 */
export function onEvent<K extends EventName>(
  name: K,
  handler: (payload: PdfManagerEvents[K]) => void,
): () => void {
  const listener = (event: Event) => {
    handler((event as CustomEvent<PdfManagerEvents[K]>).detail);
  };
  window.addEventListener(EVENT_PREFIX + name, listener);
  return () => window.removeEventListener(EVENT_PREFIX + name, listener);
}

/**
 * Dispatches an event the same way Python does. Used by browser mode, the mock and tests.
 *
 * @param name - Event name.
 * @param payload - Event payload, delivered as `event.detail`.
 */
export function emitEvent<K extends EventName>(name: K, payload: PdfManagerEvents[K]): void {
  window.dispatchEvent(new CustomEvent(EVENT_PREFIX + name, { detail: payload }));
}
