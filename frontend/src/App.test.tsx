import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import App from "./App";

test("renders the project baseline", () => {
  const html = renderToStaticMarkup(<App />);

  expect(html).toContain("Personal Workbench");
  expect(html).toContain("项目骨架已启动");
});
