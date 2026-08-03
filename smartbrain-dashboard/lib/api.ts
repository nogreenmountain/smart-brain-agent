// 智慧大脑 - 后端 API 调用客户端
// 全部用 cookie 鉴权（后端发 session_id httpOnly cookie）
// 这个文件只能在 client component 里用,server component 直接 fetch 会失败

function getApiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return 'http://localhost:8000';
}

export interface OrgMembership {
  org_id: string;
  org_name: string;
  role: 'owner' | 'admin' | 'developer' | 'business_user';
}

export interface Me {
  user_id: string;
  email: string;
  full_name: string | null;
  memberships: OrgMembership[];
}

export interface Project {
  id: string;
  org_id: string;
  name: string;
  environment: string;
  department_id?: DepartmentId;
  role?: ProjectRole;
  created_at?: string | null;
  completed_at?: string | null;
}

export type ProjectRole = 'owner' | 'admin' | 'developer' | 'business_user';

export interface ProjectMember {
  user_id: string;
  email: string;
  role: ProjectRole;
}

export interface AddProjectMemberInput {
  user_id?: string;
  identifier?: string;
  role: ProjectRole;
}

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  document_name: string;
  content: string;
  source_page: number | null;
  source_line: number | null;
  score: number;
  heading_path?: string | null;
  retrieval_mode?: string | null;
  vector_score?: number | null;
  keyword_score?: number | null;
  vector_rank?: number | null;
  keyword_rank?: number | null;
  rrf_score?: number | null;
  rerank_score?: number | null;
  embedding_model?: string | null;
  embedding_version?: string | null;
}

export interface SearchResult {
  query: string;
  hits: SearchHit[];
}

export interface AnswerResult {
  query: string;
  hits: SearchHit[];
  synthesis: string;
  source: 'llm' | 'stub';
}

export interface UploadResult {
  document_id: string;
  filename: string;
  chunk_count: number;
  status: string;
  error: string | null;
}

export interface MaterialDocumentResult {
  document_id: string;
  filename: string;
  format: string;
  chunk_count: number;
  status: string;
}

export interface MaterialBatchUploadResult {
  raw_document_count: number;
  raw_documents: MaterialDocumentResult[];
  draft: ProjectMemoryDraft;
}

export type MaterialRecommendation = 'keep' | 'review' | 'duplicate' | 'sensitive' | 'low_value';

export interface MaterialIntakePreviewItem {
  id: string;
  filename: string;
  format: string;
  size_bytes: number;
  content_hash: string;
  recommendation: MaterialRecommendation;
  included: boolean;
  reason: string;
  issues: string[];
}

export interface MaterialIntakePreview {
  id: string;
  project_id: string;
  status: 'preview_ready';
  summary: string;
  model: string | null;
  used_fallback: boolean;
  items: MaterialIntakePreviewItem[];
}

export interface MaterialIntakeConfirmResult {
  intake_id: string;
  status: 'pending_review';
  raw_document_count: number;
  curated_document_id: string;
  draft_id: string;
  skill_count: number;
  generation_model: string | null;
  generation_used_fallback: boolean;
}

export type KnowledgeApprovalStatus = 'raw_uploaded' | 'pending_review' | 'approved' | 'rejected';

export interface KnowledgeLedgerUser {
  user_id: string;
  email: string;
  role?: ProjectRole | null;
}

export interface KnowledgeLedgerProject {
  id: string;
  name: string;
  environment: string;
  department_id: DepartmentId;
  created_at?: string | null;
  completed_at?: string | null;
}

export interface KnowledgeLedgerSummary {
  raw_document_count: number;
  approved_count: number;
  pending_count: number;
  rejected_count: number;
  unreviewed_count: number;
  latest_uploaded_at: string | null;
  latest_reviewed_at: string | null;
}

export interface KnowledgeLedgerDocument {
  document_id: string;
  filename: string;
  display_name: string;
  format: string;
  size_bytes: number;
  status: string;
  chunk_count: number;
  error_message: string | null;
  uploaded_by: KnowledgeLedgerUser | null;
  uploaded_at: string;
  approval_status: KnowledgeApprovalStatus;
  reviewed_by: KnowledgeLedgerUser | null;
  reviewed_at: string | null;
  review_comment: string | null;
  draft_id: string | null;
  approved_memory_document_id: string | null;
  intake_id?: string | null;
  original_file_id?: string | null;
}

