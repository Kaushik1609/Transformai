/**
 * Utility function for combining class names.
 * Used by shadcn/ui components throughout the application.
 */
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
