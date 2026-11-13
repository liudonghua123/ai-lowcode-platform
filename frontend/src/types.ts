export type Locale = 'en' | 'zh'
export type ThemeMode = 'system' | 'light' | 'dark'

export interface Permission { id: number; code: string; name: string; resource: string; action: string }
export interface Role {
  id: number; code: string; name: string; description?: string
  permission_ids: number[]; builtin: boolean; mfa_required: boolean
}
export interface User {
  id: number; username: string; email?: string; display_name?: string; avatar?: string
  status: string; dept?: string; tags?: string[]; role_ids: number[]; roles?: string[]
  permissions: string[]; role_codes: string[]; is_admin: boolean
  is_auditor?: boolean; data_scope?: 'all' | 'audit' | 'self'
  data_scopes?: Record<string, unknown>
  otp_enabled?: boolean; passkey_enabled?: boolean; passkey_count?: number
  provider?: string; last_login_at?: string; created_at?: string
}
export interface FormCondition { field: string; operator: string; value: unknown }
export interface FormRule { logic: 'and' | 'or'; conditions: FormCondition[] }
export interface FormDetailColumn {
  key: string; label: string; type: string; formula?: string; options?: string[]
}
export interface FormDetailSummary { key: string; label: string; column: string; op: string }
export interface FormField {
  id: string; key: string; type: string; label: string; required?: boolean
  placeholder?: string; options?: string[]; width?: number; defaultValue?: unknown
  validation?: Record<string, unknown>; description?: string
  formula?: string; visible_when?: FormRule; required_when?: FormRule
  permission?: 'editable' | 'readonly' | 'hidden'
  columns?: FormDetailColumn[]; summary?: FormDetailSummary[]
  serial?: { prefix?: string; date?: boolean; digits?: number }
  show_upper?: boolean; region_level?: number; mobile_hidden?: boolean
  permission_node?: string; group?: string; caps?: string[]
}
export interface FormFieldItem {
  type: string; group: string; label: string; width: number; caps: string[]
}
export interface FormFieldGroup { code: string; label: string; fields: string[] }
export interface FormCatalog {
  groups: FormFieldGroup[]; fields: FormFieldItem[]; field_types: string[]
  validators: { code: string; label: string }[]
  operators: { code: string; label: string }[]
  functions: { code: string; args: string; label: string }[]
  permission_modes: { code: string; label: string }[]
  layout_types: string[]; computed_types: string[]
  field_count: number; region_levels: number
}
export interface FormDef {
  id: number; code: string; name: string; description?: string; status: string
  schema: FormField[]; layout: Record<string, unknown>; version: number
  print_template?: Record<string, unknown>; settings?: Record<string, unknown>
  field_count?: number
  created_by?: string; created_at?: string; updated_at?: string
}
export interface FormSubmission {
  id: number; form_id: number; data: Record<string, unknown>
  status: string; submitted_by?: string; created_at?: string
  form_version?: number; serial_no?: string | null; flow_instance_id?: number | null
  computed?: Record<string, unknown>; updated_at?: string
}
export interface FormVersion {
  id: number; form_id: number; version: number; schema: FormField[]
  layout: Record<string, unknown>; print_template?: Record<string, unknown>
  settings?: Record<string, unknown>; note?: string
  created_by?: string; created_at?: string
}
export interface FormEvalResult {
  ok: boolean; data: Record<string, unknown>; computed: Record<string, unknown>
  summaries: Record<string, number>; visible: string[]; hidden: string[]
  permissions: Record<string, string>
  errors: { key: string; rule: string; message: string }[]
}
export interface PrintView {
  form: { code: string; name: string; version: number }
  serial_no?: string; submitted_by?: string; created_at?: string
  fields: { key: string; label: string; value: unknown; type: string; upper?: string; info?: unknown }[]
  summaries: Record<string, number>; computed: Record<string, unknown>
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
  graph: WfGraph; version: number; form_code?: string | null
  node_count?: number; edge_count?: number
  created_by?: string; created_at?: string; updated_at?: string
}
export interface FlowTask {
  id: number; instance_id: number; node_id: string; node_name?: string
  node_type?: string; assignee: string; seq: number; status: string
  decision?: string | null; comment?: string | null; signature?: string | null
  due_at?: string | null; acted_at?: string | null; created_at?: string
  delegated_from?: string | null; round: number
  instance_status?: string; form_code?: string | null; initiator?: string
}
export interface WorkflowInstance {
  id: number; workflow_id: number; status: string
  context: Record<string, unknown>; logs: Record<string, unknown>[]
  started_by?: string; started_at?: string; finished_at?: string
  form_code?: string | null; form_data?: Record<string, unknown>
  variables?: Record<string, unknown>; current_nodes?: string[]
  workflow_version?: number; tasks?: FlowTask[]; pending?: FlowTask[]
  task_count?: number; submission_id?: number
}
export interface FlowMeta {
  approver_rules: { code: string; label: string }[]
  sign_modes: { code: string; label: string }[]
  empty_policies: { code: string; label: string }[]
  timeout_actions: { code: string; label: string }[]
  actions: string[]; node_config: Record<string, string[]>
  operators: string[]
}
export interface FlowDelegation {
  id: number; principal: string; agent: string; scope?: string
  starts_at?: string; ends_at?: string; enabled: number; created_by?: string
}
export interface WorkflowVersion {
  id: number; workflow_id: number; version: number
  graph: WfGraph; form_code?: string; note?: string; created_by?: string; created_at?: string
}
export interface KbCollection {
  id: number; code: string; name: string; description?: string
  embedding_model?: string; chunk_size?: number; document_count?: number
}
export interface KbDocument {
  id: number; collection_id: number; title: string; content: string
  source?: string; status: string; chunks?: string[]; chunk_count?: number
  content_preview?: string; created_at?: string
  file_name?: string | null; file_type?: string | null; file_label?: string
  file_size?: number; parse_status?: string; parse_error?: string | null
}
export interface UploadFormat {
  ext: string; label: string; kind: string; mime: string
}
export interface UploadFormats {
  formats: UploadFormat[]; groups: { kind: string; label: string; items: UploadFormat[] }[]
  total: number; max_file_bytes: number; max_text_chars: number
}
export interface UploadedDoc {
  id?: number; ok: boolean; file_name: string; title?: string
  file_type?: string; file_label?: string; file_size?: number
  parse_status?: string; parse_error?: string | null
  chars?: number; chunks?: number; error?: string
}
export interface RagHit {
  doc_id: number; collection_id: number; collection: string
  title: string; snippet: string; score: number
}
export interface AgentDef {
  id: number; code: string; name: string; description?: string
  mode: 'query' | 'act' | 'hybrid'; model?: string; system_prompt?: string
  temperature: number; kb_ids: number[]; skill_ids: number[]
  server_ids: number[]; workflow_ids: number[]
  status: string; created_by?: string; created_at?: string
}
export interface BindableItem {
  id: number; code: string; name: string
  transport?: string; enabled?: boolean; health?: string; status?: string
  tool_count?: number; document_count?: number; server_id?: number | null
  model?: string; category?: string; is_default?: boolean
}
export interface AgentBindings {
  servers: BindableItem[]; skills: BindableItem[]; collections: BindableItem[]
  workflows: BindableItem[]; models: BindableItem[]; modes: string[]
  catalog_count: number; counts: Record<string, number>
}
export interface ChatStep { tool: string; arguments: Record<string, unknown>; result: Record<string, unknown> }
export interface ChatResponse {
  answer: string; steps: ChatStep[]; sources: { doc_id: number; title: string; score: number }[]
  model: string; provider: string; orchestration: string; conversation_id: number; agent: string
  action_request?: ActionRequest | null
}
export interface Conversation {
  id: number; agent_id: number; title: string | null
  messages: { role: 'user' | 'assistant'; content: string }[]
  user_id?: string | null; created_at?: string
}
export interface McpSkill {
  id: number; code: string; name: string; type: string; endpoint?: string
  command?: string; enabled: boolean; auth_config: Record<string, unknown>
  tools: { name: string; description?: string; inputSchema?: unknown }[]
  health: string; last_sync_at?: string; created_at?: string
  status: 'installed' | 'disabled' | 'uninstalled' | 'error'
  version?: string; source?: string; description?: string
  manifest?: Record<string, unknown>; installed_at?: string
  file_count?: number; server_id?: number | null; hub_id?: number | null
  server?: { id: number; code: string; name: string; transport: string; enabled: boolean } | null
  hub?: { id: number; code: string; name: string; kind: string } | null
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
export interface McpServer {
  id: number; code: string; name: string; description?: string
  transport: string; endpoint?: string | null; command?: string | null
  auth_config: Record<string, unknown>
  tools: { name: string; description?: string; inputSchema?: unknown }[]
  tool_count: number; enabled: boolean; health: string
  last_sync_at?: string | null; status: string; source?: string
  created_by?: string; created_at?: string; updated_at?: string
  skills?: { id: number; code: string; name: string; status: string }[]
}
export interface McpServerStats {
  total: number; enabled: number; declared_tools: number
  by_status: Record<string, number>; by_transport: Record<string, number>
}
export type ModelCategory = 'llm' | 'asr' | 'tts' | 'embedding' | 'rerank' | 'vision'
export interface ModelCategoryMeta {
  code: string; label: string; label_zh: string; icon: string
  description: string; default_model: string; api_path: string; count: number
}
export interface ModelVendor {
  code: string; name: string; base_url: string; models: Record<string, string>
}
export interface AiProvider {
  id: number; code: string; name: string; category: ModelCategory
  vendor: string; base_url: string; model: string
  enabled: boolean; is_default: boolean; config: Record<string, unknown>
  description?: string; has_api_key: boolean; api_key_masked: string
  category_label: string; created_at?: string; updated_at?: string
}
export interface AiProviderMeta {
  categories: ModelCategoryMeta[]; vendors: ModelVendor[]
  defaults: Record<string, { code: string; name: string; model: string; enabled: boolean } | null>
  total: number
  effective_llm: Record<string, unknown> & { has_api_key: boolean }
}
export interface AiSettingsEnv {
  base_url: string; model: string; has_api_key: boolean
  api_key_masked: string; configured: boolean
}
export interface AiSettingsItem {
  category: ModelCategory; label: string; label_zh: string; default_model: string
  provider_id: number | null; provider_code: string | null; provider_name: string | null
  vendor: string; enabled: boolean; base_url: string; model: string
  has_api_key: boolean; api_key_masked: string; env_managed: boolean
  source: 'env' | 'manual' | 'none'; ready: boolean; env: AiSettingsEnv
}
export interface AiSettingsView {
  categories: AiSettingsItem[]
  runtime: {
    provider: string; model: string; base_url: string
    config_source: string; temperature: number; has_api_key: boolean
  }
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
/* ---- Workflow portal / dynamic start form / agent action requests ---- */
export interface StartSchema {
  workflow: { id: number; code: string; name: string; status: string; version: number; node_count: number }
  form: { id: number; code: string; name: string; version: number; status: string; field_count: number } | null
  fields: FormField[]
  permissions: Record<string, string>
  columns: number
  platform: string
  start_path: string
  requires_auth: boolean
  hint?: string
}
export interface WorkflowCatalogItem {
  id: number; code: string; name: string; description?: string; status: string
  version: number; form_code: string | null; form_name: string | null
  form_status: string | null; field_count: number; node_count: number
  startable: boolean; requires_auth: boolean; start_path: string
}
export interface MyInstance extends WorkflowInstance {
  workflow_code?: string; workflow_name?: string
  task_count?: number; pending_count?: number
}
export interface PortalStats {
  by_status: Record<string, number>; total: number; running: number
  pending_approvals: number; startable_workflows: number
}
export interface ShareInfo {
  workflow_id: number
  code: string; name: string; description?: string
  form_code: string | null; form_name: string | null
  requires_auth: boolean; start_path: string; login_path: string
  share_url: string; note: string
}
export interface ActionRequest {
  id: string; kind: 'start_workflow' | 'submit_form'; code: string
  workflow_id?: number; title: string; description: string
  schema: FormField[]; form_id: number | null; form_code: string | null
  submit_label: string; endpoint: string
}
export interface AgentActionResult {
  ok: boolean; kind: string; code: string; answer: string
  instance_id?: number; submission_id?: number; status?: string
  pending?: FlowTask[]; conversation_id?: number; agent?: string
}

export interface DelegationRow {
  principal: string; agent: string; starts_at?: string; ends_at?: string
}

export interface MeOverview {
  profile: User
  tasks: { pending: number; done: number }
  instances: { running: number; total: number }
  submissions: number
  notifications_unread: number
  groups: { code: string; name: string }[]
  delegations: { outgoing: DelegationRow[]; incoming: DelegationRow[] }
  data_scope: string
}

export interface Notification {
  id: number; recipient: string; event: string; title: string; body?: string
  ref_type?: string; ref_id?: string; read_at: string | null; created_at: string
}

export type NotificationPrefs = Record<string, string[]>

export interface NotificationChannelMeta {
  code: string; en: string; zh: string; editable: boolean
  ready?: boolean; config?: Record<string, unknown>
}

export interface UserGroup {
  id: number; code: string; name: string; description?: string
  members: string[]; tags: string[]; enabled: boolean; member_count: number
}

export interface Bootstrap {
  app: { name: string; version: string; api_prefix: string; license: string }
  i18n: { locales: string[]; default: string }
  themes: string[]; defaults: { locale: string; theme: string }
  form: {
    field_types: string[]; statuses: string[]
    field_groups?: { code: string; label: string }[]
    validators?: string[]; functions?: string[]; permission_modes?: string[]
  }
  workflow: {
    node_types: { type: string; name: string; category: string; color: string; config: string[] }[]
    operators: string[]; statuses: string[]
    approver_rules?: string[]; sign_modes?: string[]; actions?: string[]
  }
  rbac: { permissions: Permission[]; roles: Pick<Role, 'id' | 'code' | 'name'>[] }
  auth: { provider_meta: Record<string, unknown>; providers: AuthProvider[]; mfa_methods: string[]; mfa_policy: MfaPolicy }
  agents: { modes: string[]; runtime: Record<string, unknown> }
  mcp: { types: string[]; endpoint: string; mode: string; tool_count: number
    builtin_tool_count?: number; server_count?: number }
  skills?: { catalog_count: number; installed: number; types: string[]; statuses: string[] }
  ai?: { categories: string[]; providers: number; defaults: Record<string, unknown> }
  user: User
}


// ---- v5: declarative registry, skill hubs, visual editing, capabilities ----
export interface ConfigField {
  key: string; label: string; type: string
  options?: (string | number)[]; default?: unknown
  placeholder?: string; help?: string
}
export interface RegistryComponent {
  type: string; group: string; label: string; width: number
  caps: string[]; config_schema: ConfigField[]
}
export interface RegistryNode {
  type: string; name: string; category: string; color: string
  icon: string; runtime: string; config: string[]; config_schema: ConfigField[]
}
export interface RegistryPayload {
  components: RegistryComponent[]; nodes: RegistryNode[]
  component_groups: { code: string; label: string }[]
  component_count: number; node_count: number
  node_categories: string[]; human_nodes: string[]
  custom: { components: Record<string, unknown>[]; nodes: Record<string, unknown>[] }
  config_field_types: string[]
}
export interface SkillHub {
  id: number; code: string; name: string; description: string
  url: string | null; kind: 'builtin' | 'remote'; enabled: boolean
  sync_interval_min: number; last_sync_at?: string | null
  last_error?: string | null; skill_count: number
  installed_count: number; created_by?: string
  created_at: string; updated_at: string
}
export interface HubSkill {
  code: string; name: string; type: string; version: string
  description: string; endpoint?: string; command?: string
  capabilities: string[]; category: string; author: string
  downloads: number; tools: { name: string; description?: string }[]
  tool_count: number; files: string[]; hub_id: number
  hub_code: string; hub_name: string; installed: boolean
}
export interface HubSearchResult {
  skills: HubSkill[]; total: number; hubs: string[]
  errors: string[]; categories: string[]
}
export interface SkillPreview {
  skill: McpSkill; manifest: Record<string, unknown>
  capabilities: string[]; skill_md_html: string; readme_html: string
  tools: { name: string; description?: string }[]
  files: { path: string; size: number; language: string }[]
  has_documentation: boolean
}
export interface ToolSpec {
  name: string; description: string
  inputSchema: { type: string; properties: Record<string, unknown>; required: string[] }
  permission?: string | null; available?: boolean
}
export interface CapabilityDomain {
  tools: ToolSpec[]; permissions: string[]; total: number; available: number
}
export interface CapabilityMatrix {
  domains: Record<string, CapabilityDomain>
  total_tools: number; available_tools: number; permission_driven: boolean
}