export interface KnowledgeLedger {
  project: KnowledgeLedgerProject;
  permissions: { can_review: boolean };
  leaders: KnowledgeLedgerUser[];
  uploaders: KnowledgeLedgerUser[];
  summary: KnowledgeLedgerSummary;
  documents: KnowledgeLedgerDocument[];
}

export interface KnowledgeLedgerParams {
  projectId: string;
  uploaderUserId?: string;
  approvalStatus?: KnowledgeApprovalStatus;
  uploadedFrom?: string;
  uploadedTo?: string;
  reviewedFrom?: string;
  reviewedTo?: string;
}

export interface DocRow {
  id: string;
  filename: string;
  display_name: string;
  format: string;
  size_bytes: number;
  status: string;
  chunk_count: number;
  error_message: string | null;
  created_at: string;
}

export interface AuditLog {
  id: number;
  user_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

export interface WorkdayEmployee {
  id: string;
  name: string;
}

export interface WorkdayOverview {
  active_start: string | null;
  active_end: string | null;
  active_time_range_seconds: number;
  trace_count: number;
  span_count: number;
  task_count: number;
  llm_call_count: number;
  tool_call_count: number;
  error_count: number;
  total_tokens: number;
  total_cost: number;
  avg_llm_latency_ms: number;
  p95_llm_latency_ms: number;
}

export interface WorkdayTask {
  task_id: string;
  title: string;
  duration_seconds: number;
  trace_count: number;
  span_count: number;
  llm_call_count: number;
  tool_call_count: number;
  error_count: number;
  total_tokens: number;
  total_cost: number;
  avg_llm_latency_ms: number;
}

export interface WorkdayFinding {
  finding_type: 'cost' | 'latency' | 'error';
  severity: 'medium' | 'high';
  title: string;
  description: string;
  evidence: Record<string, unknown>;
  trace_ids: string[];
  task_id: string | null;
  threshold: number;
  actual_value: number;
}

export interface WorkdayImportantTrace {
  trace_id: string;
  task_id: string;
  start_time: string;
  end_time: string;
  duration_seconds: number;
  span_count: number;
  llm_call_count: number;
  tool_call_count: number;
  error_count: number;
  total_tokens: number;
  total_cost: number;
  reasons: string[];
  replay_url: string | null;
}

export interface WorkdayDistillationCandidate {
  candidate_id: string;
  status: 'pending';
  title: string;
  reason: string;
  task_id: string | null;
  trace_ids: string[];
  signals: string[];
}

export interface WorkdayModelUsage {
  name: string;
  call_count: number;
  total_tokens: number;
  total_cost: number;
}

export interface WorkdayToolUsage {
  name: string;
  call_count: number;
  error_count: number;
}

export interface WorkdayRawMetrics {
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  cache_read_input_tokens: number;
  total_tokens: number;
  model_usage: WorkdayModelUsage[];
  tool_usage: WorkdayToolUsage[];
}

export interface WorkdaySummary {
  status: 'ok' | 'no_data';
  project_id: string;
  employee: WorkdayEmployee;
  date: string;
  timezone: 'Asia/Shanghai';
  overview: WorkdayOverview;
  narrative_summary: string;
  tasks: WorkdayTask[];
  findings: WorkdayFinding[];
  important_traces: WorkdayImportantTrace[];
  distillation_candidates: WorkdayDistillationCandidate[];
  raw_metrics: WorkdayRawMetrics | null;
  warnings: string[];
}

export interface WorkdaySummaryParams {
  employeeId: string;
  date: string;
  includeTraces: boolean;
  includeReplayRefs: boolean;
  includeRawMetrics: boolean;
}

export type AIUsageSource =
  | 'cc_switch'
  | 'chatgpt_web'
  | 'chatgpt_desktop'
  | 'openai_compliance'
  | 'smartbrain';

export interface AIUsageDepartmentOption {
  id: DepartmentId;
  name: string;
}

export interface AIUsageProjectOption {
  id: string;
  name: string;
  department_id: DepartmentId;
}

export interface AIUsageEmployeeOption {
  id: string;
  name: string;
  email: string;
  project_ids: string[];
}

export interface AIUsageOptions {
  mode: 'self' | 'admin';
  current_employee: AIUsageEmployeeOption;
  departments: AIUsageDepartmentOption[];
  projects: AIUsageProjectOption[];
  employees: AIUsageEmployeeOption[];
}

export interface AIUsageMessage {
  role: string;
  content: string;
  token_count: number | null;
  created_at: string | null;
}

export interface AIUsageRecord {
  id: string;
  record_type: 'chat' | 'trace';
  project_id: string;
  project_name: string;
  employee_id: string;
  employee_name: string;
  source: string;
  title: string;
  started_at: string;
  ended_at: string | null;
  task_id: string;
  task_title: string | null;
  model: string | null;
  status: string;
  duration_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost: number;
  error_count: number;
  trace_id: string | null;
  message_count: number;
  messages: AIUsageMessage[] | null;
}

export interface AIUsageDailyPoint {
  date: string;
  record_count: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  error_count: number;
}

export interface AIUsageHourlyPoint {
  hour: number;
  record_count: number;
  total_tokens: number;
}

export interface AIUsageSourcePoint {
  source: string;
  record_count: number;
  total_tokens: number;
}

export interface AIUsageSummary {
  start_date: string;
  end_date: string;
  period_days: number;
  active_days: number;
  record_count: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  average_tokens_per_day: number;
  error_count: number;
  total_cost: number;
  daily_usage: AIUsageDailyPoint[];
  hourly_usage: AIUsageHourlyPoint[];
  source_usage: AIUsageSourcePoint[];
}

export interface AIUsageQueryResult {
  mode: 'self' | 'admin';
  employee: AIUsageEmployeeOption;
  projects: AIUsageProjectOption[];
  timezone: 'Asia/Shanghai';
  summary: AIUsageSummary;
  records: AIUsageRecord[];
  has_more: boolean;
  warnings: string[];
}

export interface AIUsageQueryParams {
  startDate: string;
  endDate: string;
  employeeId?: string;
  source?: AIUsageSource;
  includeMessages?: boolean;
  limit?: number;
}

export interface AIUsageReport {
  employee: AIUsageEmployeeOption;
  summary: AIUsageSummary;
  high_frequency_periods: string[];
  report: string;
  model: string;
  generated_at: string;
}

export interface AIUsageReportParams {
  employeeId: string;
  startDate: string;
  endDate: string;
  source?: AIUsageSource;
}

export type DepartmentId = 'research' | 'marketing' | 'business';

export interface Department {
  id: DepartmentId;
  name: string;
  sort_order: number;
}

export interface ProjectRepository {
  project_id: string;
  git_url: string;
  git_branch: string;
}

export interface ProjectMemoryDraft {
  id: string;
  project_id: string;
  department_id: DepartmentId;
  department_name: string;
  title: string;
  status: 'pending_review' | 'approved' | 'rejected';
  markdown_content: string;
  source_count: number;
  document_id: string | null;
  skill_count?: number;
  generation_model?: string | null;
  generation_used_fallback?: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProjectMemoryReviewResult {
  id: string;
  status: 'pending_review' | 'approved' | 'rejected';
  document_id: string | null;
  chunk_count: number;
  wiki_page_count: number;
}

export interface ProjectWikiSource {
  source_type: string;
  source_id: string;
  locator: string | null;
}

export interface ProjectWikiLink {
  node_id?: string | null;
  to_title: string;
  relation: string;
}

export interface ProjectWikiPage {
  id: string;
  page_key: string;
  title: string;
  page_type: string;
  memory_kind: string;
  tags: string[];
  summary: string;
  markdown_content: string;
  usefulness: number;
  confidence: number;
  current_version: number;
  verification_status: 'generated' | 'verified' | 'stale';
  valid_from: string | null;
  valid_until: string | null;
  sources: ProjectWikiSource[];
  links: ProjectWikiLink[];
  created_at: string;
  updated_at: string;
}

export interface ProjectWikiChange {
  id: string;
  title: string;
  page_type: string;
  memory_kind: string;
  tags: string[];
  reason_code: string;
  status: string;
  summary: string;
  proposed_markdown: string;
  usefulness: number;
  confidence: number;
  contradiction: boolean;
  source_ids: string[];
  link_titles: string[];
  created_at: string;
}

export interface ProjectWikiRun {
  id: string;
  status: 'running' | 'completed' | 'failed';
  trigger_type: 'manual' | 'scheduled' | 'mcp_proposal';
  model: string;
  source_count: number;
  candidate_count: number;
  auto_applied_count: number;
  pending_review_count: number;
  discarded_count: number;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface ProjectWikiOverview {
  project: { id: string; name: string; department_id: string };
  permissions: { can_review: boolean; can_compile: boolean };
  summary: {
    page_count: number;
    pending_review_count: number;
    source_count: number;
    link_count: number;
  };
  pages: ProjectWikiPage[];
  pending_changes: ProjectWikiChange[];
  latest_run: ProjectWikiRun | null;
}

export interface ProjectWikiCompileResult {
  run_id: string;
  source_count: number;
  candidate_count: number;
  auto_applied_count: number;
  pending_review_count: number;
  discarded_count: number;
  model: string;
}

export interface ProjectWikiReviewResult {
  id: string;
  status: 'applied' | 'rejected';
  page_id: string | null;
}

export type AIMonitorComponentName =
  | 'cc_switch'
  | 'chatgpt_web_extension'
  | 'browser_shortcut'
  | 'chatgpt_desktop';

export type AIMonitorComponentStatus =
  | 'installed'
  | 'missing'
  | 'unknown'
  | 'unsupported'
  | 'error';

export interface AIMonitorComponentReport {
  name: AIMonitorComponentName;
  status: AIMonitorComponentStatus;
  version: string | null;
  last_seen_at: string | null;
  details: Record<string, unknown>;
}

export interface AIMonitorDeviceStatus {
  device_id: string;
  device_name: string | null;
  employee_id: string;
  employee_name: string;
  installer_version: string | null;
  os: string | null;
  components: Partial<Record<AIMonitorComponentName, AIMonitorComponentReport>>;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

export interface AIMonitorStatus {
  project_id: string | null;
  project_ids?: string[];
  employee_id: string;
  employee_name: string | null;
  summary: Record<AIMonitorComponentName, AIMonitorComponentStatus>;
  devices: AIMonitorDeviceStatus[];
}

export class ApiError extends Error {
  constructor(public status: number, public body: unknown, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, {
    credentials: 'include',
    ...init,
  });
  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    const detail: string =
      body && typeof body === 'object' && 'detail' in body && typeof (body as { detail: unknown }).detail === 'string'
        ? (body as { detail: string }).detail
        : `请求失败 (${res.status})`;
    throw new ApiError(res.status, body, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// 鉴权
export async function login(identifier: string, password: string): Promise<Me> {
  const normalizedIdentifier = identifier.trim();
  const email = normalizedIdentifier.includes('@')
    ? normalizedIdentifier
    : `${normalizedIdentifier}@local.dev`;
  await call('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  return getMe();
}

export async function logout(): Promise<void> {
  await call('/auth/logout', { method: 'POST' });
}

export async function getMe(): Promise<Me> {
  return call<Me>('/v4/auth/me');
}

// 项目
export async function listProjects(): Promise<Project[]> {
  return call<Project[]>('/v4/projects');
}

export async function createProject(input: {
  org_id: string;
  name: string;
  environment: 'development' | 'staging' | 'production';
  department_id?: DepartmentId;
  completed_at?: string | null;
}): Promise<Project> {
  return call<Project>('/v4/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function updateProject(
  projectId: string,
  input: { name?: string; completed_at?: string | null },
): Promise<Project> {
  return call<Project>(`/v4/projects/${encodeURIComponent(projectId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function deleteProject(projectId: string): Promise<void> {
  return call<void>(`/v4/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
  });
}

export async function listProjectMembers(projectId: string): Promise<ProjectMember[]> {
  return call<ProjectMember[]>(`/v4/projects/${projectId}/members`);
}

export async function addProjectMember(
  projectId: string,
  input: AddProjectMemberInput,
): Promise<ProjectMember> {
  return call<ProjectMember>(`/v4/projects/${projectId}/members`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function removeProjectMember(projectId: string, userId: string): Promise<void> {
  return call<void>(`/v4/projects/${projectId}/members/${userId}`, {
    method: 'DELETE',
  });
}

export async function resetProjectMemberPassword(
  projectId: string,
  userId: string,
  password: string,
): Promise<{ user_id: string; email: string; status: 'updated' }> {
  return call<{ user_id: string; email: string; status: 'updated' }>(
    `/v4/projects/${projectId}/members/${userId}/password`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    },
  );
}

// 知识库
export async function searchKnowledge(
  projectId: string,
  query: string,
  k = 5,
): Promise<SearchResult> {
  return call<SearchResult>('/v4/knowledge/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, query, k }),
  });
}

export async function answerQuestion(
  projectId: string,
  query: string,
  k = 5,
): Promise<AnswerResult> {
  return call<AnswerResult>('/v4/knowledge/answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, query, k }),
  });
}

export async function uploadDocument(
  projectId: string,
  file: File,
): Promise<UploadResult> {
  const fd = new FormData();
  fd.append('project_id', projectId);
  fd.append('display_name', file.name);
  fd.append('file', file);
  return call<UploadResult>('/v4/knowledge/upload', {
    method: 'POST',
    body: fd,
  });
}

export async function uploadProjectMaterialsBatch(
  projectId: string,
  departmentId: DepartmentId,
  files: File[],
): Promise<MaterialBatchUploadResult> {
  const fd = new FormData();
  fd.append('project_id', projectId);
  fd.append('department_id', departmentId);
  files.forEach((file) => fd.append('files', file));
  return call<MaterialBatchUploadResult>('/v4/knowledge/material-batches', {
    method: 'POST',
    body: fd,
  });
}

export interface ProjectWikiMcpToken {
  id: string;
  name: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
}

export interface ProjectWikiMcpTokenCreated extends Omit<ProjectWikiMcpToken, 'last_used_at'> {
  token: string;
}

export async function previewProjectMaterials(
  projectId: string,
  departmentId: DepartmentId,
  files: File[],
): Promise<MaterialIntakePreview> {
  const fd = new FormData();
  fd.append('project_id', projectId);
  fd.append('department_id', departmentId);
  files.forEach((file) => fd.append('files', file));
  return call<MaterialIntakePreview>('/v4/knowledge/material-intakes/preview', {
    method: 'POST',
    body: fd,
  });
}

export async function confirmMaterialIntake(
  intakeId: string,
  includedFileIds: string[],
): Promise<MaterialIntakeConfirmResult> {
  return call<MaterialIntakeConfirmResult>(
    `/v4/knowledge/material-intakes/${encodeURIComponent(intakeId)}/confirm`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ included_file_ids: includedFileIds }),
    },
  );
}

export function originalMaterialDownloadUrl(intakeId: string, fileId: string): string {
  return `${getApiBase()}/v4/knowledge/material-intakes/${encodeURIComponent(intakeId)}/files/${encodeURIComponent(fileId)}/download`;
}

export async function listKnowledgeLedger(params: KnowledgeLedgerParams): Promise<KnowledgeLedger> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.projectId);
  if (params.uploaderUserId) qs.set('uploader_user_id', params.uploaderUserId);
  if (params.approvalStatus) qs.set('approval_status', params.approvalStatus);
  if (params.uploadedFrom) qs.set('uploaded_from', params.uploadedFrom);
  if (params.uploadedTo) qs.set('uploaded_to', params.uploadedTo);
  if (params.reviewedFrom) qs.set('reviewed_from', params.reviewedFrom);
  if (params.reviewedTo) qs.set('reviewed_to', params.reviewedTo);
  return call<KnowledgeLedger>(`/v4/knowledge/ledger?${qs.toString()}`);
}

export async function listProjectDocuments(projectId: string): Promise<DocRow[]> {
  try {
    return await call<DocRow[]>(`/v4/projects/${projectId}/documents`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) return [];
    throw e;
  }
}

export async function deleteKnowledgeDocument(documentId: string): Promise<void> {
  return call<void>(`/v4/knowledge/documents/${encodeURIComponent(documentId)}`, {
    method: 'DELETE',
  });
}

export async function deleteDocument(documentId: string): Promise<void> {
  // 当前后端没 DELETE 端点,先用 throw 占位
  throw new ApiError(501, null, '删除功能尚未上线');
}

// 审计（仅 admin+）
export async function listAuditLogs(
  filters: { user_id?: string; action?: string; limit?: number; offset?: number } = {},
): Promise<AuditLog[]> {
  const qs = new URLSearchParams();
  if (filters.user_id) qs.set('user_id', filters.user_id);
  if (filters.action) qs.set('action', filters.action);
  if (filters.limit) qs.set('limit', String(filters.limit));
  if (filters.offset) qs.set('offset', String(filters.offset));
  return call<AuditLog[]>(`/v4/admin/audit-logs?${qs}`);
}

// AI 工作日
export async function getWorkdaySummary(
  projectId: string,
  params: WorkdaySummaryParams,
): Promise<WorkdaySummary> {
  const qs = new URLSearchParams({
    employee_id: params.employeeId,
    date: params.date,
    include_traces: String(params.includeTraces),
    include_replay_refs: String(params.includeReplayRefs),
    include_raw_metrics: String(params.includeRawMetrics),
  });
  return call<WorkdaySummary>(
    `/v4/workday/summary/${encodeURIComponent(projectId)}?${qs.toString()}`,
  );
}

export async function getAIUsageOptions(): Promise<AIUsageOptions> {
  return call<AIUsageOptions>('/v4/ai-usage/options');
}

export async function getAIUsageRecords(
  params: AIUsageQueryParams,
): Promise<AIUsageQueryResult> {
  const qs = new URLSearchParams({
    start_date: params.startDate,
    end_date: params.endDate,
    include_messages: String(params.includeMessages ?? true),
    limit: String(params.limit ?? 100),
  });
  if (params.employeeId) qs.set('employee_id', params.employeeId);
  if (params.source) qs.set('source', params.source);
  return call<AIUsageQueryResult>(`/v4/ai-usage/records?${qs.toString()}`);
}

export async function createAIUsageReport(
  params: AIUsageReportParams,
): Promise<AIUsageReport> {
  return call<AIUsageReport>('/v4/ai-usage/report', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      employee_id: params.employeeId,
      start_date: params.startDate,
      end_date: params.endDate,
      source: params.source,
    }),
  });
}

