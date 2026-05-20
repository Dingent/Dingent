import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPage } from "./ChatPage";

const updateThreadTitle = vi.fn();
let activeThreadId = "thread-1";
let agentSubscriber: {
  onActivitySnapshotEvent?: (input: { event: any }) => undefined;
  onEvent: (input: { event: any }) => undefined;
} | null = null;
const subscribe = vi.fn((subscriber) => {
  agentSubscriber = subscriber;
  return { unsubscribe: vi.fn() };
});

const agentMessages = [
  { id: "user-1", role: "user", content: "Run the tool" },
  { id: "activity-1", role: "activity", activityType: "a2ui-surface", content: { type: "table", label: "tool table" } },
  { id: "assistant-1", role: "assistant", content: "Done" },
  { id: "activity-2", role: "activity", activityType: "a2ui-surface", content: { type: "todo_list", label: "tool todos" } },
];

vi.mock("next/navigation", () => ({
  useParams: () => ({ slug: "workspace-slug" }),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({
    agent: {
      isRunning: false,
      messages: agentMessages,
      subscribe,
    },
  }),
  useRenderActivityMessage: () => ({
    renderActivityMessage: (message: { id: string; content?: { label?: string } }) => (
      <div data-testid="activity-message">
        {message.id}:{message.content?.label}
      </div>
    ),
  }),
  CopilotSidebar: ({ agentId, threadId }: { agentId?: string; threadId?: string }) => (
    <div data-testid="copilot-sidebar">
      {agentId}:{threadId}
    </div>
  ),
}));

vi.mock("@copilotkit/react-core", () => ({
  useRenderToolCall: vi.fn(),
}));

vi.mock("@/providers/ThreadProvider", () => ({
  useThreadContext: () => ({ activeThreadId, updateThreadTitle }),
}));

vi.mock("@/features/chat/chat-header", () => ({
  ChatHeader: () => <div data-testid="chat-header" />,
}));

vi.mock("@/features/workflows/hooks", () => ({
  useActiveWorkflow: () => ({ workflow: { name: "workflow-agent" } }),
}));

vi.mock("@/lib/api/client", () => ({
  getClientApi: () => ({
    forWorkspace: () => ({ workflows: {} }),
  }),
}));

vi.mock("@/components/CopilotChatMessageViewNoActivity", () => ({
  CopilotChatMessageViewNoActivity: () => <div data-testid="message-view" />,
}));

vi.mock("@/components/common/todo-list-view", () => ({
  TodoListView: () => <div data-testid="todo-list" />,
}));

describe("ChatPage", () => {
  afterEach(() => {
    window.localStorage.removeItem("dingent.debugActivitySnapshot");
    activeThreadId = "thread-1";
    agentSubscriber = null;
    subscribe.mockClear();
    vi.restoreAllMocks();
  });

  it("passes parsed frontend activity messages from CopilotKit agent state to the middle activity list", () => {
    render(<ChatPage />);

    expect(screen.getByTestId("copilot-sidebar")).toHaveTextContent("workflow-agent:thread-1");
    expect(screen.getByText("activity-1:tool table")).toBeInTheDocument();
    expect(screen.getByText("activity-2:tool todos")).toBeInTheDocument();
    expect(screen.getAllByTestId("activity-message")).toHaveLength(2);
    expect(screen.queryByText("user-1:")).not.toBeInTheDocument();
    expect(screen.queryByText("assistant-1:")).not.toBeInTheDocument();
  });

  it("renders activity snapshot events before the final messages snapshot", () => {
    render(<ChatPage />);

    act(() => {
      agentSubscriber?.onActivitySnapshotEvent?.({
        event: {
          type: "ACTIVITY_SNAPSHOT",
          messageId: "activity-live",
          activityType: "a2ui-surface",
          content: { label: "live table" },
        },
      });
    });

    expect(screen.getByText("activity-live:live table")).toBeInTheDocument();
  });

  it("throws when debug activity snapshot assertions are enabled", () => {
    window.localStorage.setItem("dingent.debugActivitySnapshot", "throw");
    render(<ChatPage />);

    expect(() => {
      agentSubscriber?.onActivitySnapshotEvent?.({
        event: {
          type: "ACTIVITY_SNAPSHOT",
          messageId: "activity-live",
          activityType: "a2ui-surface",
          content: { label: "live table" },
        },
      });
    }).toThrow("Received ACTIVITY_SNAPSHOT activity message: activity-live");
  });

  it("keeps live thinking visible after assistant text starts", () => {
    render(<ChatPage />);

    act(() => {
      agentSubscriber?.onEvent({ event: { type: "THINKING_START" } });
      agentSubscriber?.onEvent({ event: { type: "THINKING_TEXT_MESSAGE_CONTENT", delta: "checking tools" } });
      agentSubscriber?.onEvent({ event: { type: "TEXT_MESSAGE_START" } });
    });

    expect(screen.getByText("Thinking Process...")).toBeInTheDocument();
    expect(screen.getByText("checking tools")).toBeInTheDocument();
  });

  it("logs first token time when the first output is thinking text", () => {
    const consoleLog = vi.spyOn(console, "log").mockImplementation(() => undefined);
    vi.spyOn(performance, "now").mockReturnValueOnce(100).mockReturnValueOnce(137.42);
    render(<ChatPage />);

    act(() => {
      agentSubscriber?.onEvent({ event: { type: "RUN_STARTED" } });
      agentSubscriber?.onEvent({ event: { type: "THINKING_TEXT_MESSAGE_CONTENT", delta: "checking tools" } });
      agentSubscriber?.onEvent({ event: { type: "TEXT_MESSAGE_CONTENT", delta: "final answer" } });
    });

    expect(consoleLog).toHaveBeenCalledTimes(1);
    expect(consoleLog).toHaveBeenCalledWith("[Dingent] First token time", {
      elapsedMs: 37.42,
      eventType: "THINKING_TEXT_MESSAGE_CONTENT",
    });
  });

  it("clears live thinking when switching threads", () => {
    const { rerender } = render(<ChatPage />);

    act(() => {
      agentSubscriber?.onEvent({ event: { type: "THINKING_START" } });
      agentSubscriber?.onEvent({ event: { type: "THINKING_TEXT_MESSAGE_CONTENT", delta: "old thread thought" } });
    });
    expect(screen.getByText("old thread thought")).toBeInTheDocument();

    activeThreadId = "thread-2";
    rerender(<ChatPage />);

    expect(screen.queryByText("old thread thought")).not.toBeInTheDocument();
  });
});
