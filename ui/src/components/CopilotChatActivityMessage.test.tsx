import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CopilotChatActivityList } from "./CopilotChatActivityMessage";

vi.mock("@copilotkit/react-core/v2", () => ({
  useRenderActivityMessage: () => ({
    renderActivityMessage: (message: { id: string; content: { type?: string; label?: string } }) => (
      <div data-testid="activity-message">
        {message.id}:{message.content?.label ?? message.content?.type}
      </div>
    ),
  }),
}));

describe("CopilotChatActivityList", () => {
  it("renders non-todo activities and only the latest todo list", () => {
    render(
      <CopilotChatActivityList
        messages={[
          { id: "todo-old", role: "activity", activityType: "a2ui-surface", content: { type: "todo_list", label: "old todos" } },
          { id: "table-1", role: "activity", activityType: "a2ui-surface", content: { type: "table", label: "table result" } },
          { id: "todo-new", role: "activity", activityType: "a2ui-surface", content: { type: "todo_list", label: "new todos" } },
        ]}
      />,
    );

    expect(screen.queryByText("todo-old:old todos")).not.toBeInTheDocument();
    expect(screen.getByText("table-1:table result")).toBeInTheDocument();
    expect(screen.getByText("todo-new:new todos")).toBeInTheDocument();
    expect(screen.getAllByTestId("activity-message")).toHaveLength(2);
  });
});
