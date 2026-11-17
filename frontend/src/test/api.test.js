import { afterEach, describe, it, expect, vi } from "vitest";
import {
  api,
  apiResponse,
  readChatStream,
  waitForResearch,
} from "../lib/api.js";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it("keeps owner and private trading credentials separate", async () => {
  sessionStorage.setItem("ledger-token", "owner-secret");
  const fetch = vi.fn(async () => new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  await api("/config");
  await api("/trading", { tradingKey: "private-secret" });
  await api("/trading");
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe(
    "Bearer owner-secret",
  );
  expect(fetch.mock.calls[1][1].headers.Authorization).toBe(
    "Bearer private-secret",
  );
  expect(fetch.mock.calls[2][1].headers.Authorization).toBeUndefined();
});
it("reports non-JSON service failures without a JSON parse crash", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("<!DOCTYPE html>", { status: 502 })),
  );
  await expect(api("/research")).rejects.toThrow("unexpected response");
});
it("parses split UTF-8 NDJSON, blank lines and a final line without newline", async () => {
  const bytes = new TextEncoder().encode(
    '\n{"type":"delta","text":"café"}\n{"type":"done"}',
  );
  const body = new ReadableStream({
    start(controller) {
      for (let i = 0; i < bytes.length; i += 2)
        controller.enqueue(bytes.slice(i, i + 2));
      controller.close();
    },
  });
  const items = [];
  for await (const item of readChatStream(new Response(body))) items.push(item);
  expect(items).toEqual([{ type: "delta", text: "café" }, { type: "done" }]);
});
it("resumes polling and retrieves the full completed research report", async () => {
  vi.useFakeTimers();
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "running", stages: 3 })),
    )
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: "complete" })))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "run1",
          status: "complete",
          reports: { technical: {} },
        }),
      ),
    );
  vi.stubGlobal("fetch", fetch);
  const progress = vi.fn();
  const result = waitForResearch({ id: "run1", status: "running" }, progress);
  await vi.advanceTimersByTimeAsync(6000);
  expect((await result).reports.technical).toEqual({});
  expect(progress).toHaveBeenCalledWith(
    expect.stringContaining("3 agent stages"),
  );
  vi.useRealTimers();
});
