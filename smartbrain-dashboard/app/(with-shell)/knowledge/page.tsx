'use client';

import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ClipboardCheck, Download, ExternalLink, Eye, FileText, FolderKanban, MoveRight, Pencil, Trash2, Users, X } from 'lucide-react';
import {
  ApiError,
  Department,
  KnowledgeApprovalStatus,
  KnowledgeLedgerCategory,
  KnowledgeLedger,
  KnowledgeLedgerDocument,
  deleteKnowledgeAsset,
  knowledgeAssetDownloadUrl,
  listKnowledgeLedger,
  listProjectMemoryDepartments,
  listProjectCatalog,
  moveKnowledgeAsset,
  previewKnowledgeAsset,
  renameKnowledgeAsset,
  type KnowledgeAssetPreview,
  Project,
} from '@/lib/api';
import { Button } from '@/components/Button';
import { EmptyState, LoadingDots, Toast } from '@/components/Feedback';
import { Input } from '@/components/Input';
import { ProjectHierarchySelector } from '@/components/ProjectHierarchySelector';
import { Select } from '@/components/Select';

const APPROVAL_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'raw_uploaded', label: '未生成草稿' },
  { value: 'pending_review', label: '待审批' },
  { value: 'approved', label: '已审批入库' },
  { value: 'rejected', label: '已驳回' },
];

const CATEGORY_OPTIONS: { value: KnowledgeLedgerCategory; label: string }[] = [
  { value: 'project_material', label: '项目原始资料' },
  { value: 'project_wiki_source', label: '项目 Wiki 原始资料' },
  { value: 'meeting_record', label: '会议记录' },
];

const categoryLabel: Record<KnowledgeLedgerCategory, string> = {
  project_material: '项目原始资料',
  project_wiki_source: '项目 Wiki 资料',
  meeting_record: '会议记录',
};

const approvalLabel: Record<KnowledgeApprovalStatus, string> = {
  raw_uploaded: '未生成草稿',
  pending_review: '待审批',
  approved: '已审批入库',
  rejected: '已驳回',
};

const approvalTone: Record<KnowledgeApprovalStatus, string> = {
  raw_uploaded: 'border-[#8b99ae]/25 bg-[#8b99ae]/12 text-[#5e6b80]',
  pending_review: 'border-[#f0a23a]/25 bg-[#f0a23a]/15 text-[#9a5a0d]',
  approved: 'border-[#17a58a]/25 bg-[#17a58a]/12 text-[#137f6d]',
  rejected: 'border-[#df5a67]/25 bg-[#df5a67]/12 text-[#b83d49]',
};

