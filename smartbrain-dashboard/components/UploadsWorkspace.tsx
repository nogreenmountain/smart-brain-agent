'use client';

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import {
  ClipboardList,
  FileCheck2,
  FileUp,
  FolderUp,
  GitBranch,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';

import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { LoadingDots, Toast } from '@/components/Feedback';
import { Input } from '@/components/Input';
import { PageBody, PageHeader, PageShell } from '@/components/PageLayout';
import { ProjectHierarchySelector } from '@/components/ProjectHierarchySelector';
import {
  createMeetingSummary,
  getProjectRepository,
  listMeetingParticipantOptions,
  listProjectCatalog,
  listProjectMemoryDepartments,
  uploadProjectMaterialsDirect,
  upsertProjectRepository,
  type Department,
  type MeetingParticipantOption,
  type Project,
  type UploadProgress,
} from '@/lib/api';

type UploadTab = 'materials' | 'meetings' | 'repository';

const tabs: { id: UploadTab; label: string; icon: typeof FolderUp; description: string }[] = [
  { id: 'materials', label: '项目原始资料', icon: FolderUp, description: '文件直接可靠上传，完成后自动提交到审批流程。' },
  { id: 'meetings', label: '会议记录', icon: ClipboardList, description: '上传会议全文并提交管理员审批，已入库内容统一在知识库查看。' },
  { id: 'repository', label: 'GitHub 仓库', icon: GitBranch, description: '维护新成员和 AI 理解项目时使用的代码仓库入口。' },
];

const MATERIAL_ACCEPT = '.pdf,.docx,.pptx,.xlsx,.md,.markdown,.html,.htm,.txt,.py,.ts,.tsx,.js,.jsx,.json,.yaml,.yml,.css,.scss,.java,.go,.rs,.cpp,.c,.h,.cs,.sql';
const MEETING_FILE_ACCEPT = '.pdf,.docx,.pptx,.md,.txt,.html,.htm,.csv,.json,.xml,.yaml,.yml';
const MATERIAL_UPLOAD_LIMIT_MB = 500;
const MATERIAL_UPLOAD_LIMIT_BYTES = MATERIAL_UPLOAD_LIMIT_MB * 1024 * 1024;

export default function UploadsWorkspace({ initialTab = 'materials' }: { initialTab?: UploadTab }) {
  const materialFileRef = useRef<HTMLInputElement>(null);
  const materialClientUploadIdRef = useRef<string | null>(null);
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
  const [materialUploadProgress, setMaterialUploadProgress] = useState<UploadProgress | null>(null);
  const [materialUploadError, setMaterialUploadError] = useState('');
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
    materialClientUploadIdRef.current = null;
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

  async function uploadMaterials() {
    if (!selectedProjectIsMember || !selectedProject?.department_id || selectedMaterialFiles.length === 0 || uploadingMaterials) return;
    const oversizedFile = selectedMaterialFiles.find((file) => file.size > MATERIAL_UPLOAD_LIMIT_BYTES);
    if (oversizedFile) {
      setMaterialUploadError(`单个文件不能超过 ${MATERIAL_UPLOAD_LIMIT_MB} MB：${oversizedFile.name}`);
      return;
    }
    const totalBytes = selectedMaterialFiles.reduce((total, file) => total + file.size, 0);
    if (totalBytes > MATERIAL_UPLOAD_LIMIT_BYTES) {
      setMaterialUploadError(`单批文件总大小不能超过 ${MATERIAL_UPLOAD_LIMIT_MB} MB`);
      return;
    }
    setMaterialUploadError('');
    setMaterialUploadProgress({
      phase: 'uploading', percent: 0, loadedBytes: 0,
      totalBytes,
    });
    setUploadingMaterials(true);
    try {
      if (!materialClientUploadIdRef.current) {
        materialClientUploadIdRef.current = createClientUploadId();
      }
      const result = await uploadProjectMaterialsDirect(
        selectedProject.id,
        selectedProject.department_id,
        selectedMaterialFiles,
        materialClientUploadIdRef.current,
        setMaterialUploadProgress,
      );
      clearMaterialSelection();
      setToast({ msg: `已提交 ${result.raw_document_count} 份原始资料，等待管理员审批后入库`, kind: 'info' });
    } catch (error: unknown) {
      setMaterialUploadError(error instanceof Error ? error.message : '资料上传失败');
    } finally {
      setMaterialUploadProgress(null);
      setUploadingMaterials(false);
    }
  }

  function clearMaterialSelection() {
    setSelectedMaterialFiles([]);
    materialClientUploadIdRef.current = null;
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
      setToast({ msg: '仓库地址已提交审批，管理员批准后生效', kind: 'info' });
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
                <p className="mt-1 text-sm leading-6 text-[#6e7d97]">文件会直接分块上传并提交审批；网络中断后可保留当前选择并继续重试。</p>
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
                  materialClientUploadIdRef.current = null;
                }}
                className="mt-1.5"
              />
            </label>
            <p className="mt-2 text-xs leading-5 text-[#6e7d97]">
              单个文件和单批总大小均不超过 {MATERIAL_UPLOAD_LIMIT_MB} MB；超限文件不会发起上传请求。
            </p>
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
                onClick={uploadMaterials}
              >
                {uploadingMaterials ? <LoadingDots /> : <><FileUp size={16} aria-hidden="true" />上传并提交审批</>}
              </Button>
            </div>
          </Card>
        )}

        {activeTab === 'meetings' && (
          <Card className="overflow-hidden">
            <div className="border-b border-[#d7e0ec] bg-[#f7faff] px-5 py-4">
              <h2 className="text-xl font-semibold text-[#10213e]">会议记录</h2>
              <p className="mt-1 text-sm text-[#6e7d97]">此页面只负责上传；审批通过后的会议记录统一在知识库中查看和管理。</p>
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
                <p className="mt-1 text-sm leading-6 text-[#6e7d97]">提交仓库地址和默认分支供管理员审批；批准前当前已生效配置保持不变。</p>
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
                  {savingRepo ? <LoadingDots /> : '提交仓库审批'}
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

      {materialUploadProgress && <UploadProgressDialog title="项目原始资料" progress={materialUploadProgress} />}
      {materialUploadError && (
        <UploadErrorDialog
          title="项目原始资料"
          message={materialUploadError}
          onClose={() => setMaterialUploadError('')}
        />
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
  const [projectQuery, setProjectQuery] = useState('');
  const [title, setTitle] = useState('');
  const [meetingDate, setMeetingDate] = useState(localDate());
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [membersLoading, setMembersLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [uploadError, setUploadError] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const selectedProject = projects.find((project) => project.id === projectId);
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
    setError('');
  }, [projectId]);

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
    setUploadError('');
    setUploadProgress({ phase: 'uploading', percent: 0, loadedBytes: 0, totalBytes: file.size });
    try {
      await createMeetingSummary({
        projectId,
        title: title.trim(),
        meetingDate,
        participantUserIds: selectedParticipantIds,
        file,
      }, setUploadProgress);
      setTitle('');
      setSelectedParticipantIds([]);
      setMemberQuery('');
      setFile(null);
      setFileInputKey((current) => current + 1);
      setNotice('会议记录已提交审批，管理员批准后会进入知识库的“会议记录”分类。');
    } catch (requestError) {
      setUploadError(requestError instanceof Error ? requestError.message : '会议记录上传失败');
    } finally {
      setUploadProgress(null);
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-lg border border-[#bee2cf] bg-[#f2fbf6] p-4 text-sm leading-6 text-[#50627b]">
        <ShieldCheck size={19} className="mt-0.5 shrink-0 text-[#2c7a59]" aria-hidden="true" />
        <p>所有已启用的智慧大脑用户都可以搜索项目并提交会议记录；管理员审批通过后，项目成员可在知识库查看、预览和下载。</p>
      </div>

      <div className="mx-auto grid min-w-0 max-w-3xl gap-4">
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
          {error && <div className="rounded-lg border border-[#efc9c9] bg-[#fff7f7] px-4 py-3 text-sm text-[#a33a3a]"><TriangleAlert size={16} className="mr-2 inline" />{error}</div>}
          {notice && <div className="rounded-lg border border-[#bee2cf] bg-[#f2fbf6] px-4 py-3 text-sm text-[#28714f]">{notice}</div>}
      </div>
      {uploadProgress && <UploadProgressDialog title="会议记录" progress={uploadProgress} />}
      {uploadError && (
        <UploadErrorDialog title="会议记录" message={uploadError} onClose={() => setUploadError('')} />
      )}
    </div>
  );
}

function UploadProgressDialog({ title, progress }: { title: string; progress: UploadProgress }) {
  const isUploading = progress.phase === 'uploading';
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#10213e]/55 p-4 backdrop-blur-[2px]">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${title}-upload-progress-title`}
        className="w-full max-w-lg rounded-xl border border-white/70 bg-white p-6 shadow-[0_28px_80px_rgba(15,35,66,0.32)]"
      >
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
            <FileUp size={21} aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id={`${title}-upload-progress-title`} className="text-lg font-semibold text-[#10213e]">{title}上传中</h2>
            <p className="mt-1 text-sm leading-6 text-[#6e7d97]">
              {isUploading ? '正在上传文件，请保持页面打开。' : '文件已传输完成，服务器正在解析并写入数据库，请耐心等待。'}
            </p>
          </div>
        </div>
        <div className="mt-5">
          <div
            role="progressbar"
            aria-label={`${title}上传进度`}
            aria-valuemin={0}
            aria-valuemax={100}
            {...(progress.percent === null ? {} : { 'aria-valuenow': progress.percent })}
            className="h-3 overflow-hidden rounded-full bg-[#e4ebf4]"
          >
            <div
              className={`h-full rounded-full bg-brand-600 transition-[width] duration-200 ${progress.percent === null ? 'w-1/2 animate-pulse' : ''}`}
              style={progress.percent === null ? undefined : { width: `${progress.percent}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between gap-3 text-xs text-[#6e7d97]">
            <span>{isUploading ? formatUploadBytes(progress.loadedBytes, progress.totalBytes) : '服务器处理中'}</span>
            <span className="font-semibold text-[#355170]">{progress.percent === null ? '请稍候' : `${progress.percent}%`}</span>
          </div>
        </div>
      </section>
    </div>
  );
}

function UploadErrorDialog({ title, message, onClose }: { title: string; message: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#10213e]/55 p-4 backdrop-blur-[2px]">
      <section
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${title}-upload-error-title`}
        aria-describedby={`${title}-upload-error-message`}
        className="w-full max-w-lg rounded-xl border border-[#efc9c9] bg-white p-6 shadow-[0_28px_80px_rgba(15,35,66,0.32)]"
      >
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-[#df5a67]/10 text-[#b83d49]">
            <TriangleAlert size={21} aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id={`${title}-upload-error-title`} className="text-lg font-semibold text-[#9f3440]">{title}上传失败</h2>
            <p id={`${title}-upload-error-message`} className="mt-2 break-words text-sm leading-6 text-[#6e4a50]">{message}</p>
            <p className="mt-2 text-xs leading-5 text-[#6e7d97]">已选择的文件和表单内容会保留，关闭后可以直接重试。</p>
          </div>
        </div>
        <div className="mt-5 flex justify-end">
          <Button type="button" onClick={onClose}>关闭错误信息</Button>
        </div>
      </section>
    </div>
  );
}

function formatUploadBytes(loaded: number, total: number): string {
  if (total <= 0) return `${formatFileSize(loaded)} 已上传`;
  return `${formatFileSize(loaded)} / ${formatFileSize(total)}`;
}

function createClientUploadId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
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
