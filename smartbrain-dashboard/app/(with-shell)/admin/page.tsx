'use client';

import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Archive,
  CalendarDays,
  CheckCircle2,
  ExternalLink,
  FileText,
  FolderKanban,
  GitBranch,
  PencilLine,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  Upload,
  XCircle,
} from 'lucide-react';

import { Button } from '@/components/Button';
import { EmptyState, LoadingDots, Toast } from '@/components/Feedback';
import { Input, Textarea } from '@/components/Input';
import { Select } from '@/components/Select';
import {
  createProject,
  deleteProject,
  Department,
  DepartmentId,
  getMe,
  getProjectRepository,
  listProjectMemoryDepartments,
  listProjectMemoryDrafts,
  listProjects,
  Me,
  Project,
  ProjectMemoryDraft,
  reviewProjectMemoryDraft,
  updateProject,
  uploadProjectMaterialsBatch,
  upsertProjectRepository,
} from '@/lib/api';

const statusLabel: Record<ProjectMemoryDraft['status'], string> = {
  pending_review: '待审批',
  approved: '已入库',
  rejected: '已驳回',
};

const departmentTone: Record<DepartmentId, string> = {
  research: 'border-brand-500/20 bg-brand-500/10 text-brand-700',
  marketing: 'border-[#f0a23a]/25 bg-[#f0a23a]/15 text-[#9a5a0d]',
  business: 'border-[#17a58a]/25 bg-[#17a58a]/12 text-[#137f6d]',
};

