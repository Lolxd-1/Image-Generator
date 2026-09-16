/// screens/generate/jobStorage.ts — remembers the active generate job id per
/// shop in localStorage. SPEC.md §6 has no "current running job for a shop"
/// endpoint, so once Review.tsx (or Catalog.tsx, for a regenerate) creates a
/// generate Job, the id has to be carried to Generate.tsx some other way —
/// this lets a closed-and-reopened tab (not just a same-tab remount) resume
/// the exact same run, matching the "closing this tab pauses the run, nothing
/// is lost" promise in Generate.tsx.
const KEY_PREFIX = "menu-catalog:generate-job:";

export function getStoredJobId(shopId: string): string | null {
  try {
    return window.localStorage.getItem(KEY_PREFIX + shopId);
  } catch {
    return null;
  }
}

export function setStoredJobId(shopId: string, jobId: string): void {
  try {
    window.localStorage.setItem(KEY_PREFIX + shopId, jobId);
  } catch {
    // private mode / quota — the query-string `?job=` fallback still works.
  }
}

export function clearStoredJobId(shopId: string): void {
  try {
    window.localStorage.removeItem(KEY_PREFIX + shopId);
  } catch {
    // ignore
  }
}
