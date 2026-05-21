type PluginConfigType = "string" | "float" | "integer" | "bool";
export interface PluginConfigItem {
  name: string;
  type: PluginConfigType;
  required: boolean;
  secret: boolean;
  description?: string | null;
  default?: string | number | boolean | null;
  value?: string | number | boolean | null;
}

export type AssistantPlugin = {
  registry_id: string;
  display_name: string;
  status?: string;
  enabled?: boolean;
  config?: PluginConfigItem[];
  tools?: PluginTool[];
};

export type Assistant = {
  id: string;
  name: string;
  description?: string;
  instructions?: string;
  enabled?: boolean;
  status?: string;
  plugins?: AssistantPlugin[];
  updatedAt?: string;
  model_config_id?: string | null;
};

export type AppSettings = {
  llm?: {
    model?: string;
    base_url?: string;
    provider?: string;
    api_key?: string;
  };
  workflows?: { id: string; name: string }[];
  current_workflow?: string;
};

export type PluginManifest = {
  registry_id: string;
  display_name: string;
  version?: string;
  description?: string;
  spec_version?: string;
  execution?: { mode?: string };
  dependencies?: string[];
};
export type PluginTool = {
  name: string;
  description?: string;
  enabled?: boolean;
};

import type { Edge, Node } from "@xyflow/react";
interface BaseWorkflowNode {
  id: string;
  position: { x: number; y: number };
}
export interface AssistantWorkflowNode extends BaseWorkflowNode {
  type: "assistant";
  data: {
    id: string;
    assistantId: string;
    isStart?: boolean;
    name: string;
    description?: string;
  };
}
export type WorkflowNode = Node<AssistantWorkflowNode["data"]>;
export type WorkflowEdge = Edge<{ mode?: "bidirectional" | "single" }>;
export type Workflow = {
  id: string;
  name: string;
  workspaceId?: string;
  description?: string;
  model_config_id?: string | null;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  created_at?: string;
  updated_at?: string;
};
export type WorkflowSummary = Pick<Workflow, "id" | "name" | "description">;
type ModelCost = { [modelName: string]: number };
export type AnalyticsData = {
  total_budget: number;
  current_cost: number;
  model_cost: ModelCost;
};

export interface OverviewAssistantItem {
  id: string;
  name: string;
  status: string;
  plugin_count: number;
  enabled_plugin_count: number;
}
export interface OverviewPluginItem {
  id: string;
  name: string;
  version: string;
  tool_count: number;
}
export interface OverviewWorkflowItem {
  id: string;
  name: string;
}
export interface OverviewLogEntry {
  [k: string]: any;
  timestamp?: string;
  ts?: string;
  level?: string;
  module?: string;
  message?: string;
  context?: any;
}
export interface OverviewData {
  assistants: {
    total: number;
    active: number;
    inactive: number;
    list: OverviewAssistantItem[];
  };
  plugins: { installed_total: number; list: OverviewPluginItem[] };
  workflows: {
    total: number;
    active_workflow_id: string | null;
    list: OverviewWorkflowItem[];
  };
  logs: { recent: OverviewLogEntry[]; stats: Record<string, any> };
  market: { metadata: any; plugin_updates: number };
  llm: Record<string, any>;
}

export type MarketItem = {
  id: string;
  name: string;
  description?: string;
  version?: string;
  author?: string;
  category: "plugin" | "assistant" | "workflow";
  tags?: string[];
  license?: string;
  readme?: string;
  downloads?: number;
  rating?: number;
  created_at?: string;
  updated_at?: string;
  is_installed?: boolean;
  installed_version?: string;
  update_available?: boolean;
};

export type MarketMetadata = {
  version: string;
  updated_at: string;
  categories: { plugins: number; assistants: number; workflows: number };
};

export type MarketDownloadRequest = {
  item_id: string;
  category: "plugin" | "assistant" | "workflow";
  isUpdate: boolean;
};
export type MarketDownloadResponse = {
  success: boolean;
  message: string;
  installed_path?: string;
};
export interface DisplayItem {
  type?: string;
  title?: string;
  columns?: string[];
  rows?: unknown[];
  content?: string;
  [k: string]: unknown;
}

export type Artifact = {
  version?: string;
  display: DisplayItem[];
  data?: unknown;
  metadata?: unknown;
  [k: string]: unknown;
};

export interface Workspace {
  id: string; // UUID
  name: string;
  slug: string;
  description?: string;
  allow_guest_access: boolean;
  default_model_config_id?: string | null;
  role?: "owner" | "admin" | "member";
}

// types/workspace.ts

export type WorkspaceRole = "owner" | "admin" | "member" | "viewer";

export interface WorkspaceMember {
  user_id: string;
  email: string;
  username: string;
  avatar_url?: string | null;
  role: WorkspaceRole;
  joined_at: string;
}

export interface WorkspaceCreatePayload {
  name: string;
  slug: string;
  description?: string;
}

export interface WorkspaceUpdatePayload {
  name?: string;
  description?: string;
  allow_guest_access?: boolean;
  default_model_config_id?: string | null;
}

export interface WorkspaceInvitePayload {
  email: string;
  role?: WorkspaceRole; // 默认为 "member"
}
export type ChatThread = {
  id: string; // UUID
  title: string;
  created_at: string; // ISO Date string
  updated_at: string; // ISO Date string
};
export type LogItem = {
  timestamp: string;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL" | string;
  message: string;
  module?: string;
  function?: string;
  context?: Record<string, unknown>;
  correlation_id?: string;
};

export type LogStats = {
  total_logs: number;
  by_level: Record<string, number>;
  by_module: Record<string, number>;
  oldest_timestamp: string | null;
  newest_timestamp: string | null;
};

export interface LoginRequest {
  email: string;
  password: string;
}
export interface LoginResponse {
  access_token: string;
  token_type?: string;
  user?: any;
}
export type AuthUser = {
  /** Id */
  id: string;
  /**
   * Email
   * Format: email
   */
  email: string;
  /** Full Name */
  full_name?: string | null;
  /** Role */
  role: string[];
};

export interface SignupRequest {
  username: string;
  email: string;
  password: string;
}
export type SignupResponse = AuthUser;

// LLM Model Configuration Types
export interface LLMModelConfig {
  id: string;
  workspace_id: string;
  name: string;
  provider: string;
  model: string;
  api_base?: string | null;
  api_version?: string | null;
  has_api_key: boolean;
  parameters: Record<string, any>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LLMModelConfigCreate {
  name: string;
  provider: string;
  model: string;
  api_base?: string | null;
  api_version?: string | null;
  api_key?: string | null;
  parameters?: Record<string, any>;
  is_active?: boolean;
}

export interface LLMModelConfigUpdate {
  name?: string;
  provider?: string;
  model?: string;
  api_base?: string | null;
  api_version?: string | null;
  api_key?: string | null;
  parameters?: Record<string, any>;
  is_active?: boolean;
}

export interface TestConnectionRequest {
  name: string;
  provider: string;
  model: string;
  api_base?: string | null;
  api_version?: string | null;
  api_key?: string | null;
  parameters?: Record<string, any>;
  is_active?: boolean;
}

export interface TestConnectionResponse {
  success: boolean;
  latency_ms: number;
  message: string;
}
