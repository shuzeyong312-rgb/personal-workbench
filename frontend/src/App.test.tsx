import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import App, { getResponseStatus } from "./App";

test("renders the add competitor form", () => {
  const html = renderToStaticMarkup(<App />);

  expect(html).toContain("添加 1688 竞品");
  expect(html).toContain('id="competitor-url"');
  expect(html).toContain("添加竞品");
  expect(html).toContain("仅支持 detail.1688.com/offer/");
});

test.each([
  [true, undefined, "success"],
  [false, "invalid_competitor_url", "invalid"],
  [false, "competitor_already_exists", "duplicate"],
] as const)("maps API result to %s UI state", (ok, code, expected) => {
  expect(getResponseStatus(ok, code)).toBe(expected);
});
