import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { usePolling } from "../lib/hooks.js";
it("cancels stale requests and does not let an earlier symbol overwrite a newer one", async () => {
  let finishA, finishB, signalA, signalB;
  const a = vi.fn((signal) => {
      signalA = signal;
      return new Promise((resolve) => (finishA = resolve));
    }),
    b = vi.fn((signal) => {
      signalB = signal;
      return new Promise((resolve) => (finishB = resolve));
    });
  const hook = renderHook(({ load }) => usePolling(load, true, 60000), {
    initialProps: { load: a },
  });
  hook.rerender({ load: b });
  expect(signalA.aborted).toBe(true);
  await act(async () => finishB({ ticker: "AAPL" }));
  await act(async () => finishA({ ticker: "NVDA" }));
  expect(hook.result.current.data.ticker).toBe("AAPL");
  hook.unmount();
  expect(signalB.aborted).toBe(true);
});
