/**
 * Utility function for combining class names.
 * Used by shadcn/ui components throughout the application.
 */
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Copy text to the clipboard.
 *
 * Uses the async Clipboard API when available and falls back to the legacy
 * `execCommand("copy")` path so copying still works in insecure contexts
 * (plain http / localhost) and older browsers.  Resolves true on success.
 */
export async function copyText(text: string): Promise<boolean> {
  if (typeof navigator === "undefined" || !text) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy path (permission denied / insecure context)
  }
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.top = "0";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    const selection = document.getSelection();
    const previousRange =
      selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (previousRange && selection) {
      selection.removeAllRanges();
      selection.addRange(previousRange);
    }
    return copied;
  } catch {
    return false;
  }
}
