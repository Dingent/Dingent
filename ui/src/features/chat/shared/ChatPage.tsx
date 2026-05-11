"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useAgent, CopilotSidebar } from "@copilotkit/react-core/v2";
import { useRenderToolCall } from "@copilotkit/react-core";

import { Check, CheckCircle2, Loader2 } from "lucide-react";
import {
  AgentSubscriber,
  ThinkingTextMessageContentEvent,
} from "@ag-ui/client";

import { useThreadContext } from "@/providers/ThreadProvider";
import { ChatHeader } from "@/features/chat/chat-header";
import { CopilotChatMessageViewNoActivity } from "@/components/CopilotChatMessageViewNoActivity";
import { CopilotChatActivityList } from "@/components/CopilotChatActivityMessage";
import { useActiveWorkflow } from "@/features/workflows/hooks";
import { getClientApi } from "@/lib/api/client";
import { ThinkingProvider, useThinking } from "@/providers/ThinkingProvider";
import { TodoListView } from "@/components/common/todo-list-view";

interface ChatPageProps {
  isGuest?: boolean;
  visitorId?: string;
  slug?: string;
}

function ChatPageContent({ isGuest, visitorId, slug }: ChatPageProps) {
  const api = getClientApi().forWorkspace(slug, { isGuest, visitorId });
  const { workflow } = useActiveWorkflow(api.workflows, slug);

  const { activeThreadId, updateThreadTitle } = useThreadContext();

  const agentName = workflow?.name || "default";
  const agent = useAgent({ agentId: agentName });
  const isAgentRunning = agent.agent.isRunning;
  const messages = agent.agent.messages;
  const activityMessages = messages.filter((m) => m.role === "activity");
  const [todos, setTodos] = useState(null);

  const { appendThinkingText, clearThinkingText, isThinking, setIsThinking } =
    useThinking();
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
  }, [activeThreadId]);
  useEffect(() => {
    if (!agent.agent) return;

    if (!isThinking) {
      clearThinkingText();
    }

    const thinkingSubscriber: AgentSubscriber = {
      onEvent: ({ event }) => {
        if (event.type === "THINKING_TEXT_MESSAGE_CONTENT") {
          const thinkingEvent = event as ThinkingTextMessageContentEvent;
          appendThinkingText(thinkingEvent.delta);
        } else if (event.type === "THINKING_START") {
          setIsThinking(true);
        } else if (event.type === "TEXT_MESSAGE_START") {
          setIsThinking(false);
        }
        return undefined;
      },
    };

    const subscription = agent.agent.subscribe(thinkingSubscriber);
    return () => subscription.unsubscribe();
  }, [agent.agent, isThinking, appendThinkingText, clearThinkingText]);

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
