/**
 * Treasury-reviewer passcode, held ONLY in this tab's sessionStorage (never bundled, never in NEXT_PUBLIC_*).
 * The console sends it as X-Reviewer-Token on mutating governance calls; the backend enforces it.
 */

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "praxis_reviewer_token";
const CHANGED = "praxis:reviewer-changed";
const REQUIRED = "praxis:reviewer-required";

export const REVIEWER_REQUIRED_TEXT = "Treasury Reviewer Passcode Required (Protected Endpoint)";

export function getReviewerToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setReviewerToken(value: string | null): void {
  try {
    if (value) window.sessionStorage.setItem(STORAGE_KEY, value);
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable (private mode) — the header simply won't be sent */
  }
  window.dispatchEvent(new Event(CHANGED));
}

/** Ask the header's Reviewer Auth popover to open with the "passcode required" notice. */
export function requestReviewerAuth(): void {
  window.dispatchEvent(new Event(REQUIRED));
}

export function onReviewerAuthRequested(cb: () => void): () => void {
  window.addEventListener(REQUIRED, cb);
  return () => window.removeEventListener(REQUIRED, cb);
}

function subscribe(cb: () => void) {
  window.addEventListener(CHANGED, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(CHANGED, cb);
    window.removeEventListener("storage", cb);
  };
}

/** Reactive passcode presence; `null` during SSR so hydration always matches. */
export function useReviewerToken(): string | null {
  return useSyncExternalStore(subscribe, getReviewerToken, () => null);
}