// 项目长期记忆
export async function listProjectMemoryDepartments(): Promise<Department[]> {
  return call<Department[]>('/v4/project-memory/departments');
}

export async function getProjectRepository(
  projectId: string,
): Promise<ProjectRepository | null> {
  return call<ProjectRepository | null>(
    `/v4/project-memory/projects/${encodeURIComponent(projectId)}/repository`,
  );
}

export async function upsertProjectRepository(
  projectId: string,
  input: { git_url: string; git_branch: string },
): Promise<ProjectRepository> {
  return call<ProjectRepository>(
    `/v4/project-memory/projects/${encodeURIComponent(projectId)}/repository`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    },
  );
}

export async function createProjectMemoryDraft(
  projectId: string,
  departmentId: DepartmentId,
  files: File[],
): Promise<ProjectMemoryDraft> {
  const fd = new FormData();
  fd.append('project_id', projectId);
  fd.append('department_id', departmentId);
  files.forEach((file) => fd.append('files', file));
  return call<ProjectMemoryDraft>('/v4/project-memory/drafts', {
    method: 'POST',
    body: fd,
  });
}

export async function listProjectMemoryDrafts(
  projectId: string,
): Promise<ProjectMemoryDraft[]> {
  return call<ProjectMemoryDraft[]>(
    `/v4/project-memory/drafts?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function reviewProjectMemoryDraft(
  draftId: string,
  decision: 'approve' | 'reject',
  comment?: string,
): Promise<ProjectMemoryReviewResult> {
  return call<ProjectMemoryReviewResult>(
    `/v4/project-memory/drafts/${encodeURIComponent(draftId)}/review`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, comment }),
    },
  );
}

// 项目 Wiki
export async function getProjectWikiOverview(
  projectId: string,
): Promise<ProjectWikiOverview> {
  return call<ProjectWikiOverview>(
    `/v4/project-wiki/overview?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function compileProjectWiki(
  projectId: string,
): Promise<ProjectWikiCompileResult> {
  return call<ProjectWikiCompileResult>('/v4/project-wiki/compile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId }),
  });
}

export async function reviewProjectWikiChange(
  changeId: string,
  decision: 'approve' | 'reject',
  comment?: string,
): Promise<ProjectWikiReviewResult> {
  return call<ProjectWikiReviewResult>(
    `/v4/project-wiki/changes/${encodeURIComponent(changeId)}/review`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, comment }),
    },
  );
}

export async function listProjectWikiMcpTokens(): Promise<ProjectWikiMcpToken[]> {
  return call<ProjectWikiMcpToken[]>('/v4/project-wiki/mcp-tokens');
}

export async function createProjectWikiMcpToken(
  name: string,
  scopes: Array<'wiki:read' | 'wiki:propose'>,
  expiresDays: number,
): Promise<ProjectWikiMcpTokenCreated> {
  return call<ProjectWikiMcpTokenCreated>('/v4/project-wiki/mcp-tokens', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, scopes, expires_days: expiresDays }),
  });
}

export async function revokeProjectWikiMcpToken(tokenId: string): Promise<void> {
  await call<void>(`/v4/project-wiki/mcp-tokens/${encodeURIComponent(tokenId)}`, {
    method: 'DELETE',
  });
}

// AI Monitor 安装检测
export async function getAIMonitorStatus(
  employeeId?: string,
): Promise<AIMonitorStatus> {
  const qs = new URLSearchParams();
  if (employeeId?.trim()) qs.set('employee_id', employeeId.trim());
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return call<AIMonitorStatus>(
    `/v4/ai-monitor/status${suffix}`,
  );
}
