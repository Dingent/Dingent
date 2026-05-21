import { useThinking } from "@/providers/ThinkingProvider";
import { twMerge } from "tailwind-merge";
import { ThinkingAccordion } from "./ThinkingAccordion";
export function ThinkingCursor({ className }: { className?: string }) {
  const { thinkingText, isThinking } = useThinking();
  if (!isThinking) {
    return (
      <span
        className={twMerge(
          "inline-block w-1.5 h-4 ml-1 align-middle bg-zinc-900 dark:bg-zinc-100 animate-pulse",
          className,
        )}
      />
    );
  }
  return (
    <ThinkingAccordion
      content={thinkingText}
      isThinking={isThinking}
      className={className}
      label="Thinking Process..."
    />
  );
}
