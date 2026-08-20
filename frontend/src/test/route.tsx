/**
 * Rendering an App Router page in a test.
 *
 * A route component takes `params` as a Promise and unwraps it with React 19's
 * `use()`. That suspends on the first render, so `render(<Page params={...} />)`
 * alone leaves the DOM holding the Suspense fallback for ever: the promise
 * resolves in a microtask that nothing flushes, and the page never mounts. Four
 * attempts at the join page ended that way and it went into the debt register as
 * a hole every route has.
 *
 * The recipe is one line: put the render INSIDE an awaited `act`. The boundary
 * catches the suspension, `act` flushes the microtask that resolves the promise,
 * and React commits the real tree before the assertion runs. A separate
 * `await act(async () => {})` after the render is NOT enough — measured.
 */
import { Suspense, type ReactElement } from "react";
import { act } from "react";
import { render, type RenderResult } from "@testing-library/react";

/**
 * Render a route component and wait until it has mounted.
 *
 *   const page = await renderRoute(<JoinPage params={routeParams({ token: "t" })} />);
 */
export async function renderRoute(ui: ReactElement): Promise<RenderResult> {
  let result!: RenderResult;
  await act(async () => {
    result = render(<Suspense fallback={null}>{ui}</Suspense>);
  });
  return result;
}

/** The shape the App Router hands a page: its params, already resolved. */
export function routeParams<T extends Record<string, string>>(values: T): Promise<T> {
  return Promise.resolve(values);
}
