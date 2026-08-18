'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ShieldCheck, Trash2, UserPlus } from 'lucide-react';
import {
  addProjectMember,
  ApiError,
  Department,
  getMe,
  listProjectMemoryDepartments,
  listProjectMemberOptions,
  listProjectMembers,
  listProjectCatalog,
  Me,
  Project,
  ProjectMember,
  ProjectMemberOption,
  ProjectRole,
  removeProjectMember,
} from '@/lib/api';
import { Button } from '@/components/Button';
import { EmptyState, LoadingDots, Toast } from '@/components/Feedback';
import { ProjectHierarchySelector } from '@/components/ProjectHierarchySelector';
import { Select } from '@/components/Select';
import { TeamDirectoryPanel } from './TeamDirectoryPanel';

const ROLE_OPTIONS: { value: ProjectRole; label: string }[] = [
  { value: 'developer', label: '项目成员' },
  { value: 'admin', label: '项目负责人' },
  { value: 'owner', label: '总负责人' },
];

function isLeaderRole(role: ProjectRole) {
  return role === 'owner' || role === 'admin';
}

function roleLabel(role: ProjectRole) {
  if (role === 'owner') return '总负责人';
  if (role === 'admin') return '项目负责人';
  return '项目成员';
}

function roleTone(role: ProjectRole) {
  if (isLeaderRole(role)) return 'bg-brand-500/10 text-brand-700 border-brand-500/20';
  return 'bg-[#17a58a]/10 text-[#137f6d] border-[#17a58a]/20';
}

function canManageProject(project: Project | null) {
  return Boolean(project?.role && isLeaderRole(project.role));
}

function CompactMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-[76px] rounded-lg border border-[#d7e0ec] bg-white px-3 py-2 shadow-sm">
      <div className="text-base font-semibold leading-none text-[#10213e]">{value}</div>
      <div className="mt-1 text-[11px] font-medium text-[#6e7d97]">{label}</div>
    </div>
  );
}

