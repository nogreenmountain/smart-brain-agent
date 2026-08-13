'use client';

import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Archive,
  ArrowRightLeft,
  CalendarDays,
  CheckCircle2,
  ExternalLink,
  FileText,
  FolderKanban,
  Plus,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Trash2,
  X,
  XCircle,
} from 'lucide-react';

import { Button } from '@/components/Button';
import { EmptyState, LoadingDots, Toast } from '@/components/Feedback';
import { Input, Textarea } from '@/components/Input';
import { Select } from '@/components/Select';
import {
  createProject,
  createProjectMemoryDepartment,
  deleteProjectMemoryDepartment,
  deleteProject,
  Department,
  DepartmentId,
  getMe,
  getProjectDepartmentMigration,
  listProjectCatalog,
  listProjectMemoryDepartments,
  listProjectMemoryDrafts,
  listProjects,
  Me,
  Project,
  ProjectDepartmentMigration,
  ProjectMemoryDraft,
  reviewProjectMemoryDraft,
  startProjectDepartmentMigration,
  updateProject,
  updateProjectMemoryDepartment,
} from '@/lib/api';

const statusLabel: Record<ProjectMemoryDraft['status'], string> = {
  pending_review: '待审批',
  approved: '已入库',
  rejected: '已驳回',
};

