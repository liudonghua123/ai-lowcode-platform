export type Locale = 'en' | 'zh'
export type ThemeMode = 'system' | 'light' | 'dark'

export interface Permission { id: number; code: string; name: string; resource: string; action: string }
export interface Role {
  id: number; code: string; name: string; description?: string
  permission_ids: number[]; builtin: boolean; mfa_required: boolean
}
export interface User {
  id: number; username: string; email?: string; display_name?: string; avatar?: string
  status: string; dept?: string; role_ids: number[]; roles?: string[]
  permissions: string[]; role_codes: string[]; is_admin: boolean
  otp_enabled?: boolean; passkey_enabled?: boolean; passkey_count?: number
  provider?: string; last_login_at?: string; created_at?: string
}
export interface FormField {
  id: string; key: string; type: string; label: string; required?: boolean
  placeholder?: string; options?: string[]; width?: number; defaultValue?: unknown
  validation?: Record<string, unknown>; description?: string
}
export interface FormDef {
  id: number; code: string; name: string; description?: string; status: string
  schema: FormField[]; layout: Record<string, unknown>; version: number
  created_by?: string; created_at?: string; updated_at?: string
}
export interface FormSubmission {
  id: number; form_id: number; data: Record<string, unknown>
  status: string; submitted_by?: string; created_at?: string
}
export interface WfNode {
  id: string; type: string; name: string; x: number; y: number
  config: Record<string, unknown>
}
export interface WfEdge {
  id: string; source: string; target: string; label?: string; condition?: string
}
export interface WfGraph { nodes: WfNode[]; edges: WfEdge[] }
export interface WorkflowDef {
  id: number; code: string; name: string; description?: string; status: string
  graph: WfGraph; version: number; created_by?: string; created_at?: string; updated_at?: string
}
export interface WorkflowInstance {
  id: number; workflow_id: number; status: string
  context: Record<string, unknown>; logs: Record<string, unknown>[]
  started_by?: string; started_at?: string; finished_at?: string
}
export interface KbCollection {
  id: number; code: string; name: string; description?: string
  embedding_model?: string; chunk_size?: number; document_count?: number
}
export interface KbDocument {
  id: number; collection_id: number; title: string; content: string
  source?: string; status: string; chunks?: string[]; chunk_count?: number
  content_preview?: string; created_at?: string
}
export interface RagHit {
  doc_id: number; collection_id: number; collection: string
  title: string; snippet: string; score: number
}
export interface AgentDef {
  id: number; code: string; name: string; description?: string
  mode: 'query' | 'act' | 'hybrid'; model?: string; system_prompt?: string
  temperature: number; kb_ids: number[]; skill_ids: number[]; workflow_ids: number[]
  status: string; created_by?: string; created_at?: string
}
export interface ChatStep { tool: string; arguments: Record<string, unknown>; result: Record<string, unknown> }
export interface ChatResponse {
  answer: string; steps: ChatStep[]; sources: { doc_id: number; title: string; score: number }[]
  model: string; provider: string; orchestration: string; conversation_id: number; agent: string
}
export interface ToolSpec {
  name: string; description: string
  inputSchema: { type: string; properties: Record<string, unknown>; required: string[] }
}
export interface McpSkill {
  id: number; code: string; name: string; type: string; endpoint?: string
  command?: string; enabled: boolean; auth_config: Record<string, unknown>
  tools: { name: string; description?: string; inputSchema?: unknown }[]
  health: string; last_sync_at?: string; created_at?: string
  status: 'installed' | 'disabled' | 'uninstalled' | 'error'
  version?: string; source?: string; description?: string
  manifest?: Record<string, unknown>; installed_at?: string
  file_count?: number
}
export interface SkillFile {
  id: number; skill_id: number; path: string; content?: string
  language: string; size: number; updated_at: string
}
export interface CatalogSkill {
  code: string; name: string; type: string; version: string
  description: string; endpoint?: string; command?: string
  capabilities: string[]; tool_count: number; file_count: number
  files: string[]; installed: boolean; status: string
}
export interface McpCall {
  id: number; request_id?: string; method: string; tool?: string
  source: string; transport?: string; actor?: string
  arguments: Record<string, unknown>; status: string
  error?: string; result?: unknown; duration_ms: number
  created_at: string
}
export interface CallStats {
  total: number; success: number; errors: number; success_rate: number
  avg_duration_ms: number; today: number
  by_tool: { name: string; count: number; errors: number; avg_ms: number }[]
  by_source: { source: string; count: number }[]
  timeline: { day: string; count: number; errors: number }[]
  sources: string[]; statuses: string[]; tools: string[]
}
export interface AuthProvider {
  id?: number; code: string; type: string; name: string; enabled: boolean
  config: Record<string, unknown>; sort_order?: number
}
export interface MfaPolicy {
  required: boolean; methods: string[]; enforced_roles: string[]
  enforced_users: string[]; otp: boolean; passkey: boolean
}
export interface AuditLog {
  id: number; actor: string; action: string; resource?: string
  detail: Record<string, unknown>; ip?: string; level: string; created_at: string
}
export interface Bootstrap {
  app: { name: string; version: string; api_prefix: string; license: string }
  i18n: { locales: string[]; default: string }
  themes: string[]; defaults: { locale: string; theme: string }
  form: { field_types: string[]; statuses: string[] }
  workflow: {
    node_types: { type: string; name: string; category: string; color: string; config: string[] }[]
    operators: string[]; statuses: string[]
  }
  rbac: { permissions: Permission[]; roles: Pick<Role, 'id' | 'code' | 'name'>[] }
  auth: { provider_meta: Record<string, unknown>; providers: AuthProvider[]; mfa_methods: string[]; mfa_policy: MfaPolicy }
  agents: { modes: string[]; runtime: Record<string, unknown> }
  mcp: { types: string[]; endpoint: string; mode: string; tool_count: number }
  user: User
}
