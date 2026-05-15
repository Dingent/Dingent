import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createA2UIMessageRenderer } from "./MyA2UIMessageRenderer";

const processMessages = vi.fn();

vi.mock("@copilotkit/a2ui-renderer", () => ({
  A2UIProvider: ({ children }: { children: React.ReactNode }) => <div data-testid="a2ui-provider">{children}</div>,
  A2UIRenderer: ({ surfaceId }: { surfaceId: string }) => <div data-testid="a2ui-renderer">{surfaceId}</div>,
  useA2UIActions: () => ({ processMessages }),
}));

vi.mock("react-photo-view", () => ({
  PhotoProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PhotoView: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("react-photo-view/dist/react-photo-view.css", () => ({}));

vi.mock("./A2UI/data-table", () => ({
  DataTable: ({ data }: { data: Array<Record<string, unknown>> }) => <div data-testid="legacy-table">{data.length} rows</div>,
}));

describe("createA2UIMessageRenderer", () => {
  it("routes official A2UI operations through the official provider and renderer", async () => {
    const renderer = createA2UIMessageRenderer({});
    const operations = [{ createSurface: { surfaceId: "surface-1" } }, { updateDataModel: { surfaceId: "surface-1", value: { title: "Result" } } }];
    const Render = renderer.render;

    render(<Render activityType="a2ui-surface" content={{ a2ui_operations: operations }} message={{}} agent={{}} />);

    expect(screen.getByTestId("a2ui-provider")).toBeInTheDocument();
    expect(screen.getByTestId("a2ui-renderer")).toHaveTextContent("surface-1");
    await waitFor(() => expect(processMessages).toHaveBeenCalledWith(operations));
  });

  it("keeps the legacy table renderer as a fallback for persisted activity messages", () => {
    const renderer = createA2UIMessageRenderer({});
    const Render = renderer.render;

    render(<Render activityType="a2ui-surface" content={{ type: "table", columns: ["name"], rows: [{ name: "Alice" }] }} message={{}} agent={{}} />);

    expect(screen.getByTestId("legacy-table")).toHaveTextContent("1 rows");
  });

  it("renders markdown activity content with GFM tables", () => {
    const renderer = createA2UIMessageRenderer({});
    const Render = renderer.render;

    render(
      <Render
        activityType="a2ui-surface"
        content={{ type: "markdown", title: "Result", content: "| Name | Score |\n| --- | ---: |\n| Alice | 95 |" }}
        message={{}}
        agent={{}}
      />,
    );

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
  });
});
