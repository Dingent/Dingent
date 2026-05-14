import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ThinkingAssistantMessage } from "./ThinkingAssistantMessage";

vi.mock("streamdown", () => ({
  Streamdown: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChatAssistantMessage: ({ message }: { message: { content?: string } }) => <div data-testid="assistant-message">{message.content}</div>,
}));

describe("ThinkingAssistantMessage", () => {
  it("renders thinking content separately and strips it from the assistant message", () => {
    render(
      <ThinkingAssistantMessage
        message={{ id: "assistant-1", role: "assistant", content: "<thinking>check the route</thinking>Final answer" }}
        isRunning={true}
      />,
    );

    expect(screen.getByText("Thinking Process")).toBeInTheDocument();
    expect(screen.getByText("check the route")).toBeInTheDocument();
    expect(screen.getByTestId("assistant-message")).toHaveTextContent("Final answer");
    expect(screen.getByTestId("assistant-message")).not.toHaveTextContent("thinking");
  });

  it("falls back to the standard assistant renderer when there is no thinking block", () => {
    render(<ThinkingAssistantMessage message={{ id: "assistant-2", role: "assistant", content: "Plain final answer" }} isRunning={false} />);

    expect(screen.queryByText("Thinking Process")).not.toBeInTheDocument();
    expect(screen.getByTestId("assistant-message")).toHaveTextContent("Plain final answer");
  });
});
