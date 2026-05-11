import { type ReactActivityMessageRenderer } from "@copilotkitnext/react";
import { z } from "zod";
import { memo, useDeferredValue, useMemo, useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import remarkGfm from "remark-gfm";
import ReactMarkdown from "react-markdown";
import {
  AlertCircle,
  ArrowUpDown,
  Ban,
  ChevronDown,
  ChevronUp,
  ListTodo,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { DataTable } from "./A2UI/data-table";
import { ErrorBoundary } from "react-error-boundary";
import { PhotoProvider, PhotoView } from "react-photo-view";
import "react-photo-view/dist/react-photo-view.css";

// --- 1. 类型定义 ---

interface TableContent {
  type: "table";
  title?: string;
  columns: string[];
  rows: Record<string, any>[];
}
interface MarkdownContent {
  type: "markdown";
  title?: string;
  content: string;
}

// 联合类型
type A2UIContent = TableContent | MarkdownContent;

function ErrorFallback({
  error,
  resetErrorBoundary,
}: {
  error: Error;
  resetErrorBoundary: () => void;
}) {
  return (
    <div className="p-4 border border-red-200 bg-red-50 rounded-md text-red-600 flex flex-col gap-2 my-2">
      <div className="flex items-center gap-2 font-semibold">
        <Ban className="w-4 h-4" />
        <span>Component Render Error</span>
      </div>
      <p className="text-sm opacity-80 break-all">{error.message}</p>
      <Button
        variant="outline"
        size="sm"
        onClick={resetErrorBoundary}
        className="w-fit mt-2 bg-white"
      >
        Retry
      </Button>
    </div>
  );
}

function TableView({ data }: { data: TableContent }) {
  const { columns: rawColumns, rows, title } = data;

  const safeColumns = useMemo<ColumnDef<any>[]>(() => {
    try {
      if (!rawColumns || !Array.isArray(rawColumns)) return [];

      return rawColumns.map((colName) => ({
        accessorKey: colName,
        header: ({ column }) => (
          <Button
            variant="ghost"
            onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            className="-ml-3 h-8"
          >
            {colName}
            <ArrowUpDown className="ml-2 h-4 w-4" />
          </Button>
        ),
        cell: ({ row }) => {
          try {
            const value = row.getValue(colName);
            return <div className="font-medium">{String(value ?? "-")}</div>;
          } catch (e) {
            return <span className="text-red-400 text-xs">Error</span>;
          }
        },
      }));
    } catch (e) {
      console.error("Error generating columns:", e);
      return [];
    }
  }, [rawColumns]);

  if (!rawColumns || rawColumns.length === 0) {
    return (
      <div className="p-4 text-gray-500 italic">No data columns available.</div>
    );
  }

  return (
    <div className="w-full my-4 space-y-2">
      {title && (
        <h3 className="text-lg font-semibold tracking-tight px-1">{title}</h3>
      )}
      {safeColumns.length > 0 ? (
        <DataTable columns={safeColumns} data={rows || []} />
      ) : (
        <div className="text-sm text-red-500">
          Could not render table columns.
        </div>
      )}
    </div>
  );
}
const PreviewImage = (props: any) => {
  const { src, alt, title, ...rest } = props;
  if (!src) return null;

  return (
    // 使用 PhotoView 包裹 img
    // src: 大图地址 (这里和缩略图一样)
    <PhotoView src={src}>
      <img
        src={src}
        alt={alt || title || "markdown image"}
        title={title}
        {...rest}
        // cursor-zoom-in 提示用户可点击
        className="rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm my-4 max-w-full h-auto object-cover cursor-zoom-in hover:opacity-95 transition-opacity"
        loading="lazy"
      />
    </PhotoView>
  );
};

const MarkdownView = memo(
  ({ data }: { data: MarkdownContent }) => {
    const { title, content } = data;
    const [isExpanded, setIsExpanded] = useState(false);

    const deferredContent = useDeferredValue(content);
    if (!content) return null;

    const COLLAPSE_THRESHOLD = 300;
    const isLongContent = content.length > COLLAPSE_THRESHOLD;
    const shouldCollapse = isLongContent && !isExpanded;

    if (!content) return null;

    return (
      <div className="w-full my-4 space-y-2">
        {title && (
          <div className="flex items-center gap-2 mb-2">
            <ListTodo className="w-4 h-4 text-primary" />
            <h3 className="text-lg font-semibold tracking-tight">{title}</h3>
          </div>
        )}

        <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50 overflow-hidden relative">
          <div
            className={`
            p-4 transition-all duration-300 ease-in-out
            ${shouldCollapse ? "max-h-[160px] overflow-hidden" : "max-h-none"}
          `}
          >
            <PhotoProvider maskOpacity={0.8}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                className="prose prose-sm dark:prose-invert max-w-none break-words"
                urlTransform={(value) => value}
                components={{
                  a: ({ node, ...props }) => (
                    <a
                      {...props}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline font-medium"
                    />
                  ),
                  strong: ({ node, ...props }) => (
                    <strong
                      {...props}
                      className="font-bold text-slate-800 dark:text-slate-200"
                    />
                  ),
                  // 将图片处理逻辑交给 PreviewImage 组件（或者直接渲染）
                  img: PreviewImage,
                }}
              >
                {/* ✅ 直接使用 deferredContent */}
                {deferredContent}
              </ReactMarkdown>
            </PhotoProvider>
          </div>

          {shouldCollapse && (
            <div className="absolute bottom-0 left-0 w-full h-16 bg-gradient-to-t from-slate-50 to-transparent dark:from-slate-900 pointer-events-none" />
          )}

          {/* 展开/收起按钮代码保持不变 */}
          {isLongContent && (
            <div
              className={`flex justify-center p-2 ${isExpanded ? "border-t border-slate-200 dark:border-slate-800" : "absolute bottom-0 w-full z-10"}`}
            >
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsExpanded(!isExpanded)}
                // ... 样式代码
              >
                {isExpanded ? (
                  <>
                    {" "}
                    <ChevronUp className="w-3 h-3 mr-1" /> Show Less{" "}
                  </>
                ) : (
                  <>
                    {" "}
                    <ChevronDown className="w-3 h-3 mr-1" /> Show More{" "}
                  </>
                )}
              </Button>
            </div>
          )}
        </div>
      </div>
    );
    // 这里的比较函数是性能优化的关键，只有 raw content 变了才重绘
  },
  (prevProps, nextProps) => {
    return (
      prevProps.data.content === nextProps.data.content &&
      prevProps.data.title === nextProps.data.title
    );
  },
);

// --- 5. 主渲染器工厂函数 ---

export type MessageRendererOptions = {
  theme?: any;
};

export function createA2UIMessageRenderer(
  options: MessageRendererOptions,
): ReactActivityMessageRenderer<any> {
  return {
    activityType: "a2ui-surface",
    content: z.any() as any,

    render: ({ content }) => {
      if (!content || typeof content !== "object") {
        return (
          <div className="p-4 border border-red-200 rounded text-red-500 flex items-center gap-2">
            <AlertCircle className="w-4 h-4" />
            <span>Data format error: Content is missing or invalid.</span>
          </div>
        );
      }

      // 2. 根据 type 分发渲染逻辑
      // 使用 ErrorBoundary 包裹整个动态内容，确保任意组件崩溃不影响聊天主界面
      return (
        <ErrorBoundary FallbackComponent={ErrorFallback}>
          {(() => {
            const typedContent = content as A2UIContent;

            switch (typedContent.type) {
              case "table":
                return <TableView data={typedContent} />;
              case "markdown":
                return <MarkdownView data={typedContent} />;

              default:
                if ("rows" in content && "columns" in content) {
                  return <TableView data={{ ...content, type: "table" }} />;
                }

                return (
                  <div className="p-4 border border-yellow-200 bg-yellow-50 rounded text-yellow-700 text-sm">
                    <p className="font-semibold">
                      Unknown content type: {content.type}
                    </p>
                    <pre className="mt-2 text-xs opacity-80 overflow-auto max-h-40">
                      {JSON.stringify(content, null, 2)}
                    </pre>
                  </div>
                );
            }
          })()}
        </ErrorBoundary>
      );
    },
  };
}
