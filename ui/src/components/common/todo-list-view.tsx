import { CheckCircle2, Circle, ListTodo, Loader2 } from "lucide-react";

interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export function TodoListView({ data }: { data: TodoItem[] }) {
  const todos = data;

  if (!todos || !Array.isArray(todos)) {
    return <div className="text-gray-500">Invalid todo list data.</div>;
  }

  return (
    <div className="w-full my-4 border rounded-lg overflow-hidden bg-white shadow-sm">
      <div className="bg-gray-50 px-4 py-3 border-b flex items-center gap-2">
        <ListTodo className="w-4 h-4 text-gray-600" />
        <h3 className="font-semibold text-sm text-gray-700">Execution Plan</h3>
      </div>
      <div className="divide-y">
        {todos.map((todo, idx) => {
          let icon = <Circle className="w-4 h-4 text-gray-300" />;
          let textClass = "text-gray-500";
          let bgClass = "bg-white";

          if (todo.status === "in_progress") {
            icon = <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
            textClass = "text-gray-800 font-medium";
            bgClass = "bg-blue-50/30";
          } else if (todo.status === "completed") {
            icon = <CheckCircle2 className="w-4 h-4 text-green-500" />;
            textClass = "text-gray-600 line-through decoration-gray-300";
          }

          return (
            <div
              key={idx}
              className={`flex items-start gap-3 p-3 text-sm ${bgClass} transition-colors`}
            >
              <div className="mt-0.5">{icon}</div>
              <span className={textClass}>{todo.content}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
