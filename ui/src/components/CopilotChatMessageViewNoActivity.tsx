import { ThinkingAssistantMessage } from "@/features/chat/shared/ThinkingAssistantMessage";
import { ThinkingCursor } from "@/features/chat/shared/ThinkingCursor";
import {
  CopilotChatAssistantMessage,
  CopilotChatMessageView,
  CopilotChatMessageViewProps,
} from "@copilotkit/react-core/v2";

import { useMemo } from "react";

const CopilotChatMessageViewNoActivityImpl = (
  props: CopilotChatMessageViewProps,
) => {
  const filteredMessages = useMemo(() => {
    return props.messages?.filter((m) => m.role !== "activity") || [];
  }, [props.messages]);

  return (
    <CopilotChatMessageView
      {...props}
      messages={filteredMessages}
      cursor={ThinkingCursor}
      assistantMessage={
        ThinkingAssistantMessage as typeof CopilotChatAssistantMessage
      }
    />
  );
};

CopilotChatMessageViewNoActivityImpl.Cursor = CopilotChatMessageView.Cursor;
CopilotChatMessageViewNoActivityImpl.AssistantMessage =
  ThinkingAssistantMessage;

export const CopilotChatMessageViewNoActivity =
  CopilotChatMessageViewNoActivityImpl as typeof CopilotChatMessageView;
