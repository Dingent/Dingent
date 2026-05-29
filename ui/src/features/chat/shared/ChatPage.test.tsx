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

  it("logs aggregated chat response timings when a run completes", () => {
    const consoleInfo = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const performanceNow = vi.spyOn(performance, "now").mockImplementation(() => 100);
    render(<ChatPage />);

    act(() => {
      agentSubscriber?.onEvent({ event: { type: "RUN_STARTED", runId: "run-1" } });
      agentSubscriber?.onEvent({ event: { type: "THINKING_TEXT_MESSAGE_CONTENT", delta: "thinking" } });
      agentSubscriber?.onEvent({ event: { type: "TEXT_MESSAGE_CONTENT", delta: "hello" } });
      agentSubscriber?.onEvent({ event: { type: "TOOL_CALL_START" } });
      agentSubscriber?.onEvent({ event: { type: "ACTIVITY_SNAPSHOT", messageId: "activity-live", content: { label: "live table" } } });
      agentSubscriber?.onEvent({ event: { type: "RUN_FINISHED", runId: "run-1" } });
    });

    expect(consoleInfo).toHaveBeenCalledWith(
      "[Dingent] chat response timings",
      expect.objectContaining({
        runId: "run-1",
        terminalEvent: "RUN_FINISHED",
        frontendObservedDurationMs: expect.any(Number),
        timeToFirstThinkingTokenMs: expect.any(Number),
        timeToFirstTextTokenMs: expect.any(Number),
        timeToFirstVisibleOutputMs: expect.any(Number),
        textStreamDurationMs: expect.any(Number),
        textDeltaCount: 1,
        textCharCount: 5,
        thinkingDeltaCount: 1,
        thinkingCharCount: 8,
        reasoningDeltaCount: 0,
        reasoningCharCount: 0,
        activityCount: 1,
        toolCallCount: 1,
      }),
    );

    consoleInfo.mockRestore();
    performanceNow.mockRestore();
  });

  it("starts a fresh timing window for each run started event", () => {
    const consoleInfo = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const performanceNow = vi.spyOn(performance, "now").mockReturnValue(0);
    render(<ChatPage />);

    act(() => {
      performanceNow.mockReturnValue(100);
      agentSubscriber?.onEvent({ event: { type: "TEXT_MESSAGE_CONTENT", runId: "old-run", delta: "stale" } });
      performanceNow.mockReturnValue(1_000);
      agentSubscriber?.onEvent({ event: { type: "RUN_STARTED", runId: "new-run" } });
      performanceNow.mockReturnValue(1_250);
      agentSubscriber?.onEvent({ event: { type: "THINKING_TEXT_MESSAGE_CONTENT", runId: "old-run", delta: "old thought" } });
      performanceNow.mockReturnValue(1_500);
      agentSubscriber?.onEvent({ event: { type: "THINKING_TEXT_MESSAGE_CONTENT", runId: "new-run", delta: "thinking" } });
      performanceNow.mockReturnValue(2_000);
      agentSubscriber?.onEvent({ event: { type: "RUN_FINISHED", runId: "new-run" } });
    });

    expect(consoleInfo).toHaveBeenCalledWith(
      "[Dingent] chat response timings",
      expect.objectContaining({
        runId: "new-run",
        frontendObservedDurationMs: 1_000,
        timeToFirstThinkingTokenMs: 500,
        thinkingDeltaCount: 1,
        thinkingCharCount: 8,
      }),
    );

    consoleInfo.mockRestore();
    performanceNow.mockRestore();
  });

  it("logs aggregated timings even when the terminal event has a different run id", () => {
    const consoleInfo = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const consoleLog = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const performanceNow = vi.spyOn(performance, "now").mockReturnValue(0);
    render(<ChatPage />);

    act(() => {
      performanceNow.mockReturnValue(1_000);
      agentSubscriber?.onEvent({ event: { type: "RUN_STARTED", runId: "started-run" } });
      performanceNow.mockReturnValue(1_200);
      agentSubscriber?.onEvent({ event: { type: "TEXT_MESSAGE_CONTENT", delta: "hello" } });
      performanceNow.mockReturnValue(1_500);
      agentSubscriber?.onEvent({ event: { type: "RUN_FINISHED", runId: "terminal-run" } });
    });

    expect(consoleInfo).toHaveBeenCalledWith(
      "[Dingent] chat response timings",
      expect.objectContaining({
        runId: "started-run",
        timeToFirstTextTokenMs: 200,
        textDeltaCount: 1,
        textCharCount: 5,
      }),
    );
    expect(consoleLog).not.toHaveBeenCalledWith("[Dingent] first text token timing", expect.anything());

    consoleInfo.mockRestore();
    consoleLog.mockRestore();
    performanceNow.mockRestore();
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
