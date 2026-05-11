import React, { useMemo } from "react";
import { ActivityMessage } from "@ag-ui/core";
import { twMerge } from "tailwind-merge";
import { useRenderActivityMessage } from "@copilotkit/react-core/v2";

/**
 * 内部使用的 Memoized 组件
 * 保持这个 Wrapper 存在，是为了确保列表中单个未变化的消息不会因为父组件重渲染而重绘
 */
const MemoizedActivityMessage = React.memo(
  function MemoizedActivityMessage({
    message,
    renderActivityMessage,
  }: {
    message: ActivityMessage;
    renderActivityMessage: (
      message: ActivityMessage,
    ) => React.ReactElement | null;
  }) {
    return renderActivityMessage(message);
  },
  (prevProps, nextProps) => {
    // 性能优化逻辑：只在 ID、类型或内容变化时重新渲染
    if (prevProps.message.id !== nextProps.message.id) return false;
    if (prevProps.message.activityType !== nextProps.message.activityType)
      return false;
    if (
      JSON.stringify(prevProps.message.content) !==
      JSON.stringify(nextProps.message.content)
    )
      return false;
    return true;
  },
);

export interface CopilotChatActivityListProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * 接收 Activity 消息数组
   */
  messages: ActivityMessage[];
}

/**
 * 专门用于渲染 Activity 消息列表的组件
 */
export function CopilotChatActivityList({
  messages,
  className,
  ...props
}: CopilotChatActivityListProps) {
  // 获取渲染逻辑的 Hook
  const renderActivityMessage = useRenderActivityMessage();
  const visibleMessages = useMemo(() => {
    if (!messages || messages.length === 0) return [];

    let lastTodoListIndex = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      const content = messages[i].content as any;
      if (
        content &&
        typeof content === "object" &&
        content.type === "todo_list"
      ) {
        lastTodoListIndex = i;
        break; // 找到了最后一个，停止循环
      }
    }

    return messages.filter((msg, index) => {
      const content = msg.content as any;

      const isTodoList =
        content && typeof content === "object" && content.type === "todo_list";

      if (isTodoList) {
        return index === lastTodoListIndex;
      }

      return true;
    });
  }, [messages]);

  if (
    !renderActivityMessage ||
    !visibleMessages ||
    visibleMessages.length === 0
  ) {
    return null;
  }
  // 使用 useMemo 计算最终需要显示的列表
  // 逻辑：保留所有非 'todo_list' 的消息，但对于 'todo_list'，只保留数组中出现的最后一个

  return (
    <div className={twMerge("flex flex-col gap-2", className)} {...props}>
      {visibleMessages.map((visibleMessages) => (
        <MemoizedActivityMessage
          key={visibleMessages.id}
          message={visibleMessages}
          renderActivityMessage={renderActivityMessage}
        />
      ))}
    </div>
  );
}