export function MembersManagementContent({ embedded = false }: { embedded?: boolean }) {
  const router = useRouter();
  const didInitialLoad = useRef(false);
  const [me, setMe] = useState<Me | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [memberOptions, setMemberOptions] = useState<ProjectMemberOption[]>([]);
  const [memberSearch, setMemberSearch] = useState('');
  const [selectedMemberId, setSelectedMemberId] = useState('');
  const [memberRole, setMemberRole] = useState<ProjectRole>('developer');
  const [loading, setLoading] = useState(true);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: 'info' | 'error' } | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) || null,
    [projects, selectedProjectId],
  );

  const selectedProjectCanManage = canManageProject(selectedProject);
  const canAssignOwner = Boolean(me?.is_system_admin) || selectedProject?.role === 'owner';
  const assignableRoleOptions = canAssignOwner
    ? ROLE_OPTIONS
    : ROLE_OPTIONS.filter((option) => option.value !== 'owner');

  const filteredMemberOptions = useMemo(() => {
    const query = memberSearch.trim().toLocaleLowerCase();
    if (!query) return memberOptions;
    return memberOptions.filter((member) => (
      member.nickname || member.display_name || member.username || member.email
    ).toLocaleLowerCase().includes(query)
      || member.username.toLocaleLowerCase().includes(query)
      || member.email.toLocaleLowerCase().includes(query));
  }, [memberOptions, memberSearch]);

  const privilegedCount = useMemo(
    () => members.filter((member) => isLeaderRole(member.role)).length,
    [members],
  );
  const overallLeadCount = useMemo(
    () => members.filter((member) => member.role === 'owner').length,
    [members],
  );

  const regularMemberCount = useMemo(
    () => members.filter((member) => !isLeaderRole(member.role)).length,
    [members],
  );

  const loadMembers = useCallback(async (projectId: string) => {
    setLoadingMembers(true);
    try {
      const rows = await listProjectMembers(projectId);
      setMembers(Array.isArray(rows) ? rows : []);
    } catch (e: any) {
      setMembers([]);
      if (e instanceof ApiError && e.status === 401) {
        router.replace('/login');
      } else {
        setToast({ msg: e?.message || '加载成员失败', kind: 'error' });
      }
    } finally {
      setLoadingMembers(false);
    }
  }, [router]);

  const loadMemberOptions = useCallback(async (projectId: string) => {
    try {
      const rows = await listProjectMemberOptions(projectId);
      setMemberOptions(Array.isArray(rows) ? rows : []);
    } catch (e: any) {
      setMemberOptions([]);
      if (e instanceof ApiError && e.status === 401) {
        router.replace('/login');
      } else {
        setToast({ msg: e?.message || '加载团队成员选项失败', kind: 'error' });
      }
    }
  }, [router]);

  useEffect(() => {
    if (didInitialLoad.current) return;
    didInitialLoad.current = true;
    (async () => {
      setLoading(true);
      try {
        const currentUser = await getMe();
        const [departmentRows, projectRows] = await Promise.all([
          listProjectMemoryDepartments(true),
          listProjectCatalog(),
        ]);
        setMe(currentUser);
        setDepartments(departmentRows);
        setProjects(projectRows);
        const firstProject = projectRows[0];
        if (firstProject) {
          setSelectedProjectId(firstProject.id);
          await loadMembers(firstProject.id);
          if (canManageProject(firstProject)) {
            await loadMemberOptions(firstProject.id);
          }
        }
      } catch (e: any) {
        if (e instanceof ApiError && e.status === 401) {
          router.replace('/login');
        } else {
          setToast({ msg: e?.message || '加载成员管理数据失败', kind: 'error' });
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [loadMemberOptions, loadMembers, router]);

  async function handleProjectChange(projectId: string) {
    setSelectedProjectId(projectId);
    setMembers([]);
    setMemberOptions([]);
    setMemberSearch('');
    setSelectedMemberId('');
    if (projectId) {
      await loadMembers(projectId);
      const project = projects.find((item) => item.id === projectId) || null;
      if (canManageProject(project)) {
        await loadMemberOptions(projectId);
      }
    }
  }

  async function handleAddMember(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedProjectCanManage || !selectedProjectId || !selectedMemberId || saving) return;
    setSaving(true);
    try {
      await addProjectMember(selectedProjectId, {
        user_id: selectedMemberId,
        role: memberRole,
      });
      setMemberSearch('');
      setSelectedMemberId('');
      await loadMembers(selectedProjectId);
      await loadMemberOptions(selectedProjectId);
      setToast({ msg: '成员已添加或更新', kind: 'info' });
    } catch (e: any) {
      setToast({ msg: e?.message || '添加成员失败', kind: 'error' });
    } finally {
      setSaving(false);
    }
  }

  async function handleRemoveMember(member: ProjectMember) {
    if (!selectedProjectCanManage || !selectedProjectId || deletingUserId) return;
    if (!window.confirm(`确认将 ${member.username || member.email} 从当前项目移除？团队账号和历史记录不会受影响。`)) return;
    setDeletingUserId(member.user_id);
    try {
      await removeProjectMember(selectedProjectId, member.user_id);
      await loadMembers(selectedProjectId);
      await loadMemberOptions(selectedProjectId);
      setToast({ msg: '成员已从项目移除', kind: 'info' });
    } catch (e: any) {
      setToast({ msg: e?.message || '移出项目失败', kind: 'error' });
    } finally {
      setDeletingUserId(null);
    }
  }

  return (
    <div className={`flex min-w-0 flex-col bg-[#eef3f9] text-[#10213e] ${embedded ? 'h-full' : 'h-screen'}`}>
      {!embedded && <header className="sticky top-0 z-10 border-b border-[#d7e0ec] bg-white/95 px-4 py-4 backdrop-blur md:px-6">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-bold text-brand-600">ADMIN WORKBENCH</div>
            <h1 className="mt-1 text-[26px] font-semibold leading-tight tracking-normal text-[#10213e]">
              {selectedProjectCanManage ? '成员管理' : '成员信息'}
            </h1>
            <p className="mt-1 text-sm text-[#6e7d97]">
              {selectedProjectCanManage ? '查看所有项目，并维护当前负责项目的成员与角色。' : '查看所有项目的负责人和成员名单。'}
            </p>
          </div>
          {me && (
            <div className="flex h-10 w-full items-center gap-2 rounded-lg border border-[#d7e0ec] bg-[#f7f9fc] px-3 text-xs text-[#6e7d97] sm:w-auto">
              <ShieldCheck size={14} className={selectedProjectCanManage ? 'text-[#17a58a]' : 'text-[#8b99ae]'} aria-hidden={true} />
              <span className="max-w-[220px] truncate">{me.email.split('@', 1)[0]}</span>
              <span className={selectedProjectCanManage ? 'text-[#137f6d]' : 'text-[#6e7d97]'}>
                {selectedProjectCanManage ? '项目负责人' : '成员列表可见'}
              </span>
            </div>
          )}
        </div>
      </header>}

      <main className={`flex-1 overflow-y-auto px-4 md:px-6 ${embedded ? 'py-3' : 'py-6'}`}>
        <div className="mx-auto grid max-w-[1440px] gap-3">
          {me?.is_system_admin && <TeamDirectoryPanel currentUser={me} />}
          <section className="rounded-lg border border-[#d7e0ec] bg-white shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
            <div className="border-b border-[#d7e0ec] bg-[#f7faff] px-4 py-3 md:px-5">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                  <UserPlus size={20} aria-hidden={true} />
                </div>
                <div className="min-w-0">
                  <h2 className="text-lg font-semibold leading-tight text-[#10213e]">
                    {selectedProjectCanManage ? '添加成员' : '成员概览'}
                  </h2>
                  <p className="mt-0.5 text-sm text-[#6e7d97]">
                    {selectedProjectCanManage
                      ? '先按分类定位项目，再从团队成员中选择人员加入项目。'
                      : '所有登录成员都可以查看各项目的负责人和成员名单。'}
                  </p>
                </div>
                <div className="flex-1" />
                <div className="grid grid-cols-3 gap-2 text-center">
                  <CompactMetric label="成员" value={members.length} />
                  <CompactMetric label="负责人" value={privilegedCount} />
                  <CompactMetric label="项目成员" value={regularMemberCount} />
                </div>
              </div>
            </div>

            <div className="p-4">
              <div className="grid min-w-0 grid-cols-1 gap-4">
                <div aria-label="项目筛选" className="min-w-0">
                  <ProjectHierarchySelector
                  departments={departments}
                  projects={projects}
                  projectId={selectedProjectId}
                  onProjectChange={handleProjectChange}
                  loading={loading}
                  showEnvironment
                  />
                </div>

                {selectedProjectCanManage && (
                  <form
                    aria-label="添加项目成员"
                    onSubmit={handleAddMember}
                    className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-[minmax(180px,0.8fr)_minmax(0,1fr)_minmax(140px,0.45fr)]"
                  >
                    <label className="min-w-0">
                      <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">搜索团队成员</span>
                      <input
                        aria-label="搜索团队成员"
                        value={memberSearch}
                        onChange={(event) => {
                          setMemberSearch(event.target.value);
                          setSelectedMemberId('');
                        }}
                        placeholder="输入姓名、昵称或账号中的任意一个字"
                        disabled={!selectedProjectId || saving}
                        className="h-10 w-full rounded-lg border border-[#d7e0ec] bg-white px-3 text-sm text-[#10213e] outline-none placeholder:text-[#8b99ae] focus:border-brand-500 focus:ring-4 focus:ring-brand-500/20 disabled:bg-[#f7f9fc] disabled:text-[#8b99ae]"
                      />
                    </label>
                    <label className="min-w-0">
                      <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">选择团队成员</span>
                      <Select
                        aria-label="选择团队成员"
                        value={selectedMemberId}
                        onChange={setSelectedMemberId}
                        placeholder={filteredMemberOptions.length > 0 ? '选择尚未加入项目的成员' : memberOptions.length > 0 ? '没有匹配的团队成员' : '暂无可添加成员'}
                        options={filteredMemberOptions.map((member) => ({
                          value: member.user_id,
                          label: member.nickname
                            ? `${member.nickname}（账号：${member.username}）`
                            : member.username,
                        }))}
                        disabled={!selectedProjectId || saving}
                      />
                    </label>
                    <label className="min-w-0">
                      <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">成员角色</span>
                      <Select
                        value={memberRole}
                        onChange={(value) => setMemberRole(value as ProjectRole)}
                        options={assignableRoleOptions}
                        disabled={!selectedProjectId || saving}
                      />
                    </label>
                    <div className="flex min-w-0 items-end md:col-span-2 xl:col-span-3">
                      <Button
                        type="submit"
                        className="w-full"
                        disabled={!selectedProjectId || !selectedMemberId || saving}
                      >
                        {saving ? <LoadingDots /> : '添加成员'}
                      </Button>
                    </div>
                  </form>
                )}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[#6e7d97]">
                <span className="rounded-full border border-[#d7e0ec] bg-[#f7f9fc] px-2.5 py-1">
                  当前项目：{selectedProject?.name || '未选择项目'}
                </span>
                {selectedProjectCanManage ? (
                  <span>这里只能选择团队管理中已启用的成员。</span>
                ) : (
                  <span>此项目为只读展示；只有该项目负责人可以调整成员。</span>
                )}
              </div>
            </div>
          </section>

          <section className="overflow-hidden rounded-lg border border-[#d7e0ec] bg-white shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
            <div className="flex flex-wrap items-center gap-3 border-b border-[#d7e0ec] bg-[#f7faff] px-4 py-3 md:px-5">
              <div>
                <h2 className="text-lg font-semibold leading-tight text-[#10213e]">
                  {selectedProject ? `${selectedProject.name} 成员` : '项目成员'}
                </h2>
              </div>
              <div className="flex-1" />
              <span className="rounded-full border border-brand-500/20 bg-brand-500/10 px-3 py-1 text-xs font-medium text-brand-700">
                {members.length} 人
              </span>
            </div>

            {loading || loadingMembers ? (
              <div className="py-12 text-center text-[#8b99ae]">
                <LoadingDots />
              </div>
            ) : !selectedProjectId ? (
              <EmptyState title="当前分类暂无可查看项目" hint="请联系项目负责人把你加入对应项目" />
            ) : members.length === 0 ? (
              <EmptyState title="暂无成员" />
            ) : (
              <div>
                <div className={`hidden gap-4 border-b border-[#d7e0ec] bg-[#f7f9fc] px-4 py-2.5 text-xs font-semibold text-[#6e7d97] md:px-5 lg:grid ${selectedProjectCanManage ? 'grid-cols-[minmax(220px,1.35fr)_120px_120px]' : 'grid-cols-[minmax(220px,1.35fr)_160px]'}`}>
                  <div>成员</div>
                  <div>角色</div>
                  {selectedProjectCanManage && <div className="text-right">操作</div>}
                </div>
                <div className="divide-y divide-[#d7e0ec]">
                  {members.map((member) => (
                    <div key={member.user_id} className="px-4 py-3 text-sm hover:bg-[#f7faff] md:px-5">
                      {(() => {
                        const isCurrentUser = member.user_id === me?.user_id;
                        const canOperateMember = canAssignOwner || member.role !== 'owner';
                        const isLastOwner = member.role === 'owner' && overallLeadCount <= 1;
                        const memberUsername = member.username || member.email.split('@', 1)[0];
                        const memberNickname = member.nickname?.trim();
                        return (
                      <div className={`grid grid-cols-1 gap-3 lg:items-center ${selectedProjectCanManage ? 'lg:grid-cols-[minmax(220px,1.35fr)_120px_120px]' : 'lg:grid-cols-[minmax(220px,1.35fr)_160px]'}`}>
                        <div className="min-w-0">
                          <div className="break-words font-medium text-[#10213e]">
                            {memberNickname || memberUsername}
                          </div>
                          {memberNickname && (
                            <div className="mt-1 break-words text-xs text-[#6e7d97]">账号：{memberUsername}</div>
                          )}
                          <div className="mt-1 break-all font-mono text-[11px] text-[#8b99ae]">{member.user_id}</div>
                        </div>
                        <span className={`w-fit rounded-full border px-2.5 py-1 text-xs font-medium ${roleTone(member.role)}`}>
                          {roleLabel(member.role)}
                        </span>
                        {selectedProjectCanManage && canOperateMember && (
                          <div className="flex items-center gap-2 lg:justify-end">
                            <Button
                              type="button"
                              size="sm"
                              variant="danger"
                              className="min-w-[72px]"
                              aria-label={isCurrentUser ? `不能移出当前账号 ${memberUsername}` : isLastOwner ? `必须保留总负责人 ${memberUsername}` : `移出项目 ${memberUsername}`}
                              title={isCurrentUser ? '不能把当前登录账号移出项目' : isLastOwner ? '项目至少需要保留一名总负责人' : '从项目移除成员'}
                              disabled={isCurrentUser || isLastOwner || deletingUserId === member.user_id}
                              onClick={() => handleRemoveMember(member)}
                            >
                              <Trash2 size={15} aria-hidden={true} />
                              <span>{deletingUserId === member.user_id ? '移除中' : '移出项目'}</span>
                            </Button>
                          </div>
                        )}
                      </div>
                        );
                      })()}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      </main>

      {toast && <Toast message={toast.msg} kind={toast.kind} />}
    </div>
  );
}
