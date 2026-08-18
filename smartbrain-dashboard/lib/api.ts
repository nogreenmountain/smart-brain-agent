// 智慧大脑 - 后端 API 调用客户端
// 全部用 cookie 鉴权（后端发 session_id httpOnly cookie）
// 这个文件只能在 client component 里用,server component 直接 fetch 会失败

import { apiBaseForLocation } from '@/utils/service-endpoints';

function getApiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== 'undefined') {
    return apiBaseForLocation(window.location);
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
  nickname?: string | null;
  display_name?: string;
  ai_detail_visible_to_admin?: boolean;
  is_system_admin?: boolean;
  can_manage_projects?: boolean;
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

export type ProjectCreationRequestStatus = 'pending' | 'approved' | 'rejected';

export interface ProjectCreationRequest {
  id: string;
  requester_id: string;
  requester_username: string;
  org_id: string;
  org_name: string;
  name: string;
  environment: string;
  department_id: DepartmentId;
  department_name: string;
  completed_at?: string | null;
  reason: string;
  status: ProjectCreationRequestStatus;
  review_comment?: string | null;
  reviewed_by_user_id?: string | null;
  created_project_id?: string | null;
  created_at: string;
  reviewed_at?: string | null;
}

export type ProjectRole = 'owner' | 'admin' | 'developer' | 'business_user';

export interface ProjectMember {
  user_id: string;
  email: string;
  username: string;
  nickname?: string | null;
  display_name?: string;
  role: ProjectRole;
}

export interface ProjectMemberOption {
  user_id: string;
  email: string;
  username: string;
  nickname?: string | null;
  display_name: string;
}

export interface TeamMember extends ProjectMemberOption {
  is_active: boolean;
  is_system_admin: boolean;
  project_count: number;
  created_at?: string | null;
  deactivated_at?: string | null;
}

export interface CreateTeamMemberInput {
  username: string;
  nickname?: string | null;
  password: string;
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
  draft_id: string;
}

export interface MaterialUploadSessionFile {
  id: string;
  filename: string;
  format: string;
  size_bytes: number;
  received_bytes: number;
}

export interface MaterialUploadSession {
  intake_id: string;
  status: 'uploading' | 'pending_review';
  files: MaterialUploadSessionFile[];
}

interface MaterialUploadChunkResult {
  file_id: string;
  received_bytes: number;
  size_bytes: number;
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
  asset_id: string;
  asset_type: 'project_material' | 'project_wiki' | 'meeting_record';
  document_id: string | null;
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
  meeting_date?: string | null;
}

export interface KnowledgeLedger {
  category: KnowledgeLedgerCategory;
  project: KnowledgeLedgerProject;
  permissions: { can_review: boolean; can_manage: boolean; can_delete: boolean };
  leaders: KnowledgeLedgerUser[];
  uploaders: KnowledgeLedgerUser[];
  summary: KnowledgeLedgerSummary;
  documents: KnowledgeLedgerDocument[];
}

export interface KnowledgeLedgerParams {
  projectId: string;
  category?: KnowledgeLedgerCategory;
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
  detail_visible_to_admin?: boolean;
}

export interface AIUsageOptions {
  mode: 'self' | 'admin' | 'statistics';
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
  mode: 'self' | 'admin' | 'statistics';
  employee: AIUsageEmployeeOption;
  projects: AIUsageProjectOption[];
  timezone: 'Asia/Shanghai';
  summary: AIUsageSummary;
  records: AIUsageRecord[];
  has_more: boolean;
  warnings: string[];
  detail_visible?: boolean;
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

export interface CCSwitchUsageSyncStatus {
  status: 'never' | 'ok' | 'not_running' | 'error';
  employee_id: string;
  employee_name: string;
  device_id?: string | null;
  trigger?: 'automatic' | 'manual' | null;
  request_id?: string | null;
  range_start?: string | null;
  range_end?: string | null;
  row_count?: number;
  request_count?: number;
  total_tokens?: number;
  attempted_at?: string | null;
  synced_at?: string | null;
  cc_switch_running?: boolean | null;
  error_message?: string | null;
}

export type SharedSessionStopMode = 'default_19' | 'custom' | 'manual_only';
export type SharedSessionStatus =
  | 'starting'
  | 'active'
  | 'finalizing'
  | 'pending_sync'
  | 'finalized'
  | 'cancelled'
  | 'expired';

export interface SharedCCSwitchSession {
  id: string;
  project_id?: string | null;
  target_employee_id: string;
  target_employee_name: string;
  device_id?: string | null;
  stop_mode: SharedSessionStopMode;
  stop_reason?: string | null;
  status: SharedSessionStatus;
  requested_at: string;
  started_at?: string | null;
  scheduled_stop_at: string;
  actual_stop_at?: string | null;
  request_count: number;
  total_tokens: number;
  last_synced_at?: string | null;
  last_synced_watermark?: string | null;
  finalized_at?: string | null;
  error_message?: string | null;
  activation_token?: string | null;
}

export interface StartSharedCCSwitchSessionInput {
  installationProbeId: string;
  stopMode: SharedSessionStopMode;
  scheduledStopAt?: string;
}

export interface TemporaryMonitorProbe {
  id: string;
  status: 'pending' | 'detected' | 'expired' | 'consumed';
  expires_at: string;
  detected_at?: string | null;
  device_id?: string | null;
  installer_version?: string | null;
  probe_token?: string;
}

export interface AIDailyWorkItem {
  title: string;
  problem: string;
  actions: string[];
  result: string;
  artifacts: string[];
  validation: string[];
}

export interface AIDailyWorkLog {
  id: string;
  work_date: string;
  employee_id: string;
  employee_name: string;
  report_markdown: string;
  work_items: AIDailyWorkItem[];
  source_count: number;
  model: string;
  generated_at: string;
}

export interface AIDailyWorkLogList {
  employee: AIUsageEmployeeOption;
  timezone: 'Asia/Shanghai';
  items: AIDailyWorkLog[];
}

export interface AIDailyWorkLogParams {
  startDate: string;
  endDate: string;
  employeeId?: string;
}

export type MemberWikiTaskType =
  | 'development'
  | 'debugging'
  | 'deployment'
  | 'configuration'
  | 'data_processing'
  | 'documentation'
  | 'testing'
  | 'research'
  | 'operations'
  | 'other';

export type MemberWikiOutcome = 'success' | 'partial' | 'failure';

export interface MemberWikiMember {
  user_id: string;
  employee_id: string;
  name: string;
  email: string;
}

export interface MemberWikiOptions {
  mode: 'self' | 'admin';
  current_member: MemberWikiMember;
  members: MemberWikiMember[];
}

export interface MemberWikiExperience {
  id: string;
  employee_id: string;
  employee_name: string;
  experience_key: string;
  title: string;
  task_type: MemberWikiTaskType;
  outcome: MemberWikiOutcome;
  summary: string;
  markdown_content: string;
  tags: string[];
  tools: string[];
  confidence: number;
  first_observed: string;
  last_observed: string;
  observation_count: number;
  current_version: number;
  updated_at: string;
  lexical_score: number;
  vector_score: number | null;
}

export interface MemberWikiOverview {
  mode: 'self' | 'admin';
  member: MemberWikiMember;
  timezone: 'Asia/Shanghai';
  summary: {
    experience_count: number;
    success_count: number;
    failure_count: number;
    latest_observed: string | null;
  };
  experiences: MemberWikiExperience[];
  latest_run: {
    id: string;
    status: string;
    cutoff_at: string;
    updated_member_count: number;
    session_count: number;
    experience_count: number;
    completed_at: string | null;
  } | null;
}

export interface MemberWikiOverviewParams {
  employeeId?: string;
  query?: string;
  taskType?: MemberWikiTaskType;
  outcome?: MemberWikiOutcome;
  tag?: string;
  limit?: number;
}

export interface AIUsageLeaderboardMember {
  rank: number;
  employee_id: string;
  employee_name: string;
  account: string;
  total_tokens: number;
  request_count: number;
  active_days: number;
  average_tokens_per_day: number;
  average_tokens_per_request: number;
  share_percent: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  error_count: number;
  total_cost: number;
  official_cc_switch: boolean;
}

export interface AIUsageLeaderboardDistributionPoint {
  key: string;
  label: string;
  total_tokens: number;
  request_count: number;
  percentage: number;
}

export interface AIUsageLeaderboardResult {
  start_date: string;
  end_date: string;
  period_days: number;
  timezone: 'Asia/Shanghai';
  total_tokens: number;
  request_count: number;
  active_users: number;
  active_days: number;
  average_tokens_per_user: number;
  official_cc_switch_users: number;
  members: AIUsageLeaderboardMember[];
  daily_usage: Array<{
    date: string;
    total_tokens: number;
    request_count: number;
    active_users: number;
  }>;
  source_usage: AIUsageLeaderboardDistributionPoint[];
  app_usage: AIUsageLeaderboardDistributionPoint[];
  token_usage: AIUsageLeaderboardDistributionPoint[];
  model_usage: AIUsageLeaderboardDistributionPoint[];
  privacy_notice: string;
}

export interface AIUsageLeaderboardParams {
  startDate: string;
  endDate: string;
}

export interface MeetingSummary {
  id: string;
  project_id: string;
  project_name: string;
  title: string;
  meeting_date: string;
  participant_user_ids: string[];
  participants: string[];
  tags: string[];
  summary_markdown: string;
  decisions: string[];
  action_items: string[];
  source_filename: string | null;
  source_format: string | null;
  source_size_bytes: number | null;
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  lexical_score: number;
  vector_score: number | null;
}

export interface MeetingSummaryList {
  items: MeetingSummary[];
}

export interface MeetingSummaryListParams {
  projectId: string;
  query?: string;
  tag?: string;
  meetingDateFrom?: string;
  meetingDateTo?: string;
  limit?: number;
}

export interface MeetingSubmission {
  id: string;
  draft_id: string;
  project_id: string;
  title: string;
  status: 'pending_review';
}

export interface CreateMeetingSummaryInput {
  projectId: string;
  title: string;
  meetingDate: string;
  participantUserIds: string[];
  file: File;
}

export type MeetingParticipantOption = ProjectMemberOption;

export type DepartmentId = string;

export type KnowledgeLedgerCategory = 'project_material' | 'project_wiki_source' | 'meeting_record';

export interface Department {
  id: DepartmentId;
  name: string;
  sort_order: number;
  parent_id?: DepartmentId | null;
  parent_name?: string | null;
  allows_projects?: boolean;
  level?: 1 | 2;
  is_direct?: boolean;
}

export interface ProjectDepartmentMigration {
  id: string;
  project_id: string;
  source_department_id?: DepartmentId | null;
  target_department_id?: DepartmentId | null;
  source_department_name: string;
  target_department_name: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress: number;
  current_step: string;
  raw_material_count: number;
  wiki_page_count: number;
  meeting_record_count: number;
  documents_updated?: number;
  intakes_updated?: number;
  drafts_updated?: number;
  verified: boolean;
  error_message?: string | null;
  created_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ProjectRepository {
  project_id: string;
  git_url: string;
  git_branch: string;
  status?: 'pending_review' | 'approved' | 'rejected' | null;
  draft_id?: string | null;
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

export interface ProjectMemoryReviewQueueItem {
  id: string;
  project_id: string;
  project_name: string;
  department_id: DepartmentId;
  department_name: string;
  department_path: string;
  title: string;
  status: 'pending_review' | 'approved' | 'rejected';
  markdown_content: string;
  source_count: number;
  review_kind?: 'project_material' | 'meeting_summary' | 'project_repository';
  uploader: {
    user_id: string | null;
    username: string | null;
    nickname: string | null;
    display_name: string;
  };
  file_names: string[];
  total_size_bytes: number;
  repository_url?: string | null;
  repository_branch?: string | null;
  meeting_date?: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProjectMemoryReviewResult {
  id: string;
  status: 'pending_review' | 'approved' | 'rejected';
  document_id: string | null;
  resource_id?: string | null;
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

export interface ProjectWikiUploader {
  user_id: string;
  name: string;
  email: string;
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
  uploaded_by: ProjectWikiUploader | null;
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
  uploaded_by: ProjectWikiUploader | null;
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

export interface UploadProgress {
  phase: 'uploading' | 'processing';
  percent: number | null;
  loadedBytes: number;
  totalBytes: number;
}

export type UploadProgressHandler = (progress: UploadProgress) => void;

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

function multipartCallWithProgress<T>(
  path: string,
  body: FormData,
  onProgress: UploadProgressHandler,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', `${getApiBase()}${path}`);
    request.withCredentials = true;
    let loadedBytes = 0;
    let totalBytes = 0;
    request.upload.onprogress = (event) => {
      loadedBytes = event.loaded;
      totalBytes = event.lengthComputable ? event.total : 0;
      onProgress({
        phase: 'uploading',
        percent: event.lengthComputable && event.total > 0
          ? Math.min(100, Math.round((event.loaded / event.total) * 100))
          : null,
        loadedBytes,
        totalBytes,
      });
    };
    request.upload.onload = () => {
      onProgress({
        phase: 'processing',
        percent: null,
        loadedBytes: totalBytes || loadedBytes,
        totalBytes: totalBytes || loadedBytes,
      });
    };
    request.onerror = () => reject(new Error('网络连接失败，文件尚未完成上传，请检查网络后重试。'));
    request.onabort = () => reject(new Error('上传已取消。'));
    request.onload = () => {
      let responseBody: unknown = null;
      if (request.responseText) {
        try {
          responseBody = JSON.parse(request.responseText);
        } catch {
          responseBody = null;
        }
      }
      if (request.status < 200 || request.status >= 300) {
        const detail = responseBody
          && typeof responseBody === 'object'
          && 'detail' in responseBody
          && typeof (responseBody as { detail: unknown }).detail === 'string'
          ? (responseBody as { detail: string }).detail
          : `请求失败 (${request.status || '网络错误'})`;
        reject(new ApiError(request.status, responseBody, detail));
        return;
      }
      resolve(responseBody as T);
    };
    request.send(body);
  });
}

function binaryCallWithProgress<T>(
  path: string,
  body: Blob,
  onProgress: (loadedBytes: number) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('PUT', `${getApiBase()}${path}`);
    request.withCredentials = true;
    request.setRequestHeader('Content-Type', 'application/octet-stream');
    request.upload.onprogress = (event) => onProgress(event.loaded);
    request.onerror = () => reject(new Error('网络连接失败，当前分块尚未确认，请检查网络后重试。'));
    request.onabort = () => reject(new Error('上传已取消。'));
    request.onload = () => {
      let responseBody: unknown = null;
      if (request.responseText) {
        try {
          responseBody = JSON.parse(request.responseText);
        } catch {
          responseBody = null;
        }
      }
      if (request.status < 200 || request.status >= 300) {
        const detail = responseBody
          && typeof responseBody === 'object'
          && 'detail' in responseBody
          && typeof (responseBody as { detail: unknown }).detail === 'string'
          ? (responseBody as { detail: string }).detail
          : `请求失败 (${request.status || '网络错误'})`;
        reject(new ApiError(request.status, responseBody, detail));
        return;
      }
      resolve(responseBody as T);
    };
    request.send(body);
  });
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

export async function updateMyProfile(
  nickname: string | null,
  aiDetailVisibleToAdmin: boolean,
): Promise<Me> {
  return call<Me>('/v4/auth/me/profile', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      nickname,
      ai_detail_visible_to_admin: aiDetailVisibleToAdmin,
    }),
  });
}

export async function changeMyPassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ status: 'updated' }> {
  return call<{ status: 'updated' }>('/v4/auth/me/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

// 项目
export async function listProjects(): Promise<Project[]> {
  return call<Project[]>('/v4/projects');
}

export async function listProjectCatalog(): Promise<Project[]> {
  return call<Project[]>('/v4/projects/catalog');
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

export async function listProjectCreationRequests(): Promise<ProjectCreationRequest[]> {
  return call<ProjectCreationRequest[]>('/v4/project-requests');
}

export async function submitProjectCreationRequest(input: {
  org_id: string;
  name: string;
  environment: 'development' | 'staging' | 'production';
  department_id: DepartmentId;
  completed_at?: string | null;
  reason: string;
}): Promise<ProjectCreationRequest> {
  return call<ProjectCreationRequest>('/v4/project-requests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function reviewProjectCreationRequest(
  requestId: string,
  decision: 'approve' | 'reject',
  comment: string,
): Promise<ProjectCreationRequest> {
  return call<ProjectCreationRequest>(`/v4/project-requests/${encodeURIComponent(requestId)}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, comment }),
  });
}

export async function updateProject(
  projectId: string,
  input: { name?: string; completed_at?: string | null; department_id?: DepartmentId },
): Promise<Project> {
  return call<Project>(`/v4/projects/${encodeURIComponent(projectId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function deleteProject(projectId: string, confirmName: string): Promise<void> {
  const qs = new URLSearchParams({ confirm_name: confirmName });
  return call<void>(`/v4/projects/${encodeURIComponent(projectId)}?${qs.toString()}`, {
    method: 'DELETE',
  });
}

export async function startProjectDepartmentMigration(
  projectId: string,
  input: {
    target_department_id: DepartmentId;
    expected_source_department_id: DepartmentId;
    migrate_knowledge_base: true;
    idempotency_key?: string;
  },
): Promise<ProjectDepartmentMigration> {
  return call<ProjectDepartmentMigration>(`/v4/projects/${encodeURIComponent(projectId)}/department-migrations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function getProjectDepartmentMigration(
  projectId: string,
  migrationId: string,
): Promise<ProjectDepartmentMigration> {
  return call<ProjectDepartmentMigration>(
    `/v4/projects/${encodeURIComponent(projectId)}/department-migrations/${encodeURIComponent(migrationId)}`,
  );
}

export async function listProjectMembers(projectId: string): Promise<ProjectMember[]> {
  return call<ProjectMember[]>(`/v4/projects/${projectId}/members`);
}

export async function listProjectMemberOptions(projectId: string): Promise<ProjectMemberOption[]> {
  return call<ProjectMemberOption[]>(`/v4/projects/${encodeURIComponent(projectId)}/member-options`);
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

export async function listTeamMembers(): Promise<TeamMember[]> {
  return call<TeamMember[]>('/v4/team-members');
}

export async function createTeamMember(input: CreateTeamMemberInput): Promise<TeamMember> {
  return call<TeamMember>('/v4/team-members', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function deactivateTeamMember(userId: string): Promise<void> {
  return call<void>(`/v4/team-members/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
}

export async function reactivateTeamMember(userId: string): Promise<TeamMember> {
  return call<TeamMember>(`/v4/team-members/${encodeURIComponent(userId)}/reactivate`, {
    method: 'POST',
  });
}

export async function renameTeamMemberUsername(
  userId: string,
  username: string,
): Promise<TeamMember> {
  return call<TeamMember>(`/v4/team-members/${encodeURIComponent(userId)}/username`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username }),
  });
}

export async function resetTeamMemberPassword(
  userId: string,
  password: string,
): Promise<{ user_id: string; email: string; status: 'updated' }> {
  return call<{ user_id: string; email: string; status: 'updated' }>(
    `/v4/team-members/${encodeURIComponent(userId)}/password`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    },
  );
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
  onProgress?: UploadProgressHandler,
): Promise<MaterialIntakePreview> {
  const fd = new FormData();
  fd.append('project_id', projectId);
  fd.append('department_id', departmentId);
  files.forEach((file) => fd.append('files', file));
  if (onProgress) {
    return multipartCallWithProgress<MaterialIntakePreview>(
      '/v4/knowledge/material-intakes/preview',
      fd,
      onProgress,
    );
  }
  return call<MaterialIntakePreview>('/v4/knowledge/material-intakes/preview', {
    method: 'POST',
    body: fd,
  });
}

const MATERIAL_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024;

export async function uploadProjectMaterialsDirect(
  projectId: string,
  departmentId: DepartmentId,
  files: File[],
  clientUploadId: string,
  onProgress?: UploadProgressHandler,
): Promise<MaterialIntakeConfirmResult> {
  const session = await call<MaterialUploadSession>('/v4/knowledge/material-intakes/upload-sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_id: projectId,
      department_id: departmentId,
      client_upload_id: clientUploadId,
      files: files.map((file) => ({ filename: file.name, size_bytes: file.size })),
    }),
  });
  const totalBytes = files.reduce((total, file) => total + file.size, 0);
  let confirmedBytes = session.files.reduce((total, file) => total + file.received_bytes, 0);
  const emitUploadProgress = (loadedBytes: number) => {
    onProgress?.({
      phase: 'uploading',
      percent: totalBytes > 0 ? Math.min(100, Math.round((loadedBytes / totalBytes) * 100)) : 100,
      loadedBytes,
      totalBytes,
    });
  };
  emitUploadProgress(confirmedBytes);

  const localFiles = new Map(files.map((file) => [file.name, file]));
  for (const remoteFile of session.files) {
    const localFile = localFiles.get(remoteFile.filename);
    if (!localFile) {
      throw new Error(`上传会话中的文件与当前选择不一致：${remoteFile.filename}`);
    }
    if (remoteFile.received_bytes < 0 || remoteFile.received_bytes > localFile.size) {
      throw new Error(`服务器返回了无效的上传进度：${remoteFile.filename}`);
    }
    let offset = remoteFile.received_bytes;
    while (offset < localFile.size) {
      const chunk = localFile.slice(offset, Math.min(offset + MATERIAL_UPLOAD_CHUNK_BYTES, localFile.size));
      const confirmedBeforeChunk = confirmedBytes;
      const response = await binaryCallWithProgress<MaterialUploadChunkResult>(
        `/v4/knowledge/material-intakes/upload-sessions/${encodeURIComponent(session.intake_id)}/files/${encodeURIComponent(remoteFile.id)}?offset=${offset}`,
        chunk,
        (chunkLoadedBytes) => emitUploadProgress(confirmedBeforeChunk + chunkLoadedBytes),
      );
      if (response.received_bytes <= offset || response.received_bytes > localFile.size) {
        throw new Error(`服务器未确认完整上传分块：${remoteFile.filename}`);
      }
      confirmedBytes += response.received_bytes - offset;
      offset = response.received_bytes;
      emitUploadProgress(confirmedBytes);
    }
  }

  onProgress?.({
    phase: 'processing',
    percent: null,
    loadedBytes: totalBytes,
    totalBytes,
  });
  return call<MaterialIntakeConfirmResult>(
    `/v4/knowledge/material-intakes/upload-sessions/${encodeURIComponent(session.intake_id)}/complete`,
    { method: 'POST' },
  );
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

export async function cancelMaterialIntake(intakeId: string): Promise<void> {
  return call<void>(`/v4/knowledge/material-intakes/${encodeURIComponent(intakeId)}`, {
    method: 'DELETE',
  });
}

export function originalMaterialDownloadUrl(intakeId: string, fileId: string): string {
  return `${getApiBase()}/v4/knowledge/material-intakes/${encodeURIComponent(intakeId)}/files/${encodeURIComponent(fileId)}/download`;
}

export async function listKnowledgeLedger(params: KnowledgeLedgerParams): Promise<KnowledgeLedger> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.projectId);
  qs.set('category', params.category || 'project_material');
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

// AI 工作记录
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

export type KnowledgeAssetType = 'project_material' | 'project_wiki' | 'meeting_record';

export interface KnowledgeAssetPreview {
  asset_id: string;
  asset_type: KnowledgeAssetType;
  project_id: string;
  name: string;
  format: string;
  content: string;
}

export async function renameKnowledgeAsset(
  assetType: KnowledgeAssetType,
  assetId: string,
  name: string,
): Promise<void> {
  await call(`/v4/knowledge/assets/${encodeURIComponent(assetType)}/${encodeURIComponent(assetId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

export async function moveKnowledgeAsset(
  assetType: KnowledgeAssetType,
  assetId: string,
  targetProjectId: string,
): Promise<void> {
  await call(`/v4/knowledge/assets/${encodeURIComponent(assetType)}/${encodeURIComponent(assetId)}/move`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_project_id: targetProjectId }),
  });
}

export async function deleteKnowledgeAsset(assetType: KnowledgeAssetType, assetId: string): Promise<void> {
  await call(`/v4/knowledge/assets/${encodeURIComponent(assetType)}/${encodeURIComponent(assetId)}`, {
    method: 'DELETE',
  });
}

export async function previewKnowledgeAsset(
  assetType: KnowledgeAssetType,
  assetId: string,
): Promise<KnowledgeAssetPreview> {
  return call<KnowledgeAssetPreview>(
    `/v4/knowledge/assets/${encodeURIComponent(assetType)}/${encodeURIComponent(assetId)}/preview`,
  );
}

export function knowledgeAssetDownloadUrl(assetType: KnowledgeAssetType, assetId: string): string {
  return `${getApiBase()}/v4/knowledge/assets/${encodeURIComponent(assetType)}/${encodeURIComponent(assetId)}/download`;
}

export async function getAIUsageLeaderboard(
  params: AIUsageLeaderboardParams,
): Promise<AIUsageLeaderboardResult> {
  const qs = new URLSearchParams({
    start_date: params.startDate,
    end_date: params.endDate,
  });
  return call<AIUsageLeaderboardResult>(`/v4/ai-usage/leaderboard?${qs.toString()}`);
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

export async function getCCSwitchUsageSyncStatus(
  requestId?: string,
): Promise<CCSwitchUsageSyncStatus> {
  const qs = new URLSearchParams();
  if (requestId) qs.set('request_id', requestId);
  const suffix = qs.size > 0 ? `?${qs.toString()}` : '';
  return call<CCSwitchUsageSyncStatus>(`/v4/ai-usage/cc-switch-sync/status${suffix}`);
}

export async function getCurrentSharedCCSwitchSession(): Promise<SharedCCSwitchSession | null> {
  return call<SharedCCSwitchSession | null>('/v4/ai-usage/shared-sessions/current');
}

export async function createTemporaryMonitorProbe(): Promise<TemporaryMonitorProbe> {
  return call<TemporaryMonitorProbe>('/v4/ai-usage/temporary-monitor-probes', {
    method: 'POST',
  });
}

export async function getTemporaryMonitorProbe(probeId: string): Promise<TemporaryMonitorProbe> {
  return call<TemporaryMonitorProbe>(
    `/v4/ai-usage/temporary-monitor-probes/${encodeURIComponent(probeId)}`,
  );
}

export async function getSharedCCSwitchSession(
  sessionId: string,
): Promise<SharedCCSwitchSession> {
  return call<SharedCCSwitchSession>(
    `/v4/ai-usage/shared-sessions/${encodeURIComponent(sessionId)}`,
  );
}

export async function startSharedCCSwitchSession(
  input: StartSharedCCSwitchSessionInput,
): Promise<SharedCCSwitchSession> {
  return call<SharedCCSwitchSession>('/v4/ai-usage/shared-sessions/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      installation_probe_id: input.installationProbeId,
      stop_mode: input.stopMode,
      scheduled_stop_at: input.scheduledStopAt,
    }),
  });
}

export async function updateSharedCCSwitchSessionSchedule(
  sessionId: string,
  stopMode: SharedSessionStopMode,
  scheduledStopAt?: string,
): Promise<SharedCCSwitchSession> {
  return call<SharedCCSwitchSession>(
    `/v4/ai-usage/shared-sessions/${encodeURIComponent(sessionId)}/schedule`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stop_mode: stopMode,
        scheduled_stop_at: scheduledStopAt,
      }),
    },
  );
}

export async function stopSharedCCSwitchSession(
  sessionId: string,
): Promise<SharedCCSwitchSession> {
  return call<SharedCCSwitchSession>(
    `/v4/ai-usage/shared-sessions/${encodeURIComponent(sessionId)}/stop`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'manual' }),
    },
  );
}

export async function getAIDailyWorkLogs(
  params: AIDailyWorkLogParams,
): Promise<AIDailyWorkLogList> {
  const qs = new URLSearchParams({
    start_date: params.startDate,
    end_date: params.endDate,
  });
  if (params.employeeId) qs.set('employee_id', params.employeeId);
  return call<AIDailyWorkLogList>(`/v4/ai-usage/daily-logs?${qs.toString()}`);
}

export async function getMemberWikiOptions(): Promise<MemberWikiOptions> {
  return call<MemberWikiOptions>('/v4/member-wiki/options');
}

export async function getMemberWikiOverview(
  params: MemberWikiOverviewParams = {},
): Promise<MemberWikiOverview> {
  const qs = new URLSearchParams();
  if (params.employeeId) qs.set('employee_id', params.employeeId);
  if (params.query) qs.set('query', params.query);
  if (params.taskType) qs.set('task_type', params.taskType);
  if (params.outcome) qs.set('outcome', params.outcome);
  if (params.tag) qs.set('tag', params.tag);
  qs.set('limit', String(params.limit ?? 50));
  return call<MemberWikiOverview>(`/v4/member-wiki/overview?${qs.toString()}`);
}

export async function listMeetingSummaries(
  params: MeetingSummaryListParams,
): Promise<MeetingSummaryList> {
  const qs = new URLSearchParams({ project_id: params.projectId });
  if (params.query) qs.set('query', params.query);
  if (params.tag) qs.set('tag', params.tag);
  if (params.meetingDateFrom) qs.set('meeting_date_from', params.meetingDateFrom);
  if (params.meetingDateTo) qs.set('meeting_date_to', params.meetingDateTo);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return call<MeetingSummaryList>(`/v4/meeting-summaries?${qs.toString()}`);
}

export async function listMeetingParticipantOptions(
  query = '',
  limit = 200,
): Promise<MeetingParticipantOption[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (query.trim()) qs.set('query', query.trim());
  return call<MeetingParticipantOption[]>(`/v4/meeting-participant-options?${qs.toString()}`);
}

export async function createMeetingSummary(
  input: CreateMeetingSummaryInput,
  onProgress?: UploadProgressHandler,
): Promise<MeetingSubmission> {
  const body = new FormData();
  body.set('project_id', input.projectId);
  body.set('title', input.title);
  body.set('meeting_date', input.meetingDate);
  body.set('participant_user_ids', JSON.stringify(input.participantUserIds));
  body.set('file', input.file);
  if (onProgress) {
    return multipartCallWithProgress<MeetingSubmission>('/v4/meeting-summaries', body, onProgress);
  }
  return call<MeetingSubmission>('/v4/meeting-summaries', { method: 'POST', body });
}

export function meetingSummaryFileUrl(meetingSummaryId: string): string {
  return `${getApiBase()}/v4/meeting-summaries/${encodeURIComponent(meetingSummaryId)}/file`;
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
export async function listProjectMemoryDepartments(includeGroups = false): Promise<Department[]> {
  return call<Department[]>(
    `/v4/project-memory/departments${includeGroups ? '?include_groups=true' : ''}`,
  );
}

export async function createProjectMemoryDepartment(input: {
  id?: DepartmentId;
  name: string;
  parent_id?: DepartmentId | null;
}): Promise<Department> {
  return call<Department>('/v4/project-memory/departments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function updateProjectMemoryDepartment(
  departmentId: DepartmentId,
  input: { name: string; sort_order: number; parent_id?: DepartmentId | null },
): Promise<Department> {
  return call<Department>(`/v4/project-memory/departments/${encodeURIComponent(departmentId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function reorderProjectMemoryDepartments(input: {
  parent_id?: DepartmentId | null;
  department_ids: DepartmentId[];
}): Promise<Department[]> {
  return call<Department[]>('/v4/project-memory/departments/reorder', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}

export async function deleteProjectMemoryDepartment(departmentId: DepartmentId): Promise<void> {
  return call<void>(`/v4/project-memory/departments/${encodeURIComponent(departmentId)}`, {
    method: 'DELETE',
  });
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

export async function listProjectMemoryReviewQueue(): Promise<ProjectMemoryReviewQueueItem[]> {
  return call<ProjectMemoryReviewQueueItem[]>('/v4/project-memory/review-queue');
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
