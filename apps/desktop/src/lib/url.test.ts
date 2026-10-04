import { describe, expect, it } from "vitest";
import { isHttpUrl, joinUrl, toWsUrl, trimBase } from "./url";

describe("url helpers", () => {
  it("converts http(s) to ws(s)", () => {
    expect(toWsUrl("http://127.0.0.1:8700")).toBe("ws://127.0.0.1:8700/ws");
    expect(toWsUrl("https://gcs.example.com/")).toBe("wss://gcs.example.com/ws");
    expect(toWsUrl("HTTP://host:1/prefix/", "/ws")).toBe("ws://host:1/prefix/ws");
    expect(toWsUrl("ws://already:1")).toBe("ws://already:1/ws");
    expect(toWsUrl("localhost:8700")).toBe("ws://localhost:8700/ws");
  });

  it("joins without doubling slashes", () => {
    expect(joinUrl("http://a:1/", "/api/x")).toBe("http://a:1/api/x");
    expect(joinUrl("http://a:1", "api/x")).toBe("http://a:1/api/x");
    expect(trimBase(" http://a:1/// ")).toBe("http://a:1");
  });

  it("validates http urls", () => {
    expect(isHttpUrl("http://127.0.0.1:8700")).toBe(true);
    expect(isHttpUrl("https://x")).toBe(true);
    expect(isHttpUrl("ftp://x")).toBe(false);
    expect(isHttpUrl("nope")).toBe(false);
  });
});