function fmtTime(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

function fmtDate(value?: string | null): string {
  if (!value) return '未设置';
  return new Date(value).toLocaleDateString('zh-CN', { hour12: false });
}

function roleCanCreate(me: Me | null): boolean {
  return Boolean(
    me?.memberships.some((membership) => membership.role === 'owner' || membership.role === 'admin'),
  );
}

function canManageProject(project: Project | null): boolean {
  return project?.role === 'owner' || project?.role === 'admin';
}

function projectRoleLabel(role?: Project['role']): string {
  if (role === 'owner' || role === 'admin') return '项目负责人';
  return '项目成员';
}

export default function AdminPage() {
  const router = useRouter();
  const materialFileRef = useRef<HTMLInputElement>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [departmentId, setDepartmentId] = useState<DepartmentId>('research');
  const [projectId, setProjectId] = useState('');
  const [repoUrl, setRepoUrl] = useState('');
  const [repoBranch, setRepoBranch] = useState('main');
  const [drafts, setDrafts] = useState<ProjectMemoryDraft[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState('');
  const [reviewComment, setReviewComment] = useState('');
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectOrgId, setNewProjectOrgId] = useState('');
  const [newProjectCompletedAt, setNewProjectCompletedAt] = useState('');
  const [editProjectName, setEditProjectName] = useState('');
  const [editCompletedAt, setEditCompletedAt] = useState('');
  const [loading, setLoading] = useState(true);
  const [savingRepo, setSavingRepo] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [updatingProject, setUpdatingProject] = useState(false);
  const [deletingProject, setDeletingProject] = useState(false);
  const [selectedMaterialFiles, setSelectedMaterialFiles] = useState<File[]>([]);
  const [uploadingMaterials, setUploadingMaterials] = useState(false);
  const [toast, setToast] = useState<{ msg: string; kind: 'info' | 'error' } | null>(null);

  const departmentOptions = departments.map((department) => ({
    value: department.id,
    label: department.name,
  }));

  const filteredProjects = useMemo(
    () => projects.filter((project) => (project.department_id || 'research') === departmentId),
    [projects, departmentId],
  );

  const selectedProject = projects.find((project) => project.id === projectId) || null;
  const selectedDepartment = departments.find((department) => department.id === departmentId);
  const selectedProjectCanManage = canManageProject(selectedProject);
  const canManageVisibleProject = filteredProjects.some((project) => canManageProject(project));
  const canCreateProjects = roleCanCreate(me) && (selectedProjectCanManage || canManageVisibleProject || projects.length === 0);
  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId) || drafts[0] || null;
  const approvedDrafts = drafts.filter((draft) => draft.status === 'approved').length;
  const pendingDrafts = drafts.filter((draft) => draft.status === 'pending_review').length;

  const autoOrgName =
    (me?.memberships || []).find((membership) => membership.org_id === newProjectOrgId)?.org_name || '';

  useEffect(() => {
    let active = true;
    Promise.all([getMe(), listProjectMemoryDepartments(), listProjects()])
      .then(([meResult, departmentRows, projectRows]) => {
        if (!active) return;
        setMe(meResult);
        setDepartments(departmentRows);
        setProjects(projectRows);
        const firstDepartment = departmentRows[0]?.id || 'research';
        setDepartmentId(firstDepartment);
        const firstProject =
          projectRows.find((project) => (project.department_id || 'research') === firstDepartment) ||
          projectRows[0];
        if (firstProject) setProjectId(firstProject.id);
        const firstAdminOrg = meResult.memberships.find(
          (membership) => membership.role === 'owner' || membership.role === 'admin',
        );
        if (firstAdminOrg) setNewProjectOrgId(firstAdminOrg.org_id);
      })
      .catch((error: unknown) => {
        setToast({ msg: error instanceof Error ? error.message : '加载项目管理失败', kind: 'error' });
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const next = filteredProjects[0]?.id || '';
    if (!filteredProjects.some((project) => project.id === projectId)) {
      setProjectId(next);
    }
  }, [departmentId, filteredProjects, projectId]);

  useEffect(() => {
    if (!selectedProject) {
      setEditProjectName('');
      setEditCompletedAt('');
      setRepoUrl('');
      setRepoBranch('main');
      setDrafts([]);
      setSelectedDraftId('');
      setSelectedMaterialFiles([]);
      return;
    }
    setEditProjectName(selectedProject.name);
    setEditCompletedAt(selectedProject.completed_at ? selectedProject.completed_at.slice(0, 10) : '');
    setSelectedMaterialFiles([]);
    if (materialFileRef.current) materialFileRef.current.value = '';
    void loadProjectMemory(selectedProject.id, canManageProject(selectedProject));
  }, [selectedProject]);

  async function refreshProjects(selectId?: string) {
    const rows = await listProjects();
    setProjects(rows);
    if (selectId) setProjectId(selectId);
  }

  async function loadProjectMemory(pid: string, includeDrafts = true) {
    try {
      const repository = await getProjectRepository(pid);
      setRepoUrl(repository?.git_url || '');
      setRepoBranch(repository?.git_branch || 'main');
      if (!includeDrafts) {
        setDrafts([]);
        setSelectedDraftId('');
        return;
      }
      const draftRows = await listProjectMemoryDrafts(pid);
      setDrafts(draftRows);
      setSelectedDraftId(draftRows[0]?.id || '');
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '加载项目记忆数据失败', kind: 'error' });
    }
  }

  async function handleCreateProject(event: FormEvent) {
    event.preventDefault();
    if (!newProjectOrgId || !newProjectName.trim() || creatingProject) return;
    setCreatingProject(true);
    try {
      const project = await createProject({
        org_id: newProjectOrgId,
        name: newProjectName.trim(),
        environment: 'development',
        department_id: departmentId,
        completed_at: newProjectCompletedAt || null,
      });
      setNewProjectName('');
      setNewProjectCompletedAt('');
      await refreshProjects(project.id);
      setToast({ msg: `项目 ${project.name} 已创建`, kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '创建项目失败', kind: 'error' });
    } finally {
      setCreatingProject(false);
    }
  }

  async function saveProject(event: FormEvent) {
    event.preventDefault();
    if (!selectedProject || !editProjectName.trim() || updatingProject) return;
    setUpdatingProject(true);
    try {
      const project = await updateProject(selectedProject.id, {
        name: editProjectName.trim(),
        completed_at: editCompletedAt || null,
      });
      setProjects((current) =>
        current.map((item) => (item.id === project.id ? { ...item, ...project } : item)),
      );
      setToast({ msg: '项目信息已保存', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '保存项目失败', kind: 'error' });
    } finally {
      setUpdatingProject(false);
    }
  }

  async function removeProject() {
    if (!selectedProject || deletingProject) return;
    const confirmed = window.confirm(`确认删除项目「${selectedProject.name}」？相关成员关系、资料和记忆草稿也会一起移除。`);
    if (!confirmed) return;
    setDeletingProject(true);
    try {
      await deleteProject(selectedProject.id);
      const remaining = projects.filter((project) => project.id !== selectedProject.id);
      setProjects(remaining);
      const next = remaining.find((project) => (project.department_id || 'research') === departmentId) || remaining[0];
      setProjectId(next?.id || '');
      setToast({ msg: '项目已删除', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '删除项目失败', kind: 'error' });
    } finally {
      setDeletingProject(false);
    }
  }

  async function saveRepository(event: FormEvent) {
    event.preventDefault();
    if (!selectedProject || !repoUrl.trim() || savingRepo) return;
    setSavingRepo(true);
    try {
      await upsertProjectRepository(selectedProject.id, {
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

  async function uploadMaterials() {
    if (!selectedProject || selectedMaterialFiles.length === 0 || uploadingMaterials) return;
    const confirmed = window.confirm(
      `是否已经把「${selectedProject.name}」的项目原始资料全部选好？确认后会入库，并生成项目经验草稿交给负责人审批。`,
    );
    if (!confirmed) return;
    setUploadingMaterials(true);
    try {
      const result = await uploadProjectMaterialsBatch(
        selectedProject.id,
        (selectedProject.department_id || departmentId) as DepartmentId,
        selectedMaterialFiles,
      );
      setSelectedMaterialFiles([]);
      if (materialFileRef.current) materialFileRef.current.value = '';
      setToast({
        msg: `已上传 ${result.raw_document_count} 个资料，项目经验草稿已提交负责人审批`,
        kind: 'info',
      });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '上传项目资料失败', kind: 'error' });
    } finally {
      setUploadingMaterials(false);
    }
  }

  async function submitReview(decision: 'approve' | 'reject') {
    if (!selectedDraft || reviewing) return;
    setReviewing(true);
    try {
      const result = await reviewProjectMemoryDraft(selectedDraft.id, decision, reviewComment.trim());
      setDrafts((current) =>
        current.map((draft) =>
          draft.id === selectedDraft.id
            ? {
                ...draft,
                status: result.status,
                document_id: result.document_id,
              }
            : draft,
        ),
      );
      setToast({
        msg: decision === 'approve' ? `审批通过，已入库 ${result.chunk_count} 个片段` : '草稿已驳回',
        kind: 'info',
      });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '审批失败', kind: 'error' });
    } finally {
      setReviewing(false);
    }
  }

  function openKnowledgeBase() {
    if (!selectedProject) return;
    router.push(`/knowledge?project_id=${encodeURIComponent(selectedProject.id)}`);
  }

  return (
    <div className="flex h-screen min-w-0 flex-col bg-[#eef3f9] text-[#10213e]">
      <header className="sticky top-0 z-10 border-b border-[#d7e0ec] bg-white/90 px-5 py-4 backdrop-blur md:px-6">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-3">
          <div>
            <div className="text-[12px] font-bold tracking-[0.04em] text-brand-600">PROJECT WORKBENCH</div>
            <h1 className="mt-1 text-[26px] font-semibold leading-tight tracking-normal text-[#10213e]">项目管理</h1>
            <p className="mt-1 text-sm leading-6 text-[#6e7d97]">
              {selectedProjectCanManage
                ? '管理研发项目、GitHub 仓库、结项日期和长期记忆入库流程。'
                : '查看项目概览，维护仓库地址，并提交项目原始资料。'}
            </p>
          </div>
          <div className="flex-1" />
          {selectedProject && (
            <Button type="button" variant="secondary" onClick={openKnowledgeBase}>
              <ExternalLink size={16} aria-hidden={true} />
              访问知识库
            </Button>
          )}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-5 py-6 md:px-6">
        <div className="mx-auto grid max-w-[1320px] gap-5">
          <section className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.35fr)]">
            <div className="rounded-lg border border-[#d7e0ec] bg-white shadow-[0_16px_36px_rgba(15,35,66,0.06)]">
              <div className="border-b border-[#d7e0ec] bg-[#f7faff] p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                    <FolderKanban size={20} aria-hidden={true} />
                  </div>
                  <div>
                    <h2 className="text-xl font-semibold leading-tight text-[#10213e]">项目列表</h2>
                    <p className="mt-1 text-sm text-[#6e7d97]">按部门选择项目并查看状态。</p>
                  </div>
                </div>
                <div className="mt-4">
                  <Select
                    value={departmentId}
                    onChange={(value) => setDepartmentId(value as DepartmentId)}
                    options={departmentOptions}
                    placeholder={loading ? '加载部门中' : '选择部门'}
                    disabled={loading || departmentOptions.length === 0}
                  />
                </div>
              </div>

              {loading ? (
                <div className="py-16 text-center text-[#8b99ae]">
                  <LoadingDots />
                </div>
              ) : filteredProjects.length === 0 ? (
                <div className="p-5">
                  <EmptyState
                    title="当前部门没有项目"
                    hint={canCreateProjects ? '可以在右侧创建一个新的研发项目' : '请联系项目负责人把你加入对应项目'}
                  />
                </div>
              ) : (
                <div className="max-h-[520px] divide-y divide-[#d7e0ec] overflow-y-auto">
                  {filteredProjects.map((project) => (
                    <button
                      key={project.id}
                      type="button"
                      onClick={() => setProjectId(project.id)}
                      className={`w-full px-5 py-4 text-left transition-colors ${
                        project.id === selectedProject?.id ? 'bg-brand-500/10' : 'hover:bg-[#f7faff]'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="break-words text-sm font-semibold text-[#10213e]">{project.name}</div>
                          <div className="mt-1 break-all font-mono text-[11px] text-[#8b99ae]">{project.id}</div>
                        </div>
                        <ProjectStatusBadge completedAt={project.completed_at} />
                      </div>
                      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-[#6e7d97]">
                        <span>创建：{fmtDate(project.created_at)}</span>
                        <span>结项：{fmtDate(project.completed_at)}</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="grid gap-5">
              {canCreateProjects && (
                <section className="rounded-lg border border-[#d7e0ec] bg-white p-5 shadow-[0_16px_36px_rgba(15,35,66,0.06)] md:p-6">
                  <div className="mb-5 flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                      <Plus size={20} aria-hidden={true} />
                    </div>
                    <div>
                      <h2 className="text-xl font-semibold leading-tight text-[#10213e]">创建项目</h2>
                      <p className="mt-1 text-sm text-[#6e7d97]">新项目会自动归属当前选择的部门。</p>
                    </div>
                  </div>
                  <form onSubmit={handleCreateProject} className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_190px_124px]">
                    <Field label="新项目名称" htmlFor="new-project-name">
                      <Input
                        id="new-project-name"
                        value={newProjectName}
                        onChange={(event) => setNewProjectName(event.target.value)}
                        placeholder="例如：智慧大脑 Agent"
                      />
                    </Field>
                    <Field label="新项目结项日期" htmlFor="new-project-completed-at">
                      <Input
                        id="new-project-completed-at"
                        type="date"
                        value={newProjectCompletedAt}
                        onChange={(event) => setNewProjectCompletedAt(event.target.value)}
                      />
                    </Field>
                    <div className="flex items-end">
                      <Button
                        type="submit"
                        className="w-full"
                        disabled={!newProjectName.trim() || !newProjectOrgId || creatingProject}
                        title={newProjectOrgId ? `自动归属：${autoOrgName || '当前组织'}` : '当前账号没有可创建项目的组织权限'}
                      >
                        {creatingProject ? <LoadingDots /> : '创建项目'}
                      </Button>
                    </div>
                  </form>
                  {!newProjectOrgId && (
                    <div className="mt-3 rounded-lg border border-[#f0a23a]/25 bg-[#f0a23a]/15 px-3 py-2 text-sm text-[#9a5a0d]">
                      当前账号没有可创建项目的组织权限。
                    </div>
                  )}
                </section>
              )}

              {selectedProject ? (
                <section className="rounded-lg border border-[#1f365b] bg-[#10213e] p-5 text-[#f7fbff] shadow-[0_24px_64px_rgba(15,35,66,0.08)] md:p-6">
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white/10 text-[#18b7d6] ring-1 ring-white/10">
                      <Archive size={20} aria-hidden={true} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] font-bold tracking-[0.04em] text-[#c7d2e1]">PROJECT PROFILE</div>
                      <h2 className="mt-1 break-words text-xl font-semibold leading-tight">{selectedProject.name}</h2>
                    </div>
                    <DepartmentBadge id={(selectedProject.department_id || 'research') as DepartmentId} name={selectedDepartment?.name} />
                  </div>
                  <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-3">
                    <Metric title="创建日期" value={fmtDate(selectedProject.created_at)} icon={<CalendarDays size={17} />} />
                    <Metric title="结项日期" value={fmtDate(selectedProject.completed_at)} icon={<CalendarDays size={17} />} />
                    {selectedProjectCanManage ? (
                      <Metric title="记忆草稿" value={`${drafts.length} 个`} detail={`${pendingDrafts} 待审 / ${approvedDrafts} 入库`} icon={<FileText size={17} />} />
                    ) : (
                      <Metric title="项目角色" value={projectRoleLabel(selectedProject.role)} detail="可提交项目资料" icon={<FileText size={17} />} />
                    )}
                  </div>
                </section>
              ) : null}
            </div>
          </section>

          {selectedProject ? (
            <>
              <section className={`grid grid-cols-1 gap-5 ${selectedProjectCanManage ? 'xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.8fr)]' : 'xl:grid-cols-[minmax(320px,0.82fr)_minmax(0,1fr)]'}`}>
                {selectedProjectCanManage && (
                  <div className="rounded-lg border border-[#d7e0ec] bg-white p-5 shadow-[0_16px_36px_rgba(15,35,66,0.06)] md:p-6">
                    <div className="mb-5 flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                        <PencilLine size={20} aria-hidden={true} />
                      </div>
                      <div>
                        <h2 className="text-xl font-semibold leading-tight text-[#10213e]">项目资料</h2>
                        <p className="mt-1 text-sm text-[#6e7d97]">改名、维护结项日期，或跳转到项目知识库。</p>
                      </div>
                    </div>
                    <form onSubmit={saveProject} className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_180px_132px]">
                      <Field label="当前项目名称" htmlFor="edit-project-name">
                        <Input
                          id="edit-project-name"
                          value={editProjectName}
                          onChange={(event) => setEditProjectName(event.target.value)}
                        />
                      </Field>
                      <Field label="当前项目结项日期" htmlFor="edit-completed-at">
                        <Input
                          id="edit-completed-at"
                          type="date"
                          value={editCompletedAt}
                          onChange={(event) => setEditCompletedAt(event.target.value)}
                        />
                      </Field>
                      <div className="flex items-end">
                        <Button type="submit" className="w-full" disabled={!editProjectName.trim() || updatingProject}>
                          {updatingProject ? <LoadingDots /> : (
                            <>
                              <Save size={16} aria-hidden={true} />
                              保存
                            </>
                          )}
                        </Button>
                      </div>
                    </form>
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <Button type="button" variant="secondary" onClick={openKnowledgeBase}>
                        <ExternalLink size={16} aria-hidden={true} />
                        访问对应项目知识库
                      </Button>
                      <Button type="button" variant="danger" onClick={removeProject} disabled={deletingProject}>
                        <Trash2 size={16} aria-hidden={true} />
                        {deletingProject ? '删除中' : '删除项目'}
                      </Button>
                    </div>
                  </div>
                )}

                <div className="rounded-lg border border-[#d7e0ec] bg-white p-5 shadow-[0_16px_36px_rgba(15,35,66,0.06)] md:p-6">
                  <div className="mb-5 flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                      <GitBranch size={20} aria-hidden={true} />
                    </div>
                    <div>
                      <h2 className="text-xl font-semibold leading-tight text-[#10213e]">GitHub 仓库</h2>
                      <p className="mt-1 text-sm text-[#6e7d97]">用于新成员拉取代码和理解项目上下文。</p>
                    </div>
                  </div>
                  <form onSubmit={saveRepository} className="grid gap-3">
                    <Field label="GitHub 仓库地址" htmlFor="memory-repo-url">
                      <Input
                        id="memory-repo-url"
                        value={repoUrl}
                        onChange={(event) => setRepoUrl(event.target.value)}
                        placeholder="https://github.com/org/repo.git"
                      />
                    </Field>
                    <div className="grid gap-3 sm:grid-cols-[minmax(120px,1fr)_132px]">
                      <Field label="默认分支" htmlFor="memory-repo-branch">
                        <Input
                          id="memory-repo-branch"
                          value={repoBranch}
                          onChange={(event) => setRepoBranch(event.target.value)}
                          placeholder="main"
                        />
                      </Field>
                      <div className="flex items-end">
                        <Button type="submit" className="w-full" disabled={!repoUrl.trim() || savingRepo}>
                          {savingRepo ? <LoadingDots /> : '保存仓库'}
                        </Button>
                      </div>
                    </div>
                  </form>
                </div>

                {!selectedProjectCanManage && (
                  <div className="rounded-lg border border-[#d7e0ec] bg-white p-5 shadow-[0_16px_36px_rgba(15,35,66,0.06)] md:p-6">
                    <div className="mb-5 flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                        <Upload size={20} aria-hidden={true} />
                      </div>
                      <div>
                        <h2 className="text-xl font-semibold leading-tight text-[#10213e]">上传项目资料</h2>
                        <p className="mt-1 text-sm text-[#6e7d97]">提交代码文件、PPT、Word、HTML、Markdown、TXT 等原始资料。</p>
                      </div>
                    </div>
                    <div className="grid gap-3">
                      <Field label="项目原始资料" htmlFor="project-material-files">
                        <Input
                          ref={materialFileRef}
                          id="project-material-files"
                          type="file"
                          multiple
                          accept=".pdf,.doc,.docx,.ppt,.pptx,.md,.markdown,.html,.htm,.txt,.py,.ts,.tsx,.js,.jsx,.json,.yaml,.yml,.css,.scss,.java,.go,.rs,.cpp,.c,.h,.cs,.sql"
                          onChange={(event) => setSelectedMaterialFiles(Array.from(event.target.files || []))}
                        />
                      </Field>
                      <div className="flex flex-col gap-3 rounded-lg border border-[#d7e0ec] bg-[#f7faff] px-4 py-3 text-sm text-[#6e7d97] sm:flex-row sm:items-center sm:justify-between">
                        <span className="break-words">
                          已选择 {selectedMaterialFiles.length} 个文件
                        </span>
                        <Button
                          type="button"
                          className="w-full sm:w-auto"
                          disabled={selectedMaterialFiles.length === 0 || uploadingMaterials}
                          onClick={uploadMaterials}
                        >
                          {uploadingMaterials ? <LoadingDots /> : (
                            <>
                              <Upload size={16} aria-hidden={true} />
                              上传项目资料
                            </>
                          )}
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </section>

              {selectedProjectCanManage && (
                <section className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
                <div className="rounded-lg border border-[#d7e0ec] bg-white shadow-[0_16px_36px_rgba(15,35,66,0.06)]">
                  <div className="flex items-center justify-between gap-2 border-b border-[#d7e0ec] bg-[#f7faff] px-5 py-4">
                    <div className="flex items-center gap-2 text-sm font-semibold text-[#10213e]">
                      <RefreshCw size={18} className="text-brand-600" aria-hidden="true" />
                      草稿与审批
                    </div>
                    <Button size="sm" variant="ghost" onClick={() => loadProjectMemory(selectedProject.id)}>
                      刷新
                    </Button>
                  </div>
                  <div className="p-4">
                    {drafts.length === 0 ? (
                      <EmptyState title="还没有长期记忆草稿" hint="上传资料后先生成草稿" />
                    ) : (
                      <div className="space-y-2">
                        {drafts.map((draft) => (
                          <button
                            key={draft.id}
                            type="button"
                            onClick={() => setSelectedDraftId(draft.id)}
                            className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                              selectedDraft?.id === draft.id
                                ? 'border-brand-500/30 bg-brand-500/10'
                                : 'border-[#d7e0ec] hover:bg-[#f7faff]'
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="break-words font-medium text-[#10213e]">{draft.title}</span>
                              <StatusBadge status={draft.status} />
                            </div>
                            <div className="mt-1 text-xs text-[#6e7d97]">
                              {draft.source_count} 个资料 · {fmtTime(draft.created_at)}
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-lg border border-[#d7e0ec] bg-white p-5 shadow-[0_16px_36px_rgba(15,35,66,0.06)] md:p-6">
                  {selectedDraft ? (
                    <div className="space-y-4">
                      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                        <div className="min-w-0">
                          <h2 className="break-words text-xl font-semibold leading-tight text-[#10213e]">{selectedDraft.title}</h2>
                          <p className="mt-1 text-sm text-[#6e7d97]">
                            {selectedDraft.department_name} · {statusLabel[selectedDraft.status]}
                          </p>
                        </div>
                        {selectedDraft.status === 'pending_review' && (
                          <div className="flex flex-wrap gap-2">
                            <Button
                              variant="secondary"
                              disabled={reviewing}
                              onClick={() => submitReview('reject')}
                            >
                              <XCircle size={17} aria-hidden="true" />
                              驳回
                            </Button>
                            <Button disabled={reviewing} onClick={() => submitReview('approve')}>
                              <CheckCircle2 size={17} aria-hidden="true" />
                              审批通过并入库
                            </Button>
                          </div>
                        )}
                      </div>
                      <Field label="审批意见" htmlFor="memory-review-comment">
                        <Textarea
                          id="memory-review-comment"
                          value={reviewComment}
                          onChange={(event) => setReviewComment(event.target.value)}
                          rows={3}
                          placeholder="填写通过或驳回原因"
                        />
                      </Field>
                      <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap rounded-lg border border-[#d7e0ec] bg-[#f7f9fc] p-4 text-sm leading-6 text-[#253655]">
                        {selectedDraft.markdown_content}
                      </pre>
                    </div>
                  ) : (
                    <EmptyState title="选择或生成一个草稿" />
                  )}
                </div>
                </section>
              )}
            </>
          ) : (
            <EmptyState title="请选择或创建项目" hint="项目管理会把仓库、长期记忆和知识库入口放在同一个页面" />
          )}
        </div>
      </main>

      {toast && <Toast message={toast.msg} kind={toast.kind} />}
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <label className="block text-sm" htmlFor={htmlFor}>
      <span className="mb-1.5 block text-sm font-medium text-[#253655]">{label}</span>
      {children}
    </label>
  );
}

function StatusBadge({ status }: { status: ProjectMemoryDraft['status'] }) {
  const className =
    status === 'approved'
      ? 'border-[#17a58a]/25 bg-[#17a58a]/12 text-[#137f6d]'
      : status === 'rejected'
        ? 'border-[#df5a67]/25 bg-[#df5a67]/12 text-[#b83d49]'
        : 'border-[#f0a23a]/25 bg-[#f0a23a]/15 text-[#9a5a0d]';
  return (
    <span className={`shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium ${className}`}>
      {statusLabel[status]}
    </span>
  );
}

function ProjectStatusBadge({ completedAt }: { completedAt?: string | null }) {
  const completed = Boolean(completedAt);
  return (
    <span
      className={`shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium ${
        completed
          ? 'border-[#17a58a]/25 bg-[#17a58a]/12 text-[#137f6d]'
          : 'border-[#f0a23a]/25 bg-[#f0a23a]/15 text-[#9a5a0d]'
      }`}
    >
      {completed ? '已设置结项' : '进行中'}
    </span>
  );
}

function DepartmentBadge({ id, name }: { id: DepartmentId; name?: string }) {
  return (
    <span className={`rounded-full border px-3 py-1 text-xs font-medium ${departmentTone[id]}`}>
      {name || id}
    </span>
  );
}

function Metric({
  title,
  value,
  detail,
  icon,
}: {
  title: string;
  value: string;
  detail?: string;
  icon: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.06] p-3">
      <div className="flex items-center gap-2 text-xs text-[#c7d2e1]">
        {icon}
        {title}
      </div>
      <div className="mt-2 break-words text-lg font-semibold leading-tight text-[#f7fbff]">{value}</div>
      {detail && <div className="mt-1 text-xs text-[#c7d2e1]">{detail}</div>}
    </div>
  );
}
