import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CopilotChatMessageViewNoActivity } from "./CopilotChatMessageViewNoActivity";

vi.mock("@/features/chat/shared/ThinkingCursor", () => ({
  ThinkingCursor: () => <div data-testid="thinking-cursor" />,
}));

vi.mock("@/features/chat/shared/ThinkingAssistantMessage", () => ({
  ThinkingAssistantMessage: () => <div data-testid="thinking-assistant" />,
}));

vi.mock("@copilotkit/react-core/v2", () => {
  const CopilotChatMessageView = ({ messages }: { messages?: Array<{ id: string; role: string; content?: unknown }> }) => (
    <div data-testid="message-view">
      {(messages ?? []).map((message) => (
        <div data-testid="message" data-role={message.role} key={message.id}>
          {String(message.content ?? "")}
        </div>
      ))}
    </div>
  );
  CopilotChatMessageView.Cursor = () => null;
  return {
    CopilotChatAssistantMessage: () => null,
    CopilotChatMessageView,
  };
});

describe("CopilotChatMessageViewNoActivity", () => {
  it("filters activity messages out of the normal chat message view", () => {
    render(
      <CopilotChatMessageViewNoActivity
        messages={[
          { id: "user-1", role: "user", content: "Question" },
          { id: "activity-1", role: "activity", content: { type: "table" } },
          { id: "assistant-1", role: "assistant", content: "Final answer" },
        ]}
      />,
    );

    expect(screen.getByText("Question")).toBeInTheDocument();
    expect(screen.getByText("Final answer")).toBeInTheDocument();
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("message")).toHaveLength(2);
  });
});
