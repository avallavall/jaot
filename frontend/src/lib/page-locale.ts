/**
 * The language the page is written in, for code outside a React component.
 *
 * `<html lang>` carries it (app/[locale]/layout.tsx). Number formatting with
 * `toLocaleString(undefined, …)` followed the browser instead, so a Spanish
 * page on an English system showed `1,234.5` next to an ICU message that
 * said `1.234,5`.
 *
 * Inside a component, use next-intl's `useLocale()`: it is also right while
 * the server renders, where there is no document and this returns undefined.
 */
export function pageLocale(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.documentElement.lang || undefined;
}
