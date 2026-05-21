"use client";
import { useState, useEffect } from "react";
import {
  Loader2,
  PlusCircle,
  Save,
  AlertCircle,
  CheckCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import type {
  LLMModelConfig,
  LLMModelConfigCreate,
  LLMModelConfigUpdate,
  TestConnectionRequest,
  TestConnectionResponse,
} from "@/types/entity";

interface ModelConfigDialogProps {
  model?: LLMModelConfig;
  isPending: boolean;
  onSave: (data: LLMModelConfigCreate | LLMModelConfigUpdate) => void;
  onTestConnection?: (
    data: TestConnectionRequest,
  ) => Promise<TestConnectionResponse>;
  trigger?: React.ReactNode;
}

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "azure", label: "Azure OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "ollama", label: "Ollama" },
  { value: "gemini", label: "Google Gemini" },
];

export function ModelConfigDialog({
  model,
  isPending,
  onSave,
  onTestConnection,
  trigger,
}: ModelConfigDialogProps) {
  const [open, setOpen] = useState(false);

  // 1. 新增：专门用于存储 Parameters 文本域的字符串状态
  const [jsonParams, setJsonParams] = useState("{}");
  // 2. 新增：用于显示 JSON 解析错误的提示
  const [jsonError, setJsonError] = useState<string | null>(null);

  const [data, setData] = useState<LLMModelConfigCreate>({
    name: "",
    provider: "openai",
    model: "",
    api_base: "",
    api_version: "",
    api_key: "",
    is_active: true,
    parameters: {},
  });

  const [testResult, setTestResult] = useState<{
    status: "idle" | "testing" | "success" | "error";
    message: string;
    latency?: number;
  }>({ status: "idle", message: "" });

  useEffect(() => {
    if (model) {
      setData({
        name: model.name,
        provider: model.provider,
        model: model.model,
        api_base: model.api_base || "",
        api_version: model.api_version || "",
        api_key: "",
        is_active: model.is_active,
        parameters: model.parameters || {},
      });
      // 初始化 JSON 字符串
      setJsonParams(JSON.stringify(model.parameters || {}, null, 2));
    } else {
      setData({
        name: "",
        provider: "openai",
        model: "",
        api_base: "",
        api_version: "",
        api_key: "",
        is_active: true,
        parameters: {},
      });
      // 初始化为空 JSON
      setJsonParams("{}");
    }
    setJsonError(null);
    setTestResult({ status: "idle", message: "" });
  }, [model, open]);

  // 辅助函数：尝试解析 JSON
  const parseParams = (): Record<string, any> | null => {
    try {
      const parsed = JSON.parse(jsonParams);
      setJsonError(null);
      return parsed;
    } catch (e) {
      setJsonError("Invalid JSON format");
      return null;
    }
  };

  const handleSubmit = () => {
    // 提交前解析 JSON
    const parsedParams = parseParams();
    if (parsedParams === null) return; // 如果解析失败，阻止提交

    // 将解析后的 parameters 合并到 data 中
    onSave({ ...data, parameters: parsedParams });
    setOpen(false);
  };

  const handleTest = async () => {
    if (!onTestConnection) return;

    // 测试连接前也需要解析 JSON，确保测试使用的是最新参数
    const parsedParams = parseParams();
    if (parsedParams === null) return;

    setTestResult({ status: "testing", message: "Testing connection..." });
    try {
      const result = await onTestConnection({
        ...data,
        parameters: parsedParams,
      });
      setTestResult({
        status: result.success ? "success" : "error",
        message: result.message,
        latency: result.latency_ms,
      });
    } catch (error: unknown) {
      const errorMessage =
        error instanceof Error ? error.message : "Connection test failed";
      setTestResult({
        status: "error",
        message: errorMessage,
      });
    }
  };

  const isValid = data.name && data.provider && data.model;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline">
            <PlusCircle className="mr-2 h-4 w-4" /> Add Model
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {model ? "Edit Model Configuration" : "Add New Model Configuration"}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Configuration Name *</Label>
              <Input
                value={data.name}
                onChange={(e) => setData({ ...data, name: e.target.value })}
                placeholder="e.g., My GPT-4"
              />
            </div>
            <div className="space-y-2">
              <Label>Provider *</Label>
              <Select
                value={data.provider}
                onValueChange={(value) => setData({ ...data, provider: value })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PROVIDERS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label>Model Name *</Label>
            <Input
              value={data.model}
              onChange={(e) => setData({ ...data, model: e.target.value })}
              placeholder="e.g., gpt-4, claude-3-opus, llama3"
            />
          </div>

          <div className="space-y-2">
            <Label>
              {model ? "API Key (leave empty to keep existing)" : "API Key"}
            </Label>
            <Input
              type="password"
              value={data.api_key || ""}
              onChange={(e) => setData({ ...data, api_key: e.target.value })}
              placeholder={model ? "••••••••" : "Enter API key"}
            />
          </div>

          <div className="space-y-2">
            <Label>API Base URL (Optional)</Label>
            <Input
              value={data.api_base || ""}
              onChange={(e) => setData({ ...data, api_base: e.target.value })}
              placeholder="e.g., http://localhost:11434 for Ollama"
            />
          </div>

          {data.provider === "azure" && (
            <div className="space-y-2">
              <Label>API Version (Azure)</Label>
              <Input
                value={data.api_version || ""}
                onChange={(e) =>
                  setData({ ...data, api_version: e.target.value })
                }
                placeholder="e.g., 2024-02-15-preview"
              />
            </div>
          )}

          <div className="space-y-2">
            <Label>Parameters (JSON format)</Label>
            {/* 修改处：使用 value 和 onChange 绑定 jsonParams 状态 */}
            <textarea
              className={`w-full min-h-[100px] px-3 py-2 text-sm border bg-background rounded-md resize-vertical focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent ${
                jsonError ? "border-red-500 focus:ring-red-500" : "border-input"
              }`}
              value={jsonParams}
              onChange={(e) => {
                setJsonParams(e.target.value);
                setJsonError(null); // 用户输入时清除错误提示
              }}
              placeholder='{"temperature": 0.7, "max_tokens": 1000}'
            />
            {jsonError ? (
              <p className="text-xs text-red-500">{jsonError}</p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Enter model parameters in JSON format. Example:{" "}
                {'{"temperature": 0.7, "max_tokens": 1000}'}
              </p>
            )}
          </div>

          {testResult.status !== "idle" && (
            <Alert
              variant={
                testResult.status === "success"
                  ? "default"
                  : testResult.status === "error"
                    ? "destructive"
                    : "default"
              }
            >
              {testResult.status === "success" && (
                <CheckCircle className="h-4 w-4" />
              )}
              {testResult.status === "error" && (
                <AlertCircle className="h-4 w-4" />
              )}
              {testResult.status === "testing" && (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              <AlertDescription>
                {testResult.message}
                {testResult.latency && ` (${testResult.latency}ms)`}
              </AlertDescription>
            </Alert>
          )}
        </div>
        <DialogFooter className="gap-2">
          {onTestConnection && (
            <Button
              onClick={handleTest}
              variant="outline"
              disabled={!isValid || testResult.status === "testing"}
            >
              {testResult.status === "testing" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <AlertCircle className="mr-2 h-4 w-4" />
              )}
              Test Connection
            </Button>
          )}
          {/* 如果 JSON 格式错误，禁用保存按钮 */}
          <Button
            onClick={handleSubmit}
            disabled={isPending || !isValid || !!jsonError}
          >
            {isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : model ? (
              <Save className="mr-2 h-4 w-4" />
            ) : (
              <PlusCircle className="mr-2 h-4 w-4" />
            )}
            {isPending ? "Saving..." : model ? "Update" : "Add"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
