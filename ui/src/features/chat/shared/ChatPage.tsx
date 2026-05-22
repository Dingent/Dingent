"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useAgent, CopilotSidebar } from "@copilotkit/react-core/v2";
import { useRenderToolCall } from "@copilotkit/react-core";

import { Check, CheckCircle2, Loader2 } from "lucide-react";
import { ThinkingTextMessageContentEvent } from "@ag-ui/client";

import { useThreadContext } from "@/providers/ThreadProvider";
import { ChatHeader } from "@/features/chat/chat-header";
import { CopilotChatMessageViewNoActivity } from "@/components/CopilotChatMessageViewNoActivity";
import { CopilotChatActivityList } from "@/components/CopilotChatActivityMessage";
import { useActiveWorkflow } from "@/features/workflows/hooks";
import { getClientApi } from "@/lib/api/client";
import { ThinkingProvider, useThinking } from "@/providers/ThinkingProvider";
import { TodoListView } from "@/components/common/todo-list-view";
import { ThinkingAccordion } from "./ThinkingAccordion";

interface ChatPageProps {
  isGuest?: boolean;
  visitorId?: string;
  slug?: string;
}

interface ChatTimingStats {
  agentName: string;
  threadId: string | null;
  runId?: string;
  startedAtMs: number;
  firstEventAtMs?: number;
  runStartedAtMs?: number;
  firstThinkingAtMs?: number;
  firstActivityAtMs?: number;
  firstTextStartAtMs?: number;
  firstTokenAtMs?: number;
  finishedAtMs?: number;
  textDeltaCount: number;
  textCharCount: number;
  thinkingDeltaCount: number;
  thinkingCharCount: number;
  activityCount: number;
  toolCallCount: number;
}

function elapsedMs(startMs: number, endMs?: number) {
  return typeof endMs === "number" ? Math.round((endMs - startMs) * 100) / 100 : null;
}

function getDeltaLength(delta: unknown) {
  return typeof delta === "string" ? delta.length : 0;
}

function shouldThrowOnActivitySnapshot() {
  if (typeof window === "undefined") return false;

  const params = new URLSearchParams(window.location.search);
  if (params.get("debugActivitySnapshot") === "throw") return true;

  return window.localStorage.getItem("dingent.debugActivitySnapshot") === "throw";
}

