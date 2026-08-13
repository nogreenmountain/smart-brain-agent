'use client';

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  Download,
  FileCheck2,
  FileText,
  FileUp,
  FolderUp,
  GitBranch,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UsersRound,
} from 'lucide-react';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { LoadingDots, Toast } from '@/components/Feedback';
import { Input } from '@/components/Input';
import { PageBody, PageHeader, PageShell } from '@/components/PageLayout';
import { ProjectHierarchySelector } from '@/components/ProjectHierarchySelector';
import {
  cancelMaterialIntake,
  confirmMaterialIntake,
  createMeetingSummary,
  getProjectRepository,
  listMeetingParticipantOptions,
  listMeetingSummaries,
  listProjectCatalog,
  listProjectMemoryDepartments,
  meetingSummaryFileUrl,
  previewProjectMaterials,
  upsertProjectRepository,
  type Department,
  type MaterialIntakePreview,
  type MeetingParticipantOption,
  type MeetingSummary,
  type Project,
} from '@/lib/api';

type UploadTab = 'materials' | 'meetings' | 'repository';

const tabs: { id: UploadTab; label: string; icon: typeof FolderUp; description: string }[] = [
  { id: 'materials', label: '项目原始资料', icon: FolderUp, description: '先检查敏感信息，再提交安全文件进入知识库审批流程。' },
  { id: 'meetings', label: '会议记录', icon: ClipboardList, description: '上传会议全文，并查看项目内已有的长期会议记录。' },
  { id: 'repository', label: 'GitHub 仓库', icon: GitBranch, description: '维护新成员和 AI 理解项目时使用的代码仓库入口。' },
];

const materialRecommendationLabel = {
  keep: '通过检查',
  review: '风险待确认',
  duplicate: '重复资料',
  sensitive: '包含敏感信息',
  low_value: '未通过检查',
} as const;

const materialRecommendationTone = {
  keep: 'border-[#17a58a]/25 bg-[#17a58a]/12 text-[#137f6d]',
  review: 'border-[#f0a23a]/25 bg-[#f0a23a]/15 text-[#9a5a0d]',
  duplicate: 'border-[#a8b4c6]/30 bg-[#eef2f7] text-[#5e6b80]',
  sensitive: 'border-[#df5a67]/25 bg-[#df5a67]/10 text-[#b83d49]',
  low_value: 'border-[#a8b4c6]/30 bg-[#eef2f7] text-[#5e6b80]',
} as const;

const MATERIAL_ACCEPT = '.pdf,.doc,.docx,.ppt,.pptx,.md,.markdown,.html,.htm,.txt,.py,.ts,.tsx,.js,.jsx,.json,.yaml,.yml,.css,.scss,.java,.go,.rs,.cpp,.c,.h,.cs,.sql';
const MEETING_FILE_ACCEPT = '.pdf,.docx,.pptx,.md,.txt,.html,.htm,.csv,.json,.xml,.yaml,.yml';

