import { BrainCircuit, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { twMerge } from "tailwind-merge";
import { Streamdown } from "streamdown";
interface ThinkingAccordionProps {
  content: string;
  isThinking?: boolean;
  defaultExpanded?: boolean;
  className?: string;
  label?: string;
}
export function ThinkingAccordion({
  content,
  isThinking = false,
  defaultExpanded = true,
  className,
  label = "Thinking Process",
}: ThinkingAccordionProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Auto-scroll logic when content updates and is thinking
  useEffect(() => {
    if (isThinking && isExpanded && scrollRef.current) {
      const element = scrollRef.current;
      element.scrollTop = element.scrollHeight;
    }
  }, [content, isExpanded, isThinking]);
  // Update expansion state when thinking starts
  useEffect(() => {
    if (isThinking) {
      setIsExpanded(true);
    }
  }, [isThinking]);
  if (!content && isThinking) {
    return (
      <div
        className={twMerge(
          "flex items-center gap-2 text-muted-foreground text-sm py-2",
          className,
        )}
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>Thinking...</span>
      </div>
    );
  }
  if (!content) return null;
  return (
    <div className={twMerge("w-full max-w-full my-2", className)}>
      <div className="border border-indigo-100 dark:border-indigo-900/50 bg-indigo-50/50 dark:bg-indigo-950/20 rounded-lg overflow-hidden transition-all duration-300">
        <button
          onClick={(e) => {
            e.preventDefault();
            setIsExpanded(!isExpanded);
          }}
          className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100/50 dark:hover:bg-indigo-900/30 transition-colors text-left select-none"
          type="button"
        >
          {isThinking ? (
            <BrainCircuit className="w-4 h-4 animate-pulse" />
          ) : (
            <BrainCircuit className="w-4 h-4" />
          )}
          <span>{label}</span>
          {isExpanded ? (
            <ChevronDown className="w-3 h-3 ml-auto opacity-70" />
          ) : (
            <ChevronRight className="w-3 h-3 ml-auto opacity-70" />
          )}
        </button>
        {isExpanded && (
          <div
            ref={scrollRef}
            className="px-3 py-2 text-xs text-zinc-600 dark:text-zinc-400 bg-white/50 dark:bg-black/20 border-t border-indigo-100 dark:border-indigo-900/30 max-h-[300px] overflow-y-auto scroll-smooth"
          >
            <div className="prose prose-sm prose-zinc dark:prose-invert max-w-none animate-in fade-in duration-300 leading-relaxed [&>p]:my-1 [&>p:first-child]:mt-0 [&>p:last-child]:mb-0">
              <Streamdown>{content}</Streamdown>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