function ChatPageContent({ isGuest, visitorId, slug }: ChatPageProps) {
  const api = getClientApi().forWorkspace(slug, { isGuest, visitorId });
  const { workflow } = useActiveWorkflow(api.workflows, slug);

  const { activeThreadId, updateThreadTitle } = useThreadContext();

  const agentName = workflow?.name || "default";
  const agent = useAgent({ agentId: agentName });
  const isAgentRunning = agent.agent.isRunning;
  const messages = agent.agent.messages;
  const timingStatsRef = useRef<ChatTimingStats | null>(null);
  const snapshotActivityMessages = messages.filter((m) => m.role === "activity");
  const [streamingActivityMessages, setStreamingActivityMessages] = useState<any[]>([]);
  const activityMessages = useMemo(() => {
    const merged = new Map<string, any>();
    for (const message of streamingActivityMessages) {
      merged.set(message.id, message);
    }
    for (const message of snapshotActivityMessages) {
      merged.set(message.id, message);
    }
    return Array.from(merged.values());
  }, [snapshotActivityMessages, streamingActivityMessages]);
  const [todos, setTodos] = useState(null);
  const runStartTimeRef = useRef<number | null>(null);
  const hasLoggedFirstTokenTimeRef = useRef(false);

  const { appendThinkingText, clearThinkingText, isThinking, setIsThinking, thinkingText } = useThinking();
  useRenderToolCall(
    {
      name: "write_todos",
      render: ({ status, args, result }) => {
        if (!result) return null;
        if (result?.todos) {
          setTodos(result.todos);
        }

        const lastTodo = todos?.[todos?.length - 1];

        const content = lastTodo?.content
          ? lastTodo.content.length > 15
            ? lastTodo.content.slice(0, 15) + "..."
            : lastTodo.content
          : "Initializing...";

        if (status === "complete") {
          return (
            <div className="flex items-center gap-1.5 text-xs text-zinc-500 bg-transparent border-none p-0 mt-1">
              <Check className="w-3 h-3 text-green-500/70" />
              <span>Plan updated.</span>
            </div>
          );
        }

        return (
          <div className="flex items-center gap-1.5 text-xs text-zinc-500 bg-transparent border-none p-0 mt-1">
            <Loader2 className="w-3 h-3 animate-spin text-zinc-600" />
            <span className="opacity-80">
              {todos.length > 0
                ? `Step ${todos.length}: ${content}`
                : "Thinking..."}
            </span>
          </div>
        );
      },
    },
    [activeThreadId],
  );
  useEffect(() => {
    setTodos(null);
    setStreamingActivityMessages([]);
    clearThinkingText();
    setIsThinking(false);
    timingStatsRef.current = null;
  }, [activeThreadId, clearThinkingText, setIsThinking]);
  useEffect(() => {
    if (!agent.agent) return;

    const ensureTimingStats = (event: any, nowMs = performance.now()) => {
      if (!timingStatsRef.current) {
        timingStatsRef.current = {
          agentName,
          threadId: activeThreadId,
          runId: event.runId || event.run_id,
          startedAtMs: nowMs,
          textDeltaCount: 0,
          textCharCount: 0,
          thinkingDeltaCount: 0,
          thinkingCharCount: 0,
          activityCount: 0,
          toolCallCount: 0,
        };
      }

      return timingStatsRef.current;
    };

    const logTimingStats = (event: any) => {
      const stats = timingStatsRef.current;
      if (!stats) return;

      stats.finishedAtMs = performance.now();
      const baselineMs = stats.runStartedAtMs ?? stats.startedAtMs;
      console.info("[Dingent] chat response timings", {
        agentName: stats.agentName,
        threadId: stats.threadId,
        runId: stats.runId || event.runId || event.run_id,
        terminalEvent: event.type,
        totalDurationMs: elapsedMs(stats.startedAtMs, stats.finishedAtMs),
        firstEventMs: elapsedMs(stats.startedAtMs, stats.firstEventAtMs),
        runStartDelayMs: elapsedMs(stats.startedAtMs, stats.runStartedAtMs),
        timeToFirstThinkingMs: elapsedMs(baselineMs, stats.firstThinkingAtMs),
        timeToFirstActivityMs: elapsedMs(baselineMs, stats.firstActivityAtMs),
        timeToFirstTextStartMs: elapsedMs(baselineMs, stats.firstTextStartAtMs),
        timeToFirstTokenMs: elapsedMs(baselineMs, stats.firstTokenAtMs),
        textStreamDurationMs: elapsedMs(stats.firstTokenAtMs ?? baselineMs, stats.finishedAtMs),
        textDeltaCount: stats.textDeltaCount,
        textCharCount: stats.textCharCount,
        thinkingDeltaCount: stats.thinkingDeltaCount,
        thinkingCharCount: stats.thinkingCharCount,
        activityCount: stats.activityCount,
        toolCallCount: stats.toolCallCount,
      });
      timingStatsRef.current = null;
    };

    const handleActivitySnapshot = (activityEvent: any) => {
      const nowMs = performance.now();
      const stats = ensureTimingStats(activityEvent, nowMs);
      stats.activityCount += 1;
      stats.firstActivityAtMs ??= nowMs;

      const messageId = activityEvent.messageId || activityEvent.message_id;
      if (messageId && activityEvent.content) {
        if (shouldThrowOnActivitySnapshot()) {
          throw new Error(`Received ACTIVITY_SNAPSHOT activity message: ${messageId}`);
        }

        setStreamingActivityMessages((prevMessages) => {
          const nextMessages = prevMessages.filter((message) => message.id !== messageId);
          return [
            ...nextMessages,
            {
              id: messageId,
              role: "activity",
              activityType: activityEvent.activityType || activityEvent.activity_type || "a2ui-surface",
              content: activityEvent.content,
            },
          ];
        });
      }
    };

    const logFirstTokenTime = (eventType: string, delta?: string, now = performance.now()) => {
      if (hasLoggedFirstTokenTimeRef.current || !delta) return;

      const runStartTime = runStartTimeRef.current;
      if (runStartTime === null) return;

      hasLoggedFirstTokenTimeRef.current = true;
      console.log("[Dingent] First token time", {
        elapsedMs: Math.round((now - runStartTime) * 100) / 100,
        eventType,
      });
    };

    const thinkingSubscriber = {
      onActivitySnapshotEvent: ({ event }: { event: any }) => {
        handleActivitySnapshot(event);
        return undefined;
      },
      onEvent: ({ event }) => {
        const nowMs = performance.now();
        const stats = ensureTimingStats(event, nowMs);
        stats.firstEventAtMs ??= nowMs;
        stats.runId = stats.runId || event.runId || event.run_id;

        if (event.type === "RUN_STARTED") {
          stats.runStartedAtMs ??= nowMs;
          runStartTimeRef.current = nowMs;
          hasLoggedFirstTokenTimeRef.current = false;
        } else if (event.type === "THINKING_START") {
          stats.firstThinkingAtMs ??= nowMs;
        } else if (event.type === "TEXT_MESSAGE_START") {
          stats.firstTextStartAtMs ??= nowMs;
        } else if (event.type === "THINKING_TEXT_MESSAGE_CONTENT") {
          const thinkingEvent = event as ThinkingTextMessageContentEvent;
          stats.firstThinkingAtMs ??= nowMs;
          stats.firstTokenAtMs ??= nowMs;
          stats.thinkingDeltaCount += 1;
          stats.thinkingCharCount += getDeltaLength(thinkingEvent.delta);
          logFirstTokenTime(event.type, thinkingEvent.delta, nowMs);
        } else if (event.type === "TEXT_MESSAGE_CONTENT") {
          stats.firstTokenAtMs ??= nowMs;
          stats.textDeltaCount += 1;
          stats.textCharCount += getDeltaLength(event.delta);
        } else if (event.type === "REASONING_MESSAGE_CONTENT") {
          stats.firstTokenAtMs ??= nowMs;
          stats.textDeltaCount += 1;
          stats.textCharCount += getDeltaLength(event.delta);
        } else if (event.type === "TOOL_CALL_START") {
          stats.toolCallCount += 1;
        }

        if (event.type === "THINKING_TEXT_MESSAGE_CONTENT") {
          const thinkingEvent = event as ThinkingTextMessageContentEvent;
          appendThinkingText(thinkingEvent.delta);
        } else if (event.type === "TEXT_MESSAGE_CONTENT" || event.type === "REASONING_MESSAGE_CONTENT") {
          logFirstTokenTime(event.type, event.delta, nowMs);
        } else if (event.type === "ACTIVITY_SNAPSHOT") {
          handleActivitySnapshot(event);
        } else if (event.type === "THINKING_START") {
          clearThinkingText();
          setIsThinking(true);
        } else if (event.type === "THINKING_END" || event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") {
          if (event.type !== "THINKING_END") {
            runStartTimeRef.current = null;
          }
          setIsThinking(false);
        }
        if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") {
          logTimingStats(event);
        }
        return undefined;
      },
    };

    const subscription = agent.agent.subscribe(thinkingSubscriber as Parameters<typeof agent.agent.subscribe>[0]);
    return () => subscription.unsubscribe();
  }, [activeThreadId, agent.agent, agentName, appendThinkingText, clearThinkingText, setIsThinking]);

  useEffect(() => {
    if (activeThreadId) {
      updateThreadTitle();
    }
  }, [isAgentRunning, activeThreadId, updateThreadTitle]);

  if (isGuest && !visitorId) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-zinc-900 via-zinc-950 to-black">
        <Loader2 className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!activeThreadId) return null;

  return (
    <main
      className="
        flex flex-col h-screen w-full overflow-hidden
        bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-zinc-900 via-zinc-950 to-black"
    >
      <div
        className="
          flex-shrink-0 w-full h-full max-w-7xl mx-auto px-4 sm:px-6 py-4
          overflow-y-auto
        "
      >
        {(isThinking || thinkingText) && (
          <ThinkingAccordion content={thinkingText} isThinking={isThinking} label="Thinking Process..." />
        )}
        {todos && <TodoListView key={activeThreadId} data={todos} />}
        <CopilotChatActivityList messages={activityMessages} />
      </div>
      <CopilotSidebar
        agentId={workflow?.name}
        threadId={activeThreadId}
        messageView={CopilotChatMessageViewNoActivity}
        header={ChatHeader as any}
      />
    </main>
  );
}

export function ChatPage({ isGuest = false, visitorId }: ChatPageProps) {
  const params = useParams();
  const slug = params.slug as string;

  return (
    <ThinkingProvider>
      <ChatPageContent isGuest={isGuest} visitorId={visitorId} slug={slug} />
    </ThinkingProvider>
  );
}