function fmtTime(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export default function KnowledgePage() {
  const router = useRouter();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState('');
  const [category, setCategory] = useState<KnowledgeLedgerCategory>('project_material');
  const [uploaderUserId, setUploaderUserId] = useState('');
  const [approvalStatus, setApprovalStatus] = useState('');
  const [uploadedFrom, setUploadedFrom] = useState('');
  const [uploadedTo, setUploadedTo] = useState('');
  const [reviewedFrom, setReviewedFrom] = useState('');
  const [reviewedTo, setReviewedTo] = useState('');
  const [ledger, setLedger] = useState<KnowledgeLedger | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingLedger, setLoadingLedger] = useState(false);
  const [busyAssetId, setBusyAssetId] = useState<string | null>(null);
  const [actionAsset, setActionAsset] = useState<KnowledgeLedgerDocument | null>(null);
  const [actionMode, setActionMode] = useState<'rename' | 'move' | null>(null);
  const [actionName, setActionName] = useState('');
  const [targetProjectId, setTargetProjectId] = useState('');
  const [preview, setPreview] = useState<KnowledgeAssetPreview | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: 'info' | 'error' } | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === projectId) || null,
    [projectId, projects],
  );

  const uploaderOptions = useMemo(
    () => [
      { value: '', label: '全部成员' },
      ...(ledger?.uploaders || []).map((user) => ({
        value: user.user_id,
        label: user.email,
      })),
    ],
    [ledger],
  );

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [departmentRows, projectRows] = await Promise.all([
          listProjectMemoryDepartments(true),
          listProjectCatalog(),
        ]);
        setDepartments(departmentRows);
        setProjects(projectRows);
        const queryProjectId =
          typeof window !== 'undefined'
            ? new URLSearchParams(window.location.search).get('project_id')
            : null;
        const queryProject = queryProjectId
          ? projectRows.find((project) => project.id === queryProjectId)
          : null;
        const initialProject = queryProject || projectRows[0];
        if (initialProject) setProjectId(initialProject.id);
      } catch (e: any) {
        setToast({ msg: e?.message || '加载知识库台账失败', kind: 'error' });
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!projectId) {
      setLedger(null);
      return;
    }
    let active = true;
    setLoadingLedger(true);
    listKnowledgeLedger({
      projectId,
      category,
      uploaderUserId: uploaderUserId || undefined,
      approvalStatus: (approvalStatus || undefined) as KnowledgeApprovalStatus | undefined,
      uploadedFrom: uploadedFrom || undefined,
      uploadedTo: uploadedTo || undefined,
      reviewedFrom: reviewedFrom || undefined,
      reviewedTo: reviewedTo || undefined,
    })
      .then((data) => {
        if (!active) return;
        setLedger(data);
      })
      .catch((e: any) => {
        if (!active) return;
        if (e instanceof ApiError && e.status === 403) {
          setLedger(null);
          setToast({ msg: '你不是这个项目的成员，无法查看资料台账', kind: 'error' });
        } else {
          setToast({ msg: e?.message || '加载资料台账失败', kind: 'error' });
        }
      })
      .finally(() => {
        if (active) setLoadingLedger(false);
      });
    return () => {
      active = false;
    };
  }, [approvalStatus, category, projectId, reviewedFrom, reviewedTo, uploadedFrom, uploadedTo, uploaderUserId]);

  function handleProjectChange(value: string) {
    setProjectId(value);
    setUploaderUserId('');
    setApprovalStatus('');
    setLedger(null);
  }

  function openReview() {
    if (!projectId) return;
    router.push(`/admin?project_id=${encodeURIComponent(projectId)}`);
  }

  async function reloadLedger() {
    const data = await listKnowledgeLedger({
      projectId,
      category,
      uploaderUserId: uploaderUserId || undefined,
      approvalStatus: (approvalStatus || undefined) as KnowledgeApprovalStatus | undefined,
      uploadedFrom: uploadedFrom || undefined,
      uploadedTo: uploadedTo || undefined,
      reviewedFrom: reviewedFrom || undefined,
      reviewedTo: reviewedTo || undefined,
    });
    setLedger(data);
  }

  async function handleDeleteDocument(document: KnowledgeLedgerDocument) {
    const name = document.display_name || document.filename;
    if (!window.confirm(`确定删除资料「${name}」吗？删除后将从知识库台账和检索库中移除。`)) {
      return;
    }
    setBusyAssetId(document.asset_id);
    try {
      await deleteKnowledgeAsset(document.asset_type, document.asset_id);
      await reloadLedger();
      setToast({ msg: '资料已删除', kind: 'info' });
    } catch (e: any) {
      setToast({ msg: e?.message || '删除资料失败', kind: 'error' });
    } finally {
      setBusyAssetId(null);
    }
  }

  async function handlePreview(document: KnowledgeLedgerDocument) {
    setBusyAssetId(document.asset_id);
    try {
      setPreview(await previewKnowledgeAsset(document.asset_type, document.asset_id));
    } catch (e: any) {
      setToast({ msg: e?.message || '预览资料失败', kind: 'error' });
    } finally {
      setBusyAssetId(null);
    }
  }

  function openRename(document: KnowledgeLedgerDocument) {
    setActionAsset(document);
    setActionMode('rename');
    setActionName(document.display_name || document.filename);
  }

  function openMove(document: KnowledgeLedgerDocument) {
    setActionAsset(document);
    setActionMode('move');
    setTargetProjectId(projects.find((project) => project.id !== projectId)?.id || '');
  }

  async function submitAssetAction() {
    if (!actionAsset || !actionMode) return;
    setBusyAssetId(actionAsset.asset_id);
    try {
      if (actionMode === 'rename') {
        await renameKnowledgeAsset(actionAsset.asset_type, actionAsset.asset_id, actionName.trim());
        setToast({ msg: '资料已重命名', kind: 'info' });
      } else {
        await moveKnowledgeAsset(actionAsset.asset_type, actionAsset.asset_id, targetProjectId);
        setToast({ msg: '资料已迁移到目标项目', kind: 'info' });
      }
      setActionAsset(null);
      setActionMode(null);
      await reloadLedger();
    } catch (e: any) {
      setToast({ msg: e?.message || '资料操作失败', kind: 'error' });
    } finally {
      setBusyAssetId(null);
    }
  }

  return (
    <div className="flex h-screen min-w-0 flex-col bg-[#eef3f9] text-[#10213e]">
      <header className="sticky top-0 z-10 border-b border-[#d7e0ec] bg-white/95 px-4 py-4 backdrop-blur md:px-6">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-3">
          <div>
            <div className="text-[12px] font-bold tracking-[0.04em] text-brand-600">KNOWLEDGE LEDGER</div>
            <h1 className="mt-1 text-[26px] font-semibold leading-tight tracking-normal text-[#10213e]">知识库</h1>
            <p className="mt-1 text-sm leading-6 text-[#6e7d97]">
              统一查看项目原始资料、项目 Wiki 和会议记录，并按权限预览、下载与管理。
            </p>
          </div>
          <div className="flex-1" />
          {ledger?.permissions.can_review && (
            <Button type="button" variant="secondary" onClick={openReview}>
              <ExternalLink size={16} aria-hidden={true} />
              去审批
            </Button>
          )}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6 md:px-6">
        <div className="mx-auto grid max-w-[1320px] gap-5">
          <section className="rounded-lg border border-[#d7e0ec] bg-white p-4 shadow-[0_10px_24px_rgba(15,35,66,0.04)] md:p-5">
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-4 xl:grid-cols-8">
              <Filter label="资料分类">
                <Select
                  value={category}
                  onChange={(value) => {
                    setCategory(value as KnowledgeLedgerCategory);
                    setUploaderUserId('');
                    setApprovalStatus('');
                    setReviewedFrom('');
                    setReviewedTo('');
                  }}
                  options={CATEGORY_OPTIONS}
                />
              </Filter>
              <ProjectHierarchySelector
                departments={departments}
                projects={projects}
                projectId={projectId}
                onProjectChange={handleProjectChange}
                loading={loading}
                showEnvironment
                className="lg:col-span-3 xl:col-span-3"
              />
              <Filter label="上传成员">
                <Select
                  value={uploaderUserId}
                  onChange={setUploaderUserId}
                  placeholder="全部成员"
                  options={uploaderOptions}
                  disabled={!projectId || loadingLedger}
                />
              </Filter>
              {category !== 'project_wiki_source' && (
                <Filter label="审批状态">
                  <Select
                    value={approvalStatus}
                    onChange={setApprovalStatus}
                    placeholder="全部状态"
                    options={APPROVAL_OPTIONS}
                    disabled={!projectId || loadingLedger}
                  />
                </Filter>
              )}
              <Filter label="上传开始">
                <Input type="date" value={uploadedFrom} onChange={(event) => setUploadedFrom(event.target.value)} />
              </Filter>
              <Filter label="上传结束">
                <Input type="date" value={uploadedTo} onChange={(event) => setUploadedTo(event.target.value)} />
              </Filter>
              {category !== 'project_wiki_source' && ledger?.permissions.can_review && (
                <>
                  <Filter label="审批开始">
                    <Input type="date" value={reviewedFrom} onChange={(event) => setReviewedFrom(event.target.value)} />
                  </Filter>
                  <Filter label="审批结束">
                    <Input type="date" value={reviewedTo} onChange={(event) => setReviewedTo(event.target.value)} />
                  </Filter>
                </>
              )}
            </div>
          </section>

          {selectedProject && ledger ? (
            <section className="rounded-lg border border-[#1f365b] bg-[#10213e] p-5 text-[#f7fbff] shadow-[0_24px_64px_rgba(15,35,66,0.08)] md:p-6">
              <div className="flex flex-wrap items-start gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white/10 text-[#18b7d6] ring-1 ring-white/10">
                  <FolderKanban size={20} aria-hidden={true} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[12px] font-bold tracking-[0.04em] text-[#c7d2e1]">PROJECT MATERIAL PROFILE</div>
                  <h2 className="mt-1 break-words text-xl font-semibold leading-tight">{ledger.project.name}</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-[#c7d2e1]">
                    <Users size={15} aria-hidden={true} />
                    <span>项目负责人：</span>
                    {ledger.leaders.length === 0 ? (
                      <span>未设置</span>
                    ) : (
                      ledger.leaders.map((leader) => (
                        <span key={leader.user_id} className="rounded-full bg-white/10 px-2.5 py-1 text-xs text-white">
                          {leader.email}
                        </span>
                      ))
                    )}
                  </div>
                </div>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
                <Metric title="原始资料" value={`${ledger.summary.raw_document_count}`} />
                <Metric title="已入库" value={`${ledger.summary.approved_count}`} />
                <Metric title="待审批" value={`${ledger.summary.pending_count}`} />
                <Metric title="已驳回" value={`${ledger.summary.rejected_count}`} />
                <Metric title="最近上传" value={fmtTime(ledger.summary.latest_uploaded_at)} />
                <Metric title="最近审批" value={fmtTime(ledger.summary.latest_reviewed_at)} />
              </div>
            </section>
          ) : null}

          <section className="overflow-hidden rounded-lg border border-[#d7e0ec] bg-white shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
            <div className="flex flex-wrap items-center gap-3 border-b border-[#d7e0ec] bg-[#f7faff] px-5 py-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-[#10213e]">
                <ClipboardCheck size={18} className="text-brand-600" aria-hidden={true} />
                {categoryLabel[category]}
              </div>
              <div className="flex-1" />
              <span className="rounded-full border border-brand-500/20 bg-brand-500/10 px-3 py-1 text-xs font-medium text-brand-700">
                {ledger?.documents.length || 0} 份资料
              </span>
            </div>

            {loading || loadingLedger ? (
              <div className="py-16 text-center text-[#8b99ae]">
                <LoadingDots />
              </div>
            ) : !projectId ? (
              <EmptyState title="请选择项目" hint="先选择部门和项目后查看资料台账" />
            ) : !ledger || ledger.documents.length === 0 ? (
              <EmptyState
                 title={`暂无${categoryLabel[category]}`}
                 hint={category === 'meeting_record' ? '审批通过的会议记录会在这里显示' : '资料生成或审批入库后会在这里形成台账'}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-[1080px] w-full border-collapse text-sm">
                  <thead className="bg-[#f7f9fc] text-left text-xs font-semibold text-[#6e7d97]">
                    <tr>
                      <th className="px-5 py-3">文件名</th>
                      <th className="px-4 py-3">类型</th>
                      <th className="px-4 py-3">上传成员</th>
                      <th className="px-4 py-3">上传时间</th>
                      <th className="px-4 py-3">审批状态</th>
                      <th className="px-4 py-3">审批人</th>
                      <th className="px-4 py-3">审批时间</th>
                      <th className="px-4 py-3">项目记忆</th>
                      <th className="px-5 py-3 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#d7e0ec]">
                    {ledger.documents.map((document) => (
                      <LedgerRow
                        key={document.asset_id}
                        document={document}
                        canReview={ledger.permissions.can_review}
                        canManage={ledger.permissions.can_manage}
                        canDelete={ledger.permissions.can_delete}
                        busy={busyAssetId === document.asset_id}
                        onDelete={() => handleDeleteDocument(document)}
                        onReview={openReview}
                        onPreview={() => void handlePreview(document)}
                        onRename={() => openRename(document)}
                        onMove={() => openMove(document)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </main>

      {actionAsset && actionMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#10213e]/55 p-4 backdrop-blur-[2px]">
          <section role="dialog" aria-modal="true" aria-labelledby="knowledge-action-title" className="w-full max-w-lg rounded-xl bg-white p-5 shadow-2xl">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <h2 id="knowledge-action-title" className="text-lg font-semibold text-[#10213e]">
                  {actionMode === 'rename' ? '重命名资料' : '迁移到其他项目'}
                </h2>
                <p className="mt-1 break-words text-sm text-[#6e7d97]">{actionAsset.display_name || actionAsset.filename}</p>
              </div>
              <button type="button" aria-label="关闭资料操作" onClick={() => { setActionAsset(null); setActionMode(null); }} className="rounded-md p-2 text-[#6e7d97] hover:bg-[#f2f5f9]"><X size={18} /></button>
            </div>
            <div className="mt-5">
              {actionMode === 'rename' ? (
                <Filter label="新名称"><Input value={actionName} onChange={(event) => setActionName(event.target.value)} autoFocus /></Filter>
              ) : (
                <Filter label="目标项目">
                  <Select
                    value={targetProjectId}
                    onChange={setTargetProjectId}
                    options={projects.filter((project) => project.id !== projectId).map((project) => ({ value: project.id, label: project.name }))}
                  />
                </Filter>
              )}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => { setActionAsset(null); setActionMode(null); }}>取消</Button>
              <Button type="button" disabled={busyAssetId === actionAsset.asset_id || (actionMode === 'rename' ? !actionName.trim() : !targetProjectId)} onClick={() => void submitAssetAction()}>
                {busyAssetId === actionAsset.asset_id ? '处理中…' : '确认'}
              </Button>
            </div>
          </section>
        </div>
      )}

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#10213e]/55 p-3 backdrop-blur-[2px] sm:p-6">
          <section role="dialog" aria-modal="true" aria-labelledby="knowledge-preview-title" className="flex max-h-[calc(100vh-2rem)] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
            <header className="flex items-start gap-3 border-b border-[#d7e0ec] px-5 py-4">
              <div className="min-w-0 flex-1"><h2 id="knowledge-preview-title" className="break-words text-lg font-semibold text-[#10213e]">{preview.name}</h2><p className="mt-1 text-xs text-[#6e7d97]">简单预览 · {preview.format}</p></div>
              <button type="button" aria-label="关闭资料预览" onClick={() => setPreview(null)} className="rounded-md p-2 text-[#6e7d97] hover:bg-[#f2f5f9]"><X size={18} /></button>
            </header>
            <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words bg-[#fbfcfe] p-5 font-sans text-sm leading-7 text-[#243a57]">{preview.content || '该资料暂无可预览文本，请下载原文件查看。'}</pre>
          </section>
        </div>
      )}

      {toast && <Toast message={toast.msg} kind={toast.kind} />}
    </div>
  );
}

function Filter({ label, className = '', children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">{label}</span>
      {children}
    </label>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.06] p-3">
      <div className="text-xs text-[#c7d2e1]">{title}</div>
      <div className="mt-1 break-words text-base font-semibold text-white">{value}</div>
    </div>
  );
}

function LedgerRow({
  document,
  canReview,
  canManage,
  canDelete,
  busy,
  onDelete,
  onReview,
  onPreview,
  onRename,
  onMove,
}: {
  document: KnowledgeLedgerDocument;
  canReview: boolean;
  canManage: boolean;
  canDelete: boolean;
  busy: boolean;
  onDelete: () => void;
  onReview: () => void;
  onPreview: () => void;
  onRename: () => void;
  onMove: () => void;
}) {
  return (
    <tr className="align-top hover:bg-[#f7faff]">
      <td className="px-5 py-4">
        <div className="flex items-start gap-2">
          <FileText size={17} className="mt-0.5 shrink-0 text-brand-600" aria-hidden={true} />
          <div className="min-w-0">
            <div className="break-words font-medium text-[#10213e]">{document.display_name || document.filename}</div>
            <div className="mt-1 text-xs text-[#8b99ae]">
              {fmtSize(document.size_bytes)} · {document.chunk_count} 段
            </div>
            {document.meeting_date && <div className="mt-1 text-xs text-[#8b99ae]">会议日期：{document.meeting_date}</div>}
            {document.error_message && (
              <div className="mt-1 text-xs text-[#b83d49]">{document.error_message}</div>
            )}
          </div>
        </div>
      </td>
      <td className="px-4 py-4 text-[#253655]">{document.format}</td>
      <td className="px-4 py-4 text-[#253655]">{document.uploaded_by?.email || '-'}</td>
      <td className="px-4 py-4 text-[#6e7d97]">{fmtTime(document.uploaded_at)}</td>
      <td className="px-4 py-4">
        <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${approvalTone[document.approval_status]}`}>
          {approvalLabel[document.approval_status]}
        </span>
      </td>
      <td className="px-4 py-4 text-[#253655]">{document.reviewed_by?.email || '-'}</td>
      <td className="px-4 py-4 text-[#6e7d97]">{fmtTime(document.reviewed_at)}</td>
      <td className="px-4 py-4 text-[#253655]">
        {document.approved_memory_document_id ? '已形成项目记忆' : '-'}
      </td>
        <td className="px-5 py-4 text-right">
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={onPreview}>
              <Eye size={14} aria-hidden={true} />预览
            </Button>
            <a href={knowledgeAssetDownloadUrl(document.asset_type, document.asset_id)} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#d7e0ec] bg-white px-3 text-xs font-medium text-[#355170] hover:bg-[#f7f9fc]">
              <Download size={14} aria-hidden={true} />下载
            </a>
            {canManage && (
              <>
                <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={onRename}><Pencil size={14} />重命名</Button>
                <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={onMove}><MoveRight size={14} />迁移</Button>
              </>
            )}
          {canDelete && (
              <Button
                type="button"
                size="sm"
                variant="danger"
                aria-label={`删除资料 ${document.display_name || document.filename}`}
                title="删除资料"
                disabled={busy}
                onClick={onDelete}
              >
                <Trash2 size={15} aria-hidden={true} />
                {busy ? '处理中' : '删除'}
              </Button>
          )}
          {canReview && document.approval_status === 'pending_review' ? (
            <Button type="button" size="sm" variant="secondary" onClick={onReview}>
              去审批
            </Button>
          ) : null}
          </div>
        </td>
    </tr>
  );
}