export default function UploadsWorkspace({ initialTab = 'materials' }: { initialTab?: UploadTab }) {
  const materialFileRef = useRef<HTMLInputElement>(null);
  const [activeTab, setActiveTab] = useState<UploadTab>(initialTab);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState('');
  const [loading, setLoading] = useState(true);
  const [repoUrl, setRepoUrl] = useState('');
  const [repoBranch, setRepoBranch] = useState('main');
  const [repoLoading, setRepoLoading] = useState(false);
  const [savingRepo, setSavingRepo] = useState(false);
  const [selectedMaterialFiles, setSelectedMaterialFiles] = useState<File[]>([]);
  const [uploadingMaterials, setUploadingMaterials] = useState(false);
  const [confirmingMaterials, setConfirmingMaterials] = useState(false);
  const [materialPreview, setMaterialPreview] = useState<MaterialIntakePreview | null>(null);
  const [materialScanOpen, setMaterialScanOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; kind: 'info' | 'error' } | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === projectId) || null,
    [projectId, projects],
  );
  const selectedProjectIsMember = Boolean(selectedProject?.role);

  useEffect(() => {
    let active = true;
    Promise.all([listProjectMemoryDepartments(true), listProjectCatalog()])
      .then(([departmentRows, projectRows]) => {
        if (!active) return;
        setDepartments(departmentRows);
        setProjects(projectRows);
        setProjectId(projectRows[0]?.id || '');
      })
      .catch((error: unknown) => {
        if (active) setToast({ msg: error instanceof Error ? error.message : '项目加载失败', kind: 'error' });
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    setSelectedMaterialFiles([]);
    setMaterialPreview(null);
    setMaterialScanOpen(false);
    if (materialFileRef.current) materialFileRef.current.value = '';
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !selectedProjectIsMember) {
      setRepoUrl('');
      setRepoBranch('main');
      return;
    }
    let active = true;
    setRepoLoading(true);
    getProjectRepository(projectId)
      .then((repository) => {
        if (!active) return;
        setRepoUrl(repository?.git_url || '');
        setRepoBranch(repository?.git_branch || 'main');
      })
      .catch((error: unknown) => {
        if (active) setToast({ msg: error instanceof Error ? error.message : '仓库配置加载失败', kind: 'error' });
      })
      .finally(() => {
        if (active) setRepoLoading(false);
      });
    return () => { active = false; };
  }, [projectId, selectedProjectIsMember]);

  async function inspectMaterials() {
    if (!selectedProjectIsMember || !selectedProject?.department_id || selectedMaterialFiles.length === 0 || uploadingMaterials) return;
    setMaterialScanOpen(true);
    setMaterialPreview(null);
    setUploadingMaterials(true);
    try {
      setMaterialPreview(await previewProjectMaterials(
        selectedProject.id,
        selectedProject.department_id,
        selectedMaterialFiles,
      ));
    } catch (error: unknown) {
      setMaterialScanOpen(false);
      setToast({ msg: error instanceof Error ? error.message : '资料检查失败', kind: 'error' });
    } finally {
      setUploadingMaterials(false);
    }
  }

  async function confirmMaterials() {
    if (!materialPreview || confirmingMaterials) return;
    const safeFileIds = materialPreview.items
      .filter((item) => item.recommendation === 'keep' && item.included)
      .map((item) => item.id);
    if (safeFileIds.length === 0) return;
    setConfirmingMaterials(true);
    try {
      const result = await confirmMaterialIntake(materialPreview.id, safeFileIds);
      clearMaterialSelection();
      setToast({ msg: `已提交 ${result.raw_document_count} 份原始资料，等待管理员审批后入库`, kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '提交资料失败', kind: 'error' });
    } finally {
      setConfirmingMaterials(false);
    }
  }

  async function cancelMaterials() {
    if (uploadingMaterials || confirmingMaterials) return;
    try {
      if (materialPreview) await cancelMaterialIntake(materialPreview.id);
      clearMaterialSelection();
      setToast({ msg: '本批文件已全部取消，不会上传', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '取消上传失败', kind: 'error' });
    }
  }

  function clearMaterialSelection() {
    setSelectedMaterialFiles([]);
    setMaterialPreview(null);
    setMaterialScanOpen(false);
    if (materialFileRef.current) materialFileRef.current.value = '';
  }

  async function saveRepository(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !repoUrl.trim() || savingRepo) return;
    setSavingRepo(true);
    try {
      await upsertProjectRepository(projectId, {
        git_url: repoUrl.trim(),
        git_branch: repoBranch.trim() || 'main',
      });
      setToast({ msg: '仓库地址已保存', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '保存仓库失败', kind: 'error' });
    } finally {
      setSavingRepo(false);
    }
  }

  const activeTabInfo = tabs.find((tab) => tab.id === activeTab) || tabs[0];

  return (
    <PageShell>
      <PageHeader
        eyebrow="PROJECT MATERIALS"
        icon={FolderUp}
        title="上传资料"
        description="在一个工作区内维护项目原始资料、会议记录和 GitHub 仓库，项目选择会在三个功能间保持一致。"
      />
      <PageBody contentClassName="space-y-5">
        <Card className="p-4 md:p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
              <activeTabInfo.icon size={19} aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <div role="tablist" aria-label="资料类型" className="grid gap-2 sm:grid-cols-3">
                {tabs.map((tab) => {
                  const Icon = tab.icon;
                  const selected = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={selected}
                      onClick={() => setActiveTab(tab.id)}
                      className={`inline-flex min-w-0 items-center justify-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-semibold transition-colors ${
                        selected
                          ? 'border-brand-500/30 bg-brand-500/10 text-brand-700'
                          : 'border-[#d7e0ec] bg-white text-[#50627b] hover:bg-[#f7faff]'
                      }`}
                    >
                      <Icon size={16} aria-hidden="true" />{tab.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-3 text-sm leading-6 text-[#6e7d97]">{activeTabInfo.description}</p>
            </div>
          </div>
          <div className="mt-4 border-t border-[#e5ebf3] pt-4">
            <ProjectHierarchySelector
              departments={departments}
              projects={projects}
              projectId={projectId}
              onProjectChange={setProjectId}
              loading={loading}
              showEnvironment
            />
          </div>
        </Card>

        {activeTab === 'materials' && (
          <Card className="p-5 md:p-6">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#17a58a]/10 text-[#137f6d]">
                <FileCheck2 size={20} aria-hidden="true" />
              </div>
              <div>
                <h2 className="text-xl font-semibold text-[#10213e]">项目原始资料</h2>
                <p className="mt-1 text-sm leading-6 text-[#6e7d97]">文件会先进行凭据、Token、个人信息和敏感链接检查，通过后才可提交。</p>
              </div>
            </div>
            <label className="mt-5 block text-sm font-medium text-[#253655]">
              项目原始资料
              <Input
                ref={materialFileRef}
                aria-label="项目原始资料"
                type="file"
                multiple
                accept={MATERIAL_ACCEPT}
                disabled={!selectedProjectIsMember}
                onChange={(event) => {
                  setSelectedMaterialFiles(Array.from(event.target.files || []));
                  setMaterialPreview(null);
                  setMaterialScanOpen(false);
                }}
                className="mt-1.5"
              />
            </label>
            {!selectedProjectIsMember && (
              <p className="mt-3 rounded-lg border border-[#f0a23a]/25 bg-[#fff8ec] px-3 py-2 text-sm text-[#8a5a18]">
                原始资料和仓库配置仅对项目成员开放。
              </p>
            )}
            <div className="mt-4 flex flex-col gap-3 rounded-lg border border-[#d7e0ec] bg-[#f7faff] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="text-sm font-medium text-[#253655]">已选择 {selectedMaterialFiles.length} 个文件</div>
                <div className="mt-1 text-xs leading-5 text-[#6e7d97]">分类信息将以所选项目当前归属为准，无需手动填写。</div>
              </div>
              <Button
                type="button"
                className="w-full sm:w-auto"
                disabled={!selectedProjectIsMember || selectedMaterialFiles.length === 0 || uploadingMaterials}
                onClick={inspectMaterials}
              >
                {uploadingMaterials ? <LoadingDots /> : <><Sparkles size={16} aria-hidden="true" />检查并预览</>}
              </Button>
            </div>
          </Card>
        )}

        {activeTab === 'meetings' && (
          <Card className="overflow-hidden">
            <div className="border-b border-[#d7e0ec] bg-[#f7faff] px-5 py-4">
              <h2 className="text-xl font-semibold text-[#10213e]">会议记录</h2>
              <p className="mt-1 text-sm text-[#6e7d97]">会议上传仍保留跨项目搜索能力；历史查看和下载继续按项目成员权限控制。</p>
            </div>
            <div className="p-4 md:p-5">
              <MeetingPanel
                departments={departments}
                projects={projects}
                projectId={projectId}
                onProjectChange={setProjectId}
              />
            </div>
          </Card>
        )}

        {activeTab === 'repository' && (
          <Card className="p-5 md:p-6">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                <GitBranch size={20} aria-hidden="true" />
              </div>
              <div>
                <h2 className="text-xl font-semibold text-[#10213e]">GitHub 仓库</h2>
                <p className="mt-1 text-sm leading-6 text-[#6e7d97]">为当前项目维护仓库地址和默认分支。</p>
              </div>
            </div>
            <form onSubmit={saveRepository} className="mt-5 grid min-w-0 gap-4 md:grid-cols-[minmax(0,1fr)_minmax(160px,0.32fr)]">
              <label className="min-w-0 text-sm font-medium text-[#253655]">
                GitHub 仓库地址
                <Input
                  aria-label="GitHub 仓库地址"
                  value={repoUrl}
                  disabled={!selectedProjectIsMember || repoLoading || savingRepo}
                  onChange={(event) => setRepoUrl(event.target.value)}
                  placeholder="https://github.com/org/repo.git"
                  className="mt-1.5"
                />
              </label>
              <label className="min-w-0 text-sm font-medium text-[#253655]">
                默认分支
                <Input
                  aria-label="默认分支"
                  value={repoBranch}
                  disabled={!selectedProjectIsMember || repoLoading || savingRepo}
                  onChange={(event) => setRepoBranch(event.target.value)}
                  placeholder="main"
                  className="mt-1.5"
                />
              </label>
              <div className="md:col-span-2 flex justify-end">
                <Button type="submit" className="w-full sm:w-auto" disabled={!selectedProjectIsMember || !repoUrl.trim() || repoLoading || savingRepo}>
                  {savingRepo ? <LoadingDots /> : '保存仓库'}
                </Button>
              </div>
            </form>
            {!selectedProjectIsMember && (
              <p className="mt-4 rounded-lg border border-[#f0a23a]/25 bg-[#fff8ec] px-3 py-2 text-sm text-[#8a5a18]">
                原始资料和仓库配置仅对项目成员开放。
              </p>
            )}
          </Card>
        )}
      </PageBody>

      {materialScanOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#10213e]/55 p-3 backdrop-blur-[2px] sm:p-6">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="material-security-dialog-title"
            className="max-h-[calc(100vh-1.5rem)] w-full max-w-3xl overflow-y-auto rounded-xl border border-white/70 bg-white shadow-[0_28px_80px_rgba(15,35,66,0.32)] sm:max-h-[calc(100vh-3rem)]"
          >
            <div className="border-b border-[#d7e0ec] px-5 py-4 sm:px-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 id="material-security-dialog-title" className="text-xl font-semibold text-[#10213e]">文件安全检查</h2>
                  <p className="mt-1 text-sm leading-6 text-[#6e7d97]">确认检查结果后，只会提交明确通过检测的文件。</p>
                </div>
                <ShieldCheck size={22} className="shrink-0 text-[#137f6d]" aria-hidden="true" />
              </div>
            </div>
            <div className="px-5 py-5 sm:px-6">
              {uploadingMaterials && !materialPreview ? (
                <div className="flex min-h-48 flex-col items-center justify-center gap-3 text-sm text-[#6e7d97]"><LoadingDots />正在逐个读取文件并检查敏感信息…</div>
              ) : materialPreview ? (
                <>
                  <p className="text-sm leading-6 text-[#50627b]">{materialPreview.summary}</p>
                  <div className="mt-4 divide-y divide-[#e3e9f1] border-y border-[#e3e9f1]">
                    {materialPreview.items.map((item) => (
                      <div key={item.id} className="flex items-start gap-3 py-3">
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="break-all text-sm font-medium text-[#10213e]">{item.filename}</span>
                            <span className={`rounded border px-2 py-0.5 text-xs font-medium ${materialRecommendationTone[item.recommendation]}`}>
                              {materialRecommendationLabel[item.recommendation]}
                            </span>
                          </span>
                          <span className="mt-1 block text-sm leading-6 text-[#6e7d97]">{item.reason}</span>
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              ) : null}
            </div>
            <div className="flex flex-col-reverse gap-2 border-t border-[#d7e0ec] bg-[#f7faff] px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
              <Button type="button" variant="secondary" disabled={uploadingMaterials || confirmingMaterials || !materialPreview} onClick={cancelMaterials}>
                全部不上传
              </Button>
              <Button
                type="button"
                disabled={uploadingMaterials || confirmingMaterials || !materialPreview?.items.some((item) => item.recommendation === 'keep' && item.included)}
                onClick={confirmMaterials}
              >
                {confirmingMaterials ? <LoadingDots /> : <><CheckCircle2 size={16} aria-hidden="true" />上传通过检测的文件</>}
              </Button>
            </div>
          </section>
        </div>
      )}

      {toast && <Toast message={toast.msg} kind={toast.kind} />}
    </PageShell>
  );
}

function MeetingPanel({
  departments,
  projects,
  projectId,
  onProjectChange,
}: {
  departments: Department[];
  projects: Project[];
  projectId: string;
  onProjectChange: (projectId: string) => void;
}) {
  const [members, setMembers] = useState<MeetingParticipantOption[]>([]);
  const [selectedParticipantIds, setSelectedParticipantIds] = useState<string[]>([]);
  const [memberQuery, setMemberQuery] = useState('');
  const [items, setItems] = useState<MeetingSummary[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [projectQuery, setProjectQuery] = useState('');
  const [query, setQuery] = useState('');
  const [title, setTitle] = useState('');
  const [meetingDate, setMeetingDate] = useState(localDate());
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [membersLoading, setMembersLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const selectedProject = projects.find((project) => project.id === projectId);
  const selected = useMemo(
    () => items.find((item) => item.id === selectedId) ?? items[0] ?? null,
    [items, selectedId],
  );
  const departmentPaths = useMemo(() => new Map(departments.map((department) => {
    const parent = department.parent_id
      ? departments.find((candidate) => candidate.id === department.parent_id)
      : null;
    return [department.id, parent ? `${parent.name} / ${department.name}` : department.name];
  })), [departments]);
  const filteredProjects = useMemo(() => {
    const needle = projectQuery.trim().toLocaleLowerCase();
    if (!needle) return [];
    return projects.filter((project) => (
      `${project.name} ${departmentPaths.get(project.department_id || '') || ''}`
        .toLocaleLowerCase()
        .includes(needle)
    )).slice(0, 20);
  }, [departmentPaths, projectQuery, projects]);
  const filteredMembers = useMemo(() => {
    const needle = memberQuery.trim().toLocaleLowerCase();
    if (!needle) return members;
    return members.filter((member) => (
      `${memberPrimaryName(member)} ${member.nickname || ''} ${member.display_name || ''} ${member.username || ''} ${member.email}`
        .toLocaleLowerCase()
        .includes(needle)
    ));
  }, [memberQuery, members]);

  const loadSummaries = useCallback(async (targetProjectId: string, searchQuery?: string) => {
    if (!targetProjectId) return;
    setLoading(true);
    setError('');
    try {
      const data = await listMeetingSummaries({
        projectId: targetProjectId,
        query: searchQuery?.trim() || undefined,
        limit: 100,
      });
      setItems(data.items);
      setSelectedId(data.items[0]?.id ?? '');
    } catch (requestError) {
      setItems([]);
      setError(requestError instanceof Error ? requestError.message : '会议记录加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    setMembersLoading(true);
    listMeetingParticipantOptions('', 200)
      .then((rows) => {
        if (active) setMembers(rows);
      })
      .catch((requestError: unknown) => {
        if (active) setError(requestError instanceof Error ? requestError.message : '团队成员加载失败');
      })
      .finally(() => {
        if (active) setMembersLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    setSelectedParticipantIds([]);
    setMemberQuery('');
    setNotice('');
    if (!projectId) {
      setItems([]);
      setSelectedId('');
      return;
    }
    if (selectedProject?.role) void loadSummaries(projectId);
    else {
      setItems([]);
      setSelectedId('');
      setLoading(false);
      setError('');
    }
  }, [loadSummaries, projectId, selectedProject?.role]);

  function selectProject(targetProjectId: string) {
    onProjectChange(targetProjectId);
    setProjectQuery('');
  }

  function toggleParticipant(userId: string) {
    setSelectedParticipantIds((current) => (
      current.includes(userId)
        ? current.filter((value) => value !== userId)
        : [...current, userId]
    ));
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !title.trim() || !meetingDate || selectedParticipantIds.length === 0 || !file) {
      setError('请选择项目，填写会议名称和日期，至少勾选一名参会人，并上传会议内容文件。');
      return;
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await createMeetingSummary({
        projectId,
        title: title.trim(),
        meetingDate,
        participantUserIds: selectedParticipantIds,
        file,
      });
      setTitle('');
      setSelectedParticipantIds([]);
      setMemberQuery('');
      setFile(null);
      setFileInputKey((current) => current + 1);
      setNotice('会议记录已保存，会议全文现在可以通过智慧大脑 MCP 检索和读取。');
      if (selectedProject?.role) await loadSummaries(projectId, query);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '会议记录上传失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-lg border border-[#bee2cf] bg-[#f2fbf6] p-4 text-sm leading-6 text-[#50627b]">
        <ShieldCheck size={19} className="mt-0.5 shrink-0 text-[#2c7a59]" aria-hidden="true" />
        <p>所有已启用的智慧大脑用户都可以搜索任意项目并上传会议记录；会议查看和下载仍按项目成员权限控制。</p>
      </div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <Card className="p-4">
            <label className="block text-xs font-medium text-[#50627b]">
              搜索项目
              <input
                aria-label="搜索项目"
                value={projectQuery}
                onChange={(event) => setProjectQuery(event.target.value)}
                className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm"
                placeholder="输入项目名称或分类中的任意文字"
              />
            </label>
            {projectQuery.trim() && (
              <div className="mt-2 max-h-48 space-y-1 overflow-y-auto rounded-md border border-[#d7e0ec] p-1">
                {filteredProjects.length > 0 ? filteredProjects.map((project) => (
                  <button key={project.id} type="button" onClick={() => selectProject(project.id)} className="block w-full rounded px-3 py-2 text-left hover:bg-[#f5f8fc]">
                    <span className="block text-sm font-medium text-[#172844]">{project.name}</span>
                    <span className="block text-xs text-[#6e7d97]">{departmentPaths.get(project.department_id || '') || '未分类'}</span>
                  </button>
                )) : <p className="px-3 py-3 text-center text-xs text-[#6e7d97]">没有匹配的项目</p>}
              </div>
            )}
          </Card>

          {selectedProject && (
            <Card className="p-4">
              <form onSubmit={handleCreate} className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-semibold text-[#172844]"><FileUp size={17} />上传会议记录</div>
                <label className="block text-xs font-medium text-[#50627b]">会议名称<input aria-label="会议标题" value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" placeholder="例如：产品研发周会" /></label>
                <label className="block text-xs font-medium text-[#50627b]">会议日期<input aria-label="会议日期" type="date" value={meetingDate} onChange={(event) => setMeetingDate(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" /></label>
                <fieldset className="rounded-md border border-[#cbd8e8] p-3">
                  <legend className="px-1 text-xs font-medium text-[#50627b]">参会人（全部启用团队成员）</legend>
                  <input aria-label="搜索参会人" value={memberQuery} onChange={(event) => setMemberQuery(event.target.value)} className="h-9 w-full rounded-md border border-[#d7e0ec] px-3 text-sm" placeholder="输入姓名、昵称或账号中的任意一个字" />
                  <div className="mt-2 max-h-52 space-y-1 overflow-y-auto pr-1">
                    {membersLoading ? <p className="py-3 text-center text-xs text-[#6e7d97]">正在加载团队成员…</p> : filteredMembers.length > 0 ? filteredMembers.map((member) => {
                      const primary = memberPrimaryName(member);
                      const account = accountName(member.email);
                      return (
                        <label key={member.user_id} className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-[#f5f8fc]">
                          <input type="checkbox" aria-label={`参会人 ${primary}${member.nickname ? `，账号 ${account}` : ''}`} checked={selectedParticipantIds.includes(member.user_id)} onChange={() => toggleParticipant(member.user_id)} className="h-4 w-4 rounded border-[#9fb1c7] text-brand-600" />
                          <span className="min-w-0 text-sm text-[#172844]"><span className="block truncate font-medium">{primary}</span>{member.nickname && <span className="block truncate text-xs text-[#6e7d97]">账号：{account}</span>}</span>
                        </label>
                      );
                    }) : <p className="py-3 text-center text-xs text-[#6e7d97]">没有匹配的团队成员</p>}
                  </div>
                  <p className="mt-2 text-xs text-[#6e7d97]">已选择 {selectedParticipantIds.length} 人</p>
                </fieldset>
                <label className="block text-xs font-medium text-[#50627b]">
                  上传会议内容文件
                  <input key={fileInputKey} aria-label="上传会议内容文件" type="file" accept={MEETING_FILE_ACCEPT} onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="mt-1 block w-full text-sm text-[#50627b] file:mr-3 file:h-9 file:rounded-md file:border-0 file:bg-[#edf4ff] file:px-3 file:text-[#315f9f]" />
                </label>
                <p className="text-xs leading-5 text-[#6e7d97]">支持 PDF、Word（DOCX）、PowerPoint（PPTX）、Markdown、TXT、HTML 等常用格式，单个文件不超过 20 MB。</p>
                <button type="submit" disabled={saving} className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-brand-600 px-4 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"><FileUp size={16} />{saving ? '正在上传…' : '上传会议记录'}</button>
              </form>
            </Card>
          )}
        </div>

        <div className="min-w-0 space-y-4">
          <form onSubmit={(event) => { event.preventDefault(); if (selectedProject?.role) void loadSummaries(projectId, query); }} className="grid gap-3 rounded-lg border border-[#d7e0ec] bg-white p-4 sm:grid-cols-[minmax(0,1fr)_auto]">
            <label className="text-xs font-medium text-[#50627b]">搜索会议内容<input value={query} onChange={(event) => setQuery(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" placeholder="会议内容、参会人或会议名称…" /></label>
            <button type="submit" disabled={!projectId || !selectedProject?.role || loading} className="inline-flex h-10 items-center justify-center gap-2 self-end rounded-md border border-[#cbd8e8] bg-white px-4 text-sm font-semibold text-[#355170] hover:bg-[#f7f9fc] disabled:opacity-50"><Search size={16} />检索</button>
          </form>
          {selectedProject?.role && (
            <button type="button" onClick={() => void loadSummaries(projectId, query)} disabled={loading} className="inline-flex h-9 items-center gap-2 rounded-md border border-[#cbd8e8] bg-white px-3 text-xs font-medium text-[#355170] hover:bg-[#f7f9fc] disabled:opacity-50"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />刷新会议记录</button>
          )}
          {error && <div className="rounded-lg border border-[#efc9c9] bg-[#fff7f7] px-4 py-3 text-sm text-[#a33a3a]"><TriangleAlert size={16} className="mr-2 inline" />{error}</div>}
          {notice && <div className="rounded-lg border border-[#bee2cf] bg-[#f2fbf6] px-4 py-3 text-sm text-[#28714f]">{notice}</div>}
          {items.length > 0 ? (
            <div className="grid min-w-0 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
              <Card className="max-h-[calc(100vh-300px)] overflow-y-auto">
                <div className="divide-y divide-[#edf1f6]">{items.map((item) => (
                  <button key={item.id} type="button" onClick={() => setSelectedId(item.id)} className={`w-full px-4 py-3 text-left ${selected?.id === item.id ? 'bg-[#edf4ff]' : 'hover:bg-[#f8fafc]'}`}>
                    <div className="truncate text-sm font-semibold text-[#172844]">{item.title}</div>
                    <div className="mt-1 flex items-center gap-1 text-xs text-[#6e7d97]"><CalendarDays size={13} />{item.meeting_date}</div>
                  </button>
                ))}</div>
              </Card>
              {selected && (
                <Card className="min-w-0 overflow-hidden">
                  <header className="border-b border-[#e5ebf3] px-5 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div><h3 className="text-lg font-semibold text-[#172844]">{selected.title}</h3><div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-[#6e7d97]"><span className="inline-flex items-center gap-1"><CalendarDays size={14} />{selected.meeting_date}</span><span className="inline-flex items-center gap-1"><UsersRound size={14} />{selected.participants.join('、') || '未填写参会人'}</span><span>上传人：{selected.created_by_name}</span></div></div>
                      {selected.source_filename && selected.source_format && <a href={meetingSummaryFileUrl(selected.id)} className="inline-flex h-9 items-center gap-2 rounded-md border border-[#cbd8e8] px-3 text-xs font-medium text-[#355170] hover:bg-[#f7f9fc]"><Download size={14} />下载原文件</a>}
                    </div>
                    {selected.source_filename && <div className="mt-3 flex items-center gap-2 text-xs text-[#6e7d97]"><FileText size={14} />{selected.source_filename}{selected.source_size_bytes ? ` · ${formatFileSize(selected.source_size_bytes)}` : ''}</div>}
                  </header>
                  <pre className="max-h-[calc(100vh-380px)] min-h-72 overflow-auto whitespace-pre-wrap break-words bg-[#fbfcfe] px-5 py-5 font-sans text-sm leading-7 text-[#243a57]">{selected.summary_markdown}</pre>
                </Card>
              )}
            </div>
          ) : !loading && projectId && selectedProject?.role ? (
            <Card className="flex min-h-64 flex-col items-center justify-center px-6 text-center"><ClipboardList size={30} className="text-[#8aa0ba]" /><p className="mt-3 text-base font-semibold text-[#253655]">暂无会议记录</p></Card>
          ) : !loading && projectId ? (
            <Card className="flex min-h-64 flex-col items-center justify-center px-6 text-center"><ShieldCheck size={30} className="text-[#8aa0ba]" /><p className="mt-3 text-base font-semibold text-[#253655]">可上传到此项目</p><p className="mt-1 text-sm text-[#6e7d97]">你不是该项目成员，因此不展示已有会议内容。</p></Card>
          ) : <Card className="flex min-h-64 items-center justify-center text-sm text-[#6e7d97]">正在加载会议记录…</Card>}
        </div>
      </div>
    </div>
  );
}

function localDate(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

function accountName(email: string): string {
  return email.split('@')[0] || email;
}

function memberPrimaryName(member: MeetingParticipantOption): string {
  return member.nickname?.trim() || member.display_name?.trim() || member.username || accountName(member.email);
}

function formatFileSize(size: number | null): string {
  if (!size) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}
