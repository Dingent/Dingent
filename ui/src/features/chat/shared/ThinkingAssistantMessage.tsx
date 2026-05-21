import React from "react";
import { AssistantMessage } from "@ag-ui/core";
import { twMerge } from "tailwind-merge";
import {
  CopilotChatAssistantMessage,
  CopilotChatAssistantMessageProps,
} from "@copilotkit/react-core/v2";
import { ThinkingAccordion } from "./ThinkingAccordion";
export function ThinkingAssistantMessage(
  props: CopilotChatAssistantMessageProps,
) {
  const message = props.message as AssistantMessage;
  const content = message.content || "";

  // Extract thinking content
  const regex = /<thinking>([\s\S]*?)<\/thinking>/;
  const match = content.match(regex);

  let thinkingContent = "";
  // We don't strip the thinking tags from the message passed to CopilotChatAssistantMessage
  // because typically the UI library handles clean rendering, or you might need to
  // manually pass a cleaner message prop if Copilot doesn't handle hidden tags.
  // Assuming the original behavior was desired:
  let cleanMessage = { ...message };

  if (match) {
    thinkingContent = match[1];
    // Create a copy of the message with cleaned content for the main display
    cleanMessage.content = content.replace(match[0], "").trim();
  }
  const isRunning = props.isRunning;
  // If no thinking content found, render default
  if (!thinkingContent) {
    return <CopilotChatAssistantMessage {...props} />;
  }
  return (
    <div
      className={twMerge(
        "flex flex-col gap-2 w-full max-w-full",
        props.className,
      )}
    >
      <ThinkingAccordion
        content={thinkingContent}
        isThinking={isRunning}
        defaultExpanded={!!(isRunning && thinkingContent)}
      />

      {/* Standard Assistant Message Content */}
      <CopilotChatAssistantMessage
        {...props}
        message={cleanMessage}
        // Reset class to avoid conflicts
        className=""
      />
    </div>
  );
}
