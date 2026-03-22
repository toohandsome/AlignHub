/**
 * 前端统一 API 基地址。
 * 默认指向本地 FastAPI 服务，也支持通过环境变量覆盖。
 */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000/api/v1";

export type Provider = {
  id: string;
  provider_type: string;
  name: string;
  base_url?: string | null;
  organization?: string | null;
  extra_config_json?: Record<string, unknown>;
  api_key_masked?: string | null;
};

export type ModelConfig = {
  id: string;
  provider_id: string;
  model_name: string;
  temperature?: number;
  max_tokens?: number;
  top_p?: number | null;
  stream_enabled?: boolean;
  formatter_type?: string;
  extra_config_json?: Record<string, unknown>;
};

export type ToolDef = {
  id: string;
  name: string;
  category: string;
  description: string;
};

export type AgentConfig = {
  id: string;
  name: string;
  role: string;
  persona?: string | null;
  system_prompt: string;
  model_id: string;
  memory_strategy: string;
  max_steps: number;
  is_moderator?: boolean;
  extra_config_json?: Record<string, unknown>;
  tool_names: string[];
  skill_ids: string[];
  skill_names: string[];
  mcp_ids: string[];
  mcp_names: string[];
  feishu_bot_id?: string | null;
  feishu_bot_name?: string | null;
  feishu_bot_enabled?: boolean;
  feishu_bot_receive_enabled?: boolean;
};

export type SkillConfig = {
  id: string;
  name: string;
  description: string;
  content: string;
  source_type: string;
  package_path?: string | null;
  entry_file?: string | null;
  package_files?: string[];
  enabled: boolean;
  builtin: boolean;
};

export type MCPServerConfig = {
  id: string;
  name: string;
  transport_type: string;
  description: string;
  command?: string | null;
  args_json: string[];
  env_json: Record<string, string>;
  base_url?: string | null;
  jar_path?: string | null;
  enabled: boolean;
};

export type MCPTestResult = {
  success: boolean;
  name?: string;
  transport_type?: string;
  action?: string;
  latency_ms?: number;
  preview?: string;
  startup_preview?: string;
  startup_exit_code?: number | null;
  startup_timed_out?: boolean;
  resolved_command?: string | null;
  jar_exists?: boolean | null;
  java_available?: boolean;
  java_version?: string;
  jar_path?: string | null;
  error?: string;
};

export type ChatSession = {
  id: string;
  name: string;
  topic: string;
  max_rounds: number;
  status: string;
  agent_ids: string[];
  feishu_chat_id?: string | null;
  feishu_topic_root_id?: string | null;
  feishu_enabled?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type FeishuConfig = {
  id?: string | null;
  app_id: string;
  app_secret: string;
  verification_token: string;
  bot_name?: string | null;
  enabled: boolean;
  webhook_path: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type FeishuAgentBotConfig = {
  id?: string | null;
  agent_id: string;
  agent_name?: string | null;
  app_id: string;
  app_secret: string;
  verification_token: string;
  bot_name?: string | null;
  enabled: boolean;
  receive_enabled: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type FeishuChatDiagnoseItem = {
  agent_id: string;
  agent_name: string;
  bot_name?: string | null;
  app_id: string;
  enabled: boolean;
  receive_enabled: boolean;
  in_chat: boolean | null;
  error?: string | null;
};

export type DiscussionRun = {
  id: string;
  session_id: string;
  status: string;
  current_round: number;
  notify_feishu?: boolean;
  started_at?: string | null;
  ended_at?: string | null;
  stop_reason?: string | null;
  latest_report?: ReportSummary | null;
  created_at?: string;
  updated_at?: string;
};

export type DiscussionEvent = {
  id: string;
  run_id: string;
  seq: number;
  round_no: number;
  event_type: string;
  agent_id?: string | null;
  tool_name?: string | null;
  payload_json?: Record<string, unknown>;
  payload?: Record<string, unknown>;
  created_at: string;
};

export type FinalReport = {
  id: string;
  run_id: string;
  title: string;
  summary_markdown: string;
  conclusion_json: Record<string, unknown>;
};

export type ReportSummary = {
  id: string;
  run_id: string;
  title: string;
  created_at: string;
};

export type ToolCallLog = {
  id: string;
  run_id: string;
  round_no: number;
  agent_id?: string | null;
  call_id?: string | null;
  tool_name: string;
  tool_input_json: Record<string, unknown>;
  tool_output_json: Record<string, unknown>;
  status: string;
  started_at: string;
  ended_at?: string | null;
};

export type ConnectionTestResult = {
  success: boolean;
  provider_type?: string;
  model_name?: string;
  latency_ms?: number;
  endpoint?: string;
  preview?: string;
  error?: string;
  message?: string;
};

/**
 * 统一 JSON 请求封装：
 * - 自动补齐 API 前缀
 * - 默认禁用缓存，避免管理台读到旧数据
 * - 在非 2xx 时把后端响应文本透传给页面提示
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

/**
 * 用于 zip / jar 等文件上传场景。
 * 注意不要手工设置 Content-Type，让浏览器自动附带 boundary。
 */
async function uploadRequest<T>(path: string, body: FormData, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    method: init?.method ?? "POST",
    body,
    cache: "no-store"
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  return response.json() as Promise<T>;
}

/**
 * 业务层常用的 HTTP 方法统一收口到 api 对象，页面侧直接调用即可。
 */
export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  upload: <T>(path: string, body: FormData) => uploadRequest<T>(path, body),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" })
};

/**
 * 根据当前 HTTP API 地址推导对应的 WebSocket 地址。
 * Run 详情页会用它订阅实时事件流。
 */
export function wsUrl(runId: string): string {
  const base = API_BASE.replace("/api/v1", "");
  if (base.startsWith("https://")) {
    return `${base.replace("https://", "wss://")}/api/v1/ws/runs/${runId}`;
  }
  return `${base.replace("http://", "ws://")}/api/v1/ws/runs/${runId}`;
}
