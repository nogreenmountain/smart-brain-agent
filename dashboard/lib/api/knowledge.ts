// Knowledge base API client. All functions rely on the httpOnly session
// cookie set by /auth/login; fetchAuthenticatedApi includes credentials.
import { fetchAuthenticatedApi, ApiError } from '@/lib/api-client';

export interface OrgMembership {
  org_id: string;
  org_name: string;
  role: 'owner' | 'admin' | 'developer' | 'business_user';
}

export interface MeResponse {
  user_id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  memberships: OrgMembership[];
}

export interface Project {
  id: string;
  org_id: string;
  name: string;
  environment: string;
}

export interface SearchHit {
  chunk_id: string;
  document_id: string;
  document_name: string;
  content: string;
  source_page: number | null;
  source_line: number | null;
  chunk_index: number;
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

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
}

export interface AnswerResponse {
  query: string;
  hits: SearchHit[];
  synthesis: string;
  source: 'llm' | 'stub';
}

export interface AuditLog {
  id: number;
  user_id: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  metadata: Record<string, any>;
  ip_address: string | null;
  created_at: string;
}

export interface UploadResult {
  document_id: string;
  filename: string;
  chunk_count: number;
  status: string;
  error: string | null;
}

export async function getMe(): Promise<MeResponse> {
  return fetchAuthenticatedApi<MeResponse>('/v4/auth/me');
}

export async function listProjects(): Promise<Project[]> {
  return fetchAuthenticatedApi<Project[]>('/v4/projects');
}

export async function searchKnowledge(
  projectId: string,
  query: string,
  k = 5,
): Promise<SearchResponse> {
  return fetchAuthenticatedApi<SearchResponse>('/v4/knowledge/search', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, query, k }),
  });
}

export async function answerQuestion(
  projectId: string,
  query: string,
  k = 5,
): Promise<AnswerResponse> {
  return fetchAuthenticatedApi<AnswerResponse>('/v4/knowledge/answer', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, query, k }),
  });
}

export async function uploadDocument(
  projectId: string,
  file: File,
  displayName?: string,
): Promise<UploadResult> {
  const fd = new FormData();
  fd.append('project_id', projectId);
  fd.append('display_name', displayName || file.name);
  fd.append('file', file);
  return fetchAuthenticatedApi<UploadResult>('/v4/knowledge/upload', {
    method: 'POST',
    body: fd,
    // do not set Content-Type; browser will set the multipart boundary
  });
}

export async function listAuditLogs(
  filters: { user_id?: string; action?: string; limit?: number; offset?: number } = {},
): Promise<AuditLog[]> {
  const qs = new URLSearchParams();
  if (filters.user_id) qs.set('user_id', filters.user_id);
  if (filters.action) qs.set('action', filters.action);
  if (filters.limit) qs.set('limit', String(filters.limit));
  if (filters.offset) qs.set('offset', String(filters.offset));
  return fetchAuthenticatedApi<AuditLog[]>(`/v4/admin/audit-logs?${qs}`);
}
