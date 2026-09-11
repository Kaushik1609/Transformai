/**
 * TransformIQ — Modal accessibility hook (UI-8 / a11y hardening).
 *
 * Provides the keyboard + focus behaviour the app's hand-rolled dialogs and
 * drawer need to match the platform dialogs they replace:
 *
 *   - focuses the dialog container when it opens and returns focus to the
 *     previously-focused element when it closes,
 *   - locks body scroll while the dialog is open and restores it on close,
 *   - closes on Escape,
 *   - traps Tab so focus annoty escape the dialog (rings back to the first /
 *     last focusable element).
 *
 * The dialog element must have `tabIndex={-1}` so it can receive programmatic
 * focus, and `role="dialog"` / `aria-modal` the caller already provides.
 */
"use client";

import type { RefObject } from "react";
import { useEffect, useRef } from "react";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

export function useModalA11y(
  open: boolean,
  onClose: () => void,
  dialogRef: RefObject<HTMLElement | null>,
) {
  // Keep the latest onClose in a ref so the effect below only re-runs when the
  // dialog actually opens/closes (an inline arrow identity would otherwise
  // tear down and restore focus on every render inside the dialog).
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;

    const previouslyFocused =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    const dialog = dialogRef.current;
    const body = document.body;
    const previousOverflow = body.style.overflow;
    body.style.overflow = "hidden";

    if (dialog && typeof dialog.focus === "function") {
      dialog.focus();
    }

    const focusable = () => {
      if (!dialog) return [];
      return Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const items = focusable();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const inside = dialog.contains(active);
      if (event.shiftKey && (!inside || active === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || active === last)) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      body.style.overflow = previousOverflow;
      // Return focus to the trigger that opened the dialog.
      if (previouslyFocused) previouslyFocused.focus();
    };
  }, [open, dialogRef]);
}