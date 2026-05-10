// @vitest-environment happy-dom
//
// A.9 render smoke for ResultsPage. Verifies the component mounts without
// crashing and surfaces the data prop. Not a visual / styling test.

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import ResultsPage from "./ResultsPage.jsx";
import sampleData from "./sampleData.js";

afterEach(() => cleanup());

describe("ResultsPage", () => {
  it("renders the numeric score from the data prop", () => {
    const { container } = render(<ResultsPage data={sampleData} />);
    expect(container.textContent).toContain(String(sampleData.score));
  });

  it("renders all four category labels", () => {
    const { container } = render(<ResultsPage data={sampleData} />);
    expect(container.textContent).toContain("AI Presence");
    expect(container.textContent).toContain("SEO Strength");
    expect(container.textContent).toContain("Authority");
    expect(container.textContent).toContain("Performance");
  });

  it("returns null when data prop is null", () => {
    const { container } = render(<ResultsPage data={null} />);
    expect(container.firstChild).toBeNull();
  });
});