const departmentTone: Record<string, string> = {
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
  return Boolean(me?.is_system_admin ||
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

function migrationStepLabel(step: string): string {
  const labels: Record<string, string> = {
    queued: '等待迁移作业开始',
    validating: '验证目标分类',
    inventory: '盘点项目原始资料、Wiki 与会议记录',
    syncing_metadata: '同步分类元数据',
    verifying: '执行完整性校验',
    completed: '三类知识资产已核验完成',
    failed: '迁移未完成，请查看错误后重试',
  };
  return labels[step] || step;
}

export default function AdminPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [departmentId, setDepartmentId] = useState<DepartmentId>('research');
  const [projectId, setProjectId] = useState('');
  const [drafts, setDrafts] = useState<ProjectMemoryDraft[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState('');
  const [reviewComment, setReviewComment] = useState('');
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectOrgId, setNewProjectOrgId] = useState('');
  const [newProjectCompletedAt, setNewProjectCompletedAt] = useState('');
  const [createTopLevelDepartmentId, setCreateTopLevelDepartmentId] = useState<DepartmentId>('');
  const [createDepartmentId, setCreateDepartmentId] = useState<DepartmentId>('');
  const [editProjectName, setEditProjectName] = useState('');
  const [editCompletedAt, setEditCompletedAt] = useState('');
  const [loading, setLoading] = useState(true);
  const [reviewing, setReviewing] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [updatingProject, setUpdatingProject] = useState(false);
  const [departmentTransferOpen, setDepartmentTransferOpen] = useState(false);
  const [transferDepartmentId, setTransferDepartmentId] = useState<DepartmentId>('');
  const [transferringDepartment, setTransferringDepartment] = useState(false);
  const [migrationConfirmed, setMigrationConfirmed] = useState(false);
  const [migrationJob, setMigrationJob] = useState<ProjectDepartmentMigration | null>(null);
  const [deletingProject, setDeletingProject] = useState(false);
  const [deleteProjectOpen, setDeleteProjectOpen] = useState(false);
  const [deleteProjectConfirmation, setDeleteProjectConfirmation] = useState('');
  const [categoryName, setCategoryName] = useState('');
  const [categoryParentId, setCategoryParentId] = useState<DepartmentId>('');
  const [editingCategoryId, setEditingCategoryId] = useState<DepartmentId>('');
  const [editingCategoryName, setEditingCategoryName] = useState('');
  const [editingCategorySortOrder, setEditingCategorySortOrder] = useState('');
  const [editingCategoryParentId, setEditingCategoryParentId] = useState<DepartmentId>('');
  const [savingCategory, setSavingCategory] = useState(false);
  const [categoryManagementOpen, setCategoryManagementOpen] = useState(false);
  const [toast, setToast] = useState<{ msg: string; kind: 'info' | 'error' } | null>(null);

  const projectDepartments = departments.filter((department) => department.allows_projects !== false);
  const topLevelDepartments = departments.filter((department) => !department.parent_id);
  const departmentOptions = projectDepartments.map((department) => ({
    value: department.id,
    label: department.parent_name ? `${department.parent_name} / ${department.name}` : department.name,
  }));

  const filteredProjects = useMemo(
    () => projects
      .filter((project) => (project.department_id || 'research') === departmentId)
      .sort((left, right) => {
        const statusOrder = Number(Boolean(left.completed_at)) - Number(Boolean(right.completed_at));
        if (statusOrder !== 0) return statusOrder;
        const nameOrder = left.name.localeCompare(right.name, 'zh-CN');
        return nameOrder !== 0 ? nameOrder : left.id.localeCompare(right.id);
      }),
    [projects, departmentId],
  );

  const selectedProject = projects.find((project) => project.id === projectId) || null;
  const selectedDepartment = departments.find((department) => department.id === departmentId);
  const selectedTopLevelDepartmentId = selectedDepartment?.parent_id || selectedDepartment?.id || '';
  const secondLevelDepartments = departments.filter(
    (department) => department.parent_id === selectedTopLevelDepartmentId,
  );
  const createSecondLevelDepartments = departments.filter(
    (department) => department.parent_id === createTopLevelDepartmentId,
  );
  const transferDepartment = departments.find((department) => department.id === transferDepartmentId);
  const transferTopLevelDepartmentId = transferDepartment?.parent_id || transferDepartment?.id || '';
  const transferSecondLevelDepartments = departments.filter(
    (department) => department.parent_id === transferTopLevelDepartmentId,
  );
  const selectedProjectCanManage = canManageProject(selectedProject);
  const canManageVisibleProject = filteredProjects.some((project) => canManageProject(project));
  const canCreateProjects = roleCanCreate(me) && (selectedProjectCanManage || canManageVisibleProject || projects.length === 0);
  const pendingDraftRows = drafts.filter((draft) => draft.status === 'pending_review');
  const selectedDraft = pendingDraftRows.find((draft) => draft.id === selectedDraftId) || pendingDraftRows[0] || null;
  const approvedDrafts = drafts.filter((draft) => draft.status === 'approved').length;
  const pendingDrafts = pendingDraftRows.length;

  const autoOrgName =
    (me?.memberships || []).find((membership) => membership.org_id === newProjectOrgId)?.org_name || '';

  useEffect(() => {
    let active = true;
    async function loadAdminPage() {
      try {
        const meResult = await getMe();
        if (!active) return;
        if (meResult.can_manage_projects === false) {
          router.replace('/profile');
          return;
        }
        const [departmentRows, projectRows] = await Promise.all([
          listProjectMemoryDepartments(true),
          meResult.is_system_admin ? listProjectCatalog() : listProjects(),
        ]);
        if (!active) return;
        setMe(meResult);
        setDepartments(departmentRows);
        setProjects(projectRows);
        const firstDepartment = departmentRows.find((department) => department.allows_projects !== false)?.id || 'research';
        const firstProjectDepartment = departmentRows.find((department) => department.id === firstDepartment);
        const firstTopLevelId = firstProjectDepartment?.parent_id || '';
        setCreateTopLevelDepartmentId(firstTopLevelId);
        setCreateDepartmentId(firstDepartment);
        const firstProject =
          projectRows.find((project) => (project.department_id || 'research') === firstDepartment) ||
          projectRows[0];
        setDepartmentId((firstProject?.department_id || firstDepartment) as DepartmentId);
        if (firstProject) setProjectId(firstProject.id);
        const firstAdminOrg = meResult.memberships.find(
          (membership) => membership.role === 'owner' || membership.role === 'admin',
        );
        if (firstAdminOrg) setNewProjectOrgId(firstAdminOrg.org_id);
      } catch (error: unknown) {
        if (!active) return;
        setToast({ msg: error instanceof Error ? error.message : '加载项目管理失败', kind: 'error' });
      } finally {
        if (active) setLoading(false);
      }
    }
    void loadAdminPage();
    return () => {
      active = false;
    };
  }, [router]);

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
      setDrafts([]);
      setSelectedDraftId('');
      setDepartmentTransferOpen(false);
      setTransferDepartmentId('');
      setMigrationConfirmed(false);
      setMigrationJob(null);
      return;
    }
    setEditProjectName(selectedProject.name);
    setEditCompletedAt(selectedProject.completed_at ? selectedProject.completed_at.slice(0, 10) : '');
    void loadProjectMemory(selectedProject.id, selectedProjectCanManage);
  }, [selectedProject, selectedProjectCanManage]);

  async function refreshProjects(selectId?: string) {
    const rows = me?.is_system_admin ? await listProjectCatalog() : await listProjects();
    setProjects(rows);
    if (selectId) setProjectId(selectId);
  }

  async function refreshDepartments(selectDepartmentId?: DepartmentId) {
    const rows = await listProjectMemoryDepartments(true);
    setDepartments(rows);
    if (selectDepartmentId) setDepartmentId(selectDepartmentId);
  }

  async function createCategory(event: FormEvent) {
    event.preventDefault();
    if (!categoryName.trim() || savingCategory) return;
    setSavingCategory(true);
    try {
      const created = await createProjectMemoryDepartment({
        name: categoryName.trim(),
        parent_id: categoryParentId || null,
      });
      setCategoryName('');
      setCategoryParentId('');
      await refreshDepartments(created.allows_projects ? created.id : undefined);
      setToast({ msg: `${created.level === 1 ? '第一分级' : '第二分级'} ${created.name} 已创建`, kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '创建分类失败', kind: 'error' });
    } finally {
      setSavingCategory(false);
    }
  }

  function startEditingCategory(department: Department) {
    setEditingCategoryId(department.id);
    setEditingCategoryName(department.name);
    setEditingCategorySortOrder(String(department.sort_order));
    setEditingCategoryParentId(department.parent_id || '');
  }

  async function saveCategory() {
    if (!editingCategoryId || !editingCategoryName.trim() || savingCategory) return;
    setSavingCategory(true);
    try {
      await updateProjectMemoryDepartment(editingCategoryId, {
        name: editingCategoryName.trim(),
        sort_order: Number(editingCategorySortOrder) || 0,
        ...(editingCategoryParentId ? { parent_id: editingCategoryParentId } : {}),
      });
      setEditingCategoryId('');
      await refreshDepartments();
      setToast({ msg: '分类名称和排序已保存', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '保存分类失败', kind: 'error' });
    } finally {
      setSavingCategory(false);
    }
  }

  async function removeCategory(department: Department) {
    if (savingCategory) return;
    const confirmed = window.confirm(`确认删除${department.level === 1 ? '第一分级' : '第二分级'}“${department.name}”吗？仅空分类可以删除。`);
    if (!confirmed) return;
    setSavingCategory(true);
    try {
      await deleteProjectMemoryDepartment(department.id);
      await refreshDepartments();
      setToast({ msg: `分类 ${department.name} 已删除`, kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '删除分类失败', kind: 'error' });
    } finally {
      setSavingCategory(false);
    }
  }

  async function loadProjectMemory(pid: string, includeDrafts = true) {
    try {
      if (!includeDrafts) {
        setDrafts([]);
        setSelectedDraftId('');
        return;
      }
      const draftRows = await listProjectMemoryDrafts(pid);
      setDrafts(draftRows);
      setSelectedDraftId(draftRows.find((draft) => draft.status === 'pending_review')?.id || '');
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '加载项目记忆数据失败', kind: 'error' });
    }
  }

  async function handleCreateProject(event: FormEvent) {
    event.preventDefault();
    if (!newProjectOrgId || !createDepartmentId || !newProjectName.trim() || creatingProject) return;
    setCreatingProject(true);
    try {
      const project = await createProject({
        org_id: newProjectOrgId,
        name: newProjectName.trim(),
        environment: 'development',
        department_id: createDepartmentId,
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

  function selectTopLevelDepartment(value: DepartmentId) {
    const topLevel = departments.find((department) => department.id === value);
    if (!topLevel) return;
    if (topLevel.allows_projects !== false) {
      setDepartmentId(topLevel.id);
      return;
    }
    const firstChild = departments.find(
      (department) => department.parent_id === topLevel.id && department.allows_projects !== false,
    );
    setDepartmentId(firstChild?.id || '');
  }

  function selectCreateTopLevelDepartment(value: DepartmentId) {
    setCreateTopLevelDepartmentId(value);
    const firstChild = departments.find((department) => department.parent_id === value);
    setCreateDepartmentId(firstChild?.id || '');
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
        current.map((item) => (
          item.id === project.id ? { ...item, ...project, role: item.role } : item
        )),
      );
      setToast({ msg: '项目信息已保存', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '保存项目失败', kind: 'error' });
    } finally {
      setUpdatingProject(false);
    }
  }

  async function reopenProject() {
    if (!selectedProject?.completed_at || !selectedProjectCanManage || updatingProject) return;
    const confirmed = window.confirm(
      `确认将项目“${selectedProject.name}”恢复为进行中吗？这会清空结项日期。`,
    );
    if (!confirmed) return;
    setUpdatingProject(true);
    try {
      const project = await updateProject(selectedProject.id, { completed_at: null });
      setProjects((current) =>
        current.map((item) => (
          item.id === project.id ? { ...item, ...project, role: item.role } : item
        )),
      );
      setEditCompletedAt('');
      setProjectId(project.id);
      setToast({ msg: '项目已恢复为进行中', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '恢复项目失败', kind: 'error' });
    } finally {
      setUpdatingProject(false);
    }
  }

  function openDepartmentTransfer() {
    if (!selectedProject || !selectedProjectCanManage) return;
    const currentDepartmentId = selectedProject.department_id || departmentId;
    const targetDepartment = projectDepartments.find((department) => department.id !== currentDepartmentId);
    setTransferDepartmentId(targetDepartment?.id || '');
    setMigrationConfirmed(false);
    setMigrationJob(null);
    setDepartmentTransferOpen(true);
  }

  function selectTransferTopLevelDepartment(value: DepartmentId) {
    const topLevel = departments.find((department) => department.id === value);
    if (!topLevel) return;
    if (topLevel.allows_projects !== false) {
      setTransferDepartmentId(topLevel.id);
      return;
    }
    const firstChild = projectDepartments.find((department) => department.parent_id === topLevel.id);
    setTransferDepartmentId(firstChild?.id || '');
  }

  async function transferProjectDepartment() {
    if (!selectedProject || !selectedProjectCanManage || !transferDepartmentId || !migrationConfirmed || transferringDepartment) return;
    const currentDepartmentId = selectedProject.department_id || departmentId;
    if (transferDepartmentId === currentDepartmentId) return;
    setTransferringDepartment(true);
    try {
      let job = await startProjectDepartmentMigration(selectedProject.id, {
        target_department_id: transferDepartmentId,
        expected_source_department_id: currentDepartmentId,
        migrate_knowledge_base: true,
      });
      setMigrationJob(job);
      while (job.status === 'queued' || job.status === 'running') {
        await new Promise((resolve) => window.setTimeout(resolve, 150));
        job = await getProjectDepartmentMigration(selectedProject.id, job.id);
        setMigrationJob(job);
      }
      if (job.status !== 'completed') throw new Error(job.error_message || '知识库迁移失败');
      const project = { ...selectedProject, department_id: transferDepartmentId };
      setProjects((current) =>
        current.map((item) => (
          item.id === project.id ? { ...item, ...project, role: item.role } : item
        )),
      );
      setDepartmentId(transferDepartmentId);
      setProjectId(project.id);
      setToast({ msg: '项目分类与知识库已完成迁移', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '移交部门失败', kind: 'error' });
    } finally {
      setTransferringDepartment(false);
    }
  }

  async function removeProject() {
    if (!selectedProject || deletingProject) return;
    if (deleteProjectConfirmation !== selectedProject.name) return;
    setDeletingProject(true);
    try {
      await deleteProject(selectedProject.id, deleteProjectConfirmation);
      const remaining = projects.filter((project) => project.id !== selectedProject.id);
      setProjects(remaining);
      const next = remaining.find((project) => (project.department_id || 'research') === departmentId) || remaining[0];
      setProjectId(next?.id || '');
      setDeleteProjectOpen(false);
      setDeleteProjectConfirmation('');
      setToast({ msg: '项目已删除', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '删除项目失败', kind: 'error' });
    } finally {
      setDeletingProject(false);
    }
  }

  async function submitReview(decision: 'approve' | 'reject') {
    if (!selectedDraft || reviewing) return;
    setReviewing(true);
    try {
      const result = await reviewProjectMemoryDraft(selectedDraft.id, decision, reviewComment.trim());
      const nextPending = pendingDraftRows.find((draft) => draft.id !== selectedDraft.id);
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
      setSelectedDraftId(nextPending?.id || '');
      setReviewComment('');
      setToast({
        msg: decision === 'approve'
          ? `已批准原始资料入库，共写入 ${result.chunk_count} 个知识片段`
          : '本批原始资料已驳回',
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
      <header className="sticky top-0 z-10 border-b border-[#d7e0ec] bg-white/95 px-4 py-4 backdrop-blur md:px-6">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-3">
          <div>
            <div className="text-[12px] font-bold tracking-[0.04em] text-brand-600">PROJECT WORKBENCH</div>
            <h1 className="mt-1 text-[26px] font-semibold leading-tight tracking-normal text-[#10213e]">项目管理</h1>
            <p className="mt-1 text-sm leading-6 text-[#6e7d97]">
              {selectedProjectCanManage
                ? '管理项目分类、结项日期和知识资产一致性迁移。资料与仓库统一在“上传资料”维护。'
                : '查看项目概览与当前分类。'}
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

      <main className="flex-1 overflow-y-auto px-4 py-6 md:px-6">
        <div className="mx-auto grid max-w-[1320px] gap-5">
          <section className="grid grid-cols-1 items-stretch gap-5 xl:grid-cols-[minmax(300px,0.82fr)_minmax(0,1.35fr)]">
            <div data-project-list-card className="h-full overflow-hidden rounded-lg border border-[#d7e0ec] bg-white shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
              <div className="border-b border-[#d7e0ec] bg-[#f7faff] p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                    <FolderKanban size={20} aria-hidden={true} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h2 className="text-xl font-semibold leading-tight text-[#10213e]">项目列表</h2>
                    <p className="mt-1 text-sm text-[#6e7d97]">固定显示三行，使用右侧滑块向下浏览。</p>
                  </div>
                  {me?.is_system_admin && (
                    <Button type="button" size="sm" variant="secondary" aria-label="打开分类管理" onClick={() => setCategoryManagementOpen(true)}>
                      <SlidersHorizontal size={16} aria-hidden="true" />分类管理
                    </Button>
                  )}
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <Field label="第一分级" htmlFor="project-first-level">
                    <Select
                      id="project-first-level"
                      value={selectedTopLevelDepartmentId}
                      onChange={(value) => selectTopLevelDepartment(value as DepartmentId)}
                      options={topLevelDepartments.map((department) => ({
                        value: department.id,
                        label: department.name,
                      }))}
                      placeholder={loading ? '加载分类中' : '选择第一分级'}
                      disabled={loading || topLevelDepartments.length === 0}
                    />
                  </Field>
                  {secondLevelDepartments.length > 0 && (
                    <Field label="第二分级" htmlFor="project-second-level">
                      <Select
                        id="project-second-level"
                        value={departmentId}
                        onChange={(value) => setDepartmentId(value as DepartmentId)}
                        options={secondLevelDepartments.map((department) => ({
                          value: department.id,
                          label: department.name,
                        }))}
                        placeholder="选择第二分级"
                        disabled={loading}
                      />
                    </Field>
                  )}
                </div>
              </div>

              {loading ? (
                <div className="py-16 text-center text-[#8b99ae]">
                  <LoadingDots />
                </div>
              ) : filteredProjects.length === 0 ? (
                <div className="p-5">
                  <EmptyState
                    title="当前分类没有项目"
                    hint={canCreateProjects ? '可以在右侧创建一个新的研发项目' : '请联系项目负责人把你加入对应项目'}
                  />
                </div>
              ) : (
                <div
                  aria-label="项目纵向滑动列表"
                  className="h-[336px] divide-y divide-[#d7e0ec] overflow-y-auto overscroll-contain [scrollbar-gutter:stable]"
                >
                  {filteredProjects.map((project) => (
                    <button
                      key={project.id}
                      type="button"
                      onClick={() => setProjectId(project.id)}
                      className={`h-28 w-full overflow-hidden px-5 py-4 text-left transition-colors ${
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

            <div data-testid="project-create-profile-workspace" className="grid gap-5 xl:grid-cols-[minmax(280px,0.72fr)_minmax(440px,1.28fr)] xl:items-stretch">
              {canCreateProjects && (
                <section className="h-full rounded-lg border border-[#d7e0ec] bg-white p-5 shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
                  <div className="mb-4 flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                      <Plus size={20} aria-hidden={true} />
                    </div>
                    <div>
                      <h2 className="text-xl font-semibold leading-tight text-[#10213e]">创建项目</h2>
                      <p className="mt-1 text-sm text-[#6e7d97]">新项目会归属当前精确选择的第一、第二分级。</p>
                    </div>
                  </div>
                  <form onSubmit={handleCreateProject} className="grid gap-3">
                    <div className="grid gap-3">
                      <Field label="项目第一分级" htmlFor="create-project-first-level">
                        <Select id="create-project-first-level" value={createTopLevelDepartmentId} onChange={(value) => selectCreateTopLevelDepartment(value as DepartmentId)} options={topLevelDepartments.map((department) => ({ value: department.id, label: department.name }))} />
                      </Field>
                      <Field label="项目第二分级" htmlFor="create-project-second-level">
                        <Select id="create-project-second-level" value={createDepartmentId} onChange={(value) => setCreateDepartmentId(value as DepartmentId)} options={createSecondLevelDepartments.map((department) => ({ value: department.id, label: department.name }))} />
                      </Field>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
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
                    <div className="flex items-end sm:col-span-2 xl:col-span-1">
                      <Button
                        type="submit"
                        className="w-full"
                        disabled={!newProjectName.trim() || !newProjectOrgId || !createDepartmentId || creatingProject}
                        title={newProjectOrgId ? `自动归属：${autoOrgName || '当前组织'}` : '当前账号没有可创建项目的组织权限'}
                      >
                        {creatingProject ? <LoadingDots /> : '创建项目'}
                      </Button>
                    </div>
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
                <section data-testid="project-profile-card" className="h-full rounded-lg border border-[#d7e0ec] bg-white p-5 text-[#10213e] shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                      <Archive size={20} aria-hidden={true} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] font-bold tracking-[0.04em] text-brand-600">PROJECT PROFILE</div>
                      <h2 className="mt-1 break-words text-xl font-semibold leading-tight">{selectedProject.name}</h2>
                    </div>
                    <DepartmentBadge
                      id={(selectedProject.department_id || 'research') as DepartmentId}
                      name={selectedDepartment?.parent_name
                        ? `${selectedDepartment.parent_name} / ${selectedDepartment.name}`
                        : selectedDepartment?.name}
                    />
                  </div>
                  <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <Metric title="创建日期" value={fmtDate(selectedProject.created_at)} icon={<CalendarDays size={17} />} />
                    <Metric title="结项日期" value={fmtDate(selectedProject.completed_at)} icon={<CalendarDays size={17} />} />
                    {selectedProjectCanManage ? (
                      <Metric title="记忆草稿" value={`${drafts.length} 个`} detail={`${pendingDrafts} 待审 / ${approvedDrafts} 入库`} icon={<FileText size={17} />} />
                    ) : (
                      <Metric title="项目角色" value={projectRoleLabel(selectedProject.role)} detail="可提交项目资料" icon={<FileText size={17} />} />
                    )}
                  </div>
                  {selectedProjectCanManage && (
                    <form onSubmit={saveProject} className="mt-4 grid gap-3 border-t border-[#e3e9f1] pt-4">
                      <div className="grid gap-3 sm:grid-cols-[minmax(220px,1fr)_180px]">
                      <Field label="项目名称" htmlFor="edit-project-name">
                        <Input
                          id="edit-project-name"
                          value={editProjectName}
                          onChange={(event) => setEditProjectName(event.target.value)}
                        />
                      </Field>
                      <Field label="结项日期" htmlFor="edit-completed-at">
                        <Input
                          id="edit-completed-at"
                          type="date"
                          value={editCompletedAt}
                          onChange={(event) => setEditCompletedAt(event.target.value)}
                        />
                      </Field>
                      </div>
                      <div className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-4">
                        <Button className="w-full" type="submit" disabled={!editProjectName.trim() || updatingProject}>
                          {updatingProject ? <LoadingDots /> : <><Save size={16} aria-hidden={true} />保存</>}
                        </Button>
                        <Button className="w-full" type="button" variant="secondary" onClick={openKnowledgeBase}>
                          <ExternalLink size={16} aria-hidden={true} />知识库
                        </Button>
                        <Button className="w-full" type="button" variant="secondary" onClick={openDepartmentTransfer}>
                          <ArrowRightLeft size={16} aria-hidden={true} />迁移分类
                        </Button>
                        {selectedProject.completed_at && (
                          <Button
                            className="w-full"
                            type="button"
                            variant="secondary"
                            onClick={reopenProject}
                            disabled={updatingProject}
                          >
                            <RefreshCw size={16} aria-hidden={true} />恢复为进行中
                          </Button>
                        )}
                        <Button className="w-full" type="button" variant="danger" onClick={() => {
                          setDeleteProjectOpen(true);
                          setDeleteProjectConfirmation('');
                        }} disabled={deletingProject}>
                          <Trash2 size={16} aria-hidden={true} />{deletingProject ? '删除中' : '删除项目'}
                        </Button>
                      </div>
                    </form>
                  )}
                  {selectedProjectCanManage && deleteProjectOpen && (
                    <div className="mt-4 rounded-lg border border-[#df5a67]/30 bg-[#fff7f7] p-4">
                      <div className="font-semibold text-[#9f2f3d]">确认删除项目“{selectedProject.name}”</div>
                      <p className="mt-2 text-sm leading-6 text-[#6e4a50]">删除会影响项目成员关系、项目资料、Wiki、会议记录、仓库配置、长期记忆和相关历史数据。此操作不可撤销。</p>
                      <Field label={`请输入项目名称“${selectedProject.name}”确认`} htmlFor="delete-project-confirmation">
                        <Input id="delete-project-confirmation" value={deleteProjectConfirmation} onChange={(event) => setDeleteProjectConfirmation(event.target.value)} />
                      </Field>
                      <div className="mt-3 flex gap-2">
                        <Button type="button" variant="danger" onClick={removeProject} disabled={deletingProject || deleteProjectConfirmation !== selectedProject.name}>确认永久删除</Button>
                        <Button type="button" variant="secondary" onClick={() => setDeleteProjectOpen(false)}>取消</Button>
                      </div>
                    </div>
                  )}
                  {selectedProjectCanManage && departmentTransferOpen && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#10213e]/55 p-3 backdrop-blur-[2px] sm:p-6">
                    <section role="dialog" aria-modal="true" aria-labelledby="department-migration-title" className="max-h-[calc(100vh-2rem)] w-full max-w-2xl overflow-y-auto rounded-xl bg-white shadow-[0_28px_80px_rgba(15,35,66,0.32)]">
                      <div className="border-b border-[#d7e0ec] px-5 py-4 sm:px-6">
                        <h2 id="department-migration-title" className="text-xl font-semibold text-[#10213e]">迁移项目分类与知识库</h2>
                        <p className="mt-1 text-sm leading-6 text-[#6e7d97]">不会复制或删除内容；项目 ID、成员、Wiki 版本和会议原文件保持不变。</p>
                      </div>
                      <div className="grid gap-4 px-5 py-5 sm:px-6">
                      <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="目标第一分级" htmlFor="transfer-first-level">
                        <Select
                          id="transfer-first-level"
                          value={transferTopLevelDepartmentId}
                          onChange={(value) => selectTransferTopLevelDepartment(value as DepartmentId)}
                          options={topLevelDepartments.map((department) => ({
                            value: department.id,
                            label: department.name,
                          }))}
                          placeholder="选择目标第一分级"
                          disabled={transferringDepartment}
                        />
                      </Field>
                      {transferSecondLevelDepartments.length > 0 && (
                        <Field label="目标第二分级" htmlFor="transfer-second-level">
                          <Select
                            id="transfer-second-level"
                            value={transferDepartmentId}
                            onChange={(value) => setTransferDepartmentId(value as DepartmentId)}
                            options={transferSecondLevelDepartments
                              .filter((department) => department.id !== (selectedProject.department_id || departmentId))
                              .map((department) => ({ value: department.id, label: department.name }))}
                            placeholder="选择目标第二分级"
                            disabled={transferringDepartment}
                          />
                        </Field>
                      )}
                      </div>
                      <div className="grid gap-2 sm:grid-cols-3">
                        {[
                          ['项目原始资料', migrationJob?.raw_material_count],
                          ['项目 Wiki', migrationJob?.wiki_page_count],
                          ['会议记录', migrationJob?.meeting_record_count],
                        ].map(([label, count]) => (
                          <div key={String(label)} className="rounded-lg border border-[#d7e0ec] bg-[#f7faff] p-3">
                            <div className="text-sm font-semibold text-[#253655]">{label}</div>
                            <div className="mt-1 text-xs text-[#6e7d97]">{typeof count === 'number' ? `${count} 项` : '开始后自动盘点'}</div>
                          </div>
                        ))}
                      </div>
                      {migrationJob && (
                        <div className="rounded-lg border border-brand-500/20 bg-brand-500/5 p-4">
                          <div className="flex items-center justify-between text-sm">
                            <span className="font-semibold text-[#253655]">{migrationJob.status === 'completed' ? '迁移完成' : migrationJob.status === 'failed' ? '迁移失败' : '正在迁移'}</span>
                            <span className="text-brand-700">{migrationJob.progress}%</span>
                          </div>
                          <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#dbe6f4]"><div className="h-full bg-brand-600 transition-all" style={{ width: `${migrationJob.progress}%` }} /></div>
                          <p className="mt-2 text-xs text-[#6e7d97]">{migrationStepLabel(migrationJob.current_step)}</p>
                          {migrationJob.error_message && <p role="alert" className="mt-2 text-sm text-[#b83d49]">{migrationJob.error_message}</p>}
                        </div>
                      )}
                      {!migrationJob && (
                        <label className="flex items-start gap-2 rounded-lg border border-[#d7e0ec] bg-[#f7faff] p-3 text-sm text-[#40516e]">
                          <input type="checkbox" aria-label="确认迁移项目知识库" checked={migrationConfirmed} onChange={(event) => setMigrationConfirmed(event.target.checked)} className="mt-0.5" />
                          <span>确认迁移项目知识库，并同步原始资料的结构化分类元数据。</span>
                        </label>
                      )}
                      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                        <Button
                          type="button"
                          onClick={transferProjectDepartment}
                          disabled={!transferDepartmentId || !migrationConfirmed || transferringDepartment || Boolean(migrationJob)}
                        >
                          {transferringDepartment ? <><LoadingDots />迁移中</> : '开始迁移'}
                        </Button>
                        <Button
                          type="button"
                          variant="secondary"
                          onClick={() => setDepartmentTransferOpen(false)}
                          disabled={transferringDepartment}
                        >
                          取消
                        </Button>
                      </div>
                      </div>
                    </section>
                    </div>
                  )}
                </section>
              ) : null}
            </div>
          </section>

          {selectedProject ? (
            <>
              {selectedProjectCanManage && (
                <section className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
                <div className="rounded-lg border border-[#d7e0ec] bg-white shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
                  <div className="flex items-center justify-between gap-2 border-b border-[#d7e0ec] bg-[#f7faff] px-5 py-4">
                    <div className="flex items-center gap-2 text-sm font-semibold text-[#10213e]">
                      <RefreshCw size={18} className="text-brand-600" aria-hidden="true" />
                      待审批资料
                    </div>
                    <Button size="sm" variant="ghost" onClick={() => loadProjectMemory(selectedProject.id)}>
                      刷新
                    </Button>
                  </div>
                  <div className="max-h-[620px] overflow-y-auto p-4">
                    {pendingDraftRows.length === 0 ? (
                      <EmptyState title="当前没有待审批资料" hint="员工提交通过安全检查的原始文件后，会出现在这里" />
                    ) : (
                      <div className="space-y-2">
                        {pendingDraftRows.map((draft) => (
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
                              {draft.source_count} 个原始文件 · {fmtTime(draft.created_at)}
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="max-h-[72vh] overflow-y-auto rounded-lg border border-[#d7e0ec] bg-white p-5 shadow-[0_10px_24px_rgba(15,35,66,0.04)] md:p-6">
                  {selectedDraft ? (
                    <div className="space-y-4">
                      <div className="sticky top-0 z-[1] flex flex-col gap-3 border-b border-[#e3e9f1] bg-white pb-3 md:flex-row md:items-center md:justify-between">
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
                              批准并入库
                            </Button>
                          </div>
                        )}
                      </div>
                      <Field label="备注（可选）" htmlFor="memory-review-comment">
                        <Textarea
                          id="memory-review-comment"
                          value={reviewComment}
                          onChange={(event) => setReviewComment(event.target.value)}
                          rows={3}
                          placeholder="只在需要补充说明时填写"
                        />
                      </Field>
                      <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap rounded-lg border border-[#d7e0ec] bg-[#f7f9fc] p-4 text-sm leading-6 text-[#253655]">
                        {selectedDraft.markdown_content}
                      </pre>
                    </div>
                  ) : (
                    <EmptyState title="选择一个待审批批次" />
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

      {me?.is_system_admin && categoryManagementOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#10213e]/55 p-3 backdrop-blur-[2px] sm:p-6">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="category-management-title"
            className="flex max-h-[calc(100vh-1.5rem)] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-white/70 bg-white shadow-[0_28px_80px_rgba(15,35,66,0.32)] sm:max-h-[calc(100vh-3rem)]"
          >
            <header className="flex items-start gap-3 border-b border-[#d7e0ec] bg-[#f7faff] px-5 py-4 sm:px-6">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                <SlidersHorizontal size={20} aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 id="category-management-title" className="text-xl font-semibold text-[#10213e]">分类管理</h2>
                <p className="mt-1 text-sm leading-6 text-[#6e7d97]">第一、第二分级只用于分类；具体项目必须归属第二分级。</p>
              </div>
              <button
                type="button"
                aria-label="关闭分类管理"
                onClick={() => setCategoryManagementOpen(false)}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[#6e7d97] hover:bg-white hover:text-[#10213e]"
              >
                <X size={19} aria-hidden="true" />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6 [scrollbar-gutter:stable]">
              <form onSubmit={createCategory} className="grid gap-3 lg:grid-cols-[minmax(180px,1fr)_minmax(180px,1fr)_auto] lg:items-end">
                <Field label="上级第一分级" htmlFor="category-parent">
                  <Select
                    id="category-parent"
                    value={categoryParentId}
                    onChange={(value) => setCategoryParentId(value as DepartmentId)}
                    options={[
                      { value: '', label: '无（创建第一分级）' },
                      ...topLevelDepartments.map((department) => ({ value: department.id, label: department.name })),
                    ]}
                  />
                </Field>
                <Field label={categoryParentId ? '第二分级名称' : '第一分级名称'} htmlFor="category-name">
                  <Input id="category-name" value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="输入分类名称" />
                </Field>
                <Button type="submit" disabled={!categoryName.trim() || savingCategory}>
                  <Plus size={16} aria-hidden="true" />新增分类
                </Button>
              </form>
              <div className="mt-5 grid gap-3">
                {topLevelDepartments.map((root) => {
                  const children = departments.filter((department) => department.parent_id === root.id);
                  return (
                    <div key={root.id} className="rounded-lg border border-[#d7e0ec] p-3">
                      {[root, ...children].map((department) => (
                        <div key={department.id} className={`flex flex-wrap items-center gap-2 py-2 ${department.parent_id ? 'ml-5 border-t border-[#edf1f6]' : ''}`}>
                          {editingCategoryId === department.id ? (
                            <>
                              <Input aria-label={`分类名称 ${department.name}`} value={editingCategoryName} onChange={(event) => setEditingCategoryName(event.target.value)} className="min-w-44 flex-1" />
                              <Input aria-label={`分类排序 ${department.name}`} type="number" value={editingCategorySortOrder} onChange={(event) => setEditingCategorySortOrder(event.target.value)} className="w-28" />
                              {department.parent_id && (
                                <Select
                                  aria-label={`上级第一分级 ${department.name}`}
                                  value={editingCategoryParentId}
                                  onChange={(value) => setEditingCategoryParentId(value as DepartmentId)}
                                  options={topLevelDepartments.map((rootDepartment) => ({ value: rootDepartment.id, label: rootDepartment.name }))}
                                />
                              )}
                              <Button type="button" onClick={saveCategory} disabled={savingCategory}>保存分类</Button>
                              <Button type="button" variant="secondary" onClick={() => setEditingCategoryId('')}>取消</Button>
                            </>
                          ) : (
                            <>
                              <span className="min-w-0 flex-1 text-sm font-medium text-[#10213e]">
                                {department.parent_id ? '└ ' : ''}{department.name}
                                <span className="ml-2 text-xs font-normal text-[#6e7d97]">排序 {department.sort_order}</span>
                              </span>
                              {department.is_direct ? (
                                <span className="rounded-full border border-brand-500/20 bg-brand-500/10 px-3 py-1.5 text-xs font-medium text-brand-700">
                                  系统分级 · 自动维护
                                </span>
                              ) : (
                                <>
                                  <Button type="button" variant="secondary" onClick={() => startEditingCategory(department)}>改名排序</Button>
                                  <Button type="button" variant="danger" onClick={() => void removeCategory(department)}>删除分类</Button>
                                </>
                              )}
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
        </div>
      )}

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
    <span className={`rounded-full border px-3 py-1 text-xs font-medium ${departmentTone[id] || 'border-[#8b99ae]/25 bg-[#eef2f7] text-[#50627b]'}`}>
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
    <div className="rounded-lg border border-[#d7e0ec] bg-[#f7faff] p-3">
      <div className="flex items-center gap-2 text-xs text-[#6e7d97]">
        {icon}
        {title}
      </div>
      <div className="mt-2 break-words text-lg font-semibold leading-tight text-[#10213e]">{value}</div>
      {detail && <div className="mt-1 text-xs text-[#6e7d97]">{detail}</div>}
    </div>
  );
}
