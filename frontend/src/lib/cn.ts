/// lib/cn.ts — minimal className joiner (no external dependency needed).
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
