'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { KeyRound, ShieldCheck, Trash2, UserPlus } from 'lucide-react';
import {
  addProjectMember,
  ApiError,
  Department,
  DepartmentId,
  getMe,
  listProjectMemoryDepartments,
  listProjectMembers,
  listProjectCatalog,
  Me,
  Project,
  ProjectMember,
  ProjectRole,
  removeProjectMember,
  resetProjectMemberPassword,
} from '@/lib/api';
import { Button } from '@/components/Button';
import { EmptyState, LoadingDots, Toast } from '@/components/Feedback';
import { Input } from '@/components/Input';
import { Select } from '@/components/Select';

const ROLE_OPTIONS: { value: ProjectRole; label: string }[] = [
  { value: 'developer', label: '项目成员' },
  { value: 'owner', label: '项目负责人' },
];

function isLeaderRole(role: ProjectRole) {
  return role === 'owner' || role === 'admin';
}

function roleLabel(role: ProjectRole) {
  return isLeaderRole(role) ? '项目负责人' : '项目成员';
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

export default function MembersPage() {
  const router = useRouter();
  const didInitialLoad = useRef(false);
  const [me, setMe] = useState<Me | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [departmentId, setDepartmentId] = useState<DepartmentId>('research');
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [memberIdentifier, setMemberIdentifier] = useState('');
  const [memberRole, setMemberRole] = useState<ProjectRole>('developer');
  const [loading, setLoading] = useState(true);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const [passwordTarget, setPasswordTarget] = useState<ProjectMember | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [resettingPassword, setResettingPassword] = useState(false);
  const [toast, setToast] = useState<{ msg: string; kind: 'info' | 'error' } | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) || null,
    [projects, selectedProjectId],
  );

  const filteredProjects = useMemo(
    () => projects.filter((project) => (project.department_id || 'research') === departmentId),
    [departmentId, projects],
  );

  const departmentOptions = useMemo(
    () => departments.map((department) => ({ value: department.id, label: department.name })),
    [departments],
  );

  const selectedProjectCanManage = canManageProject(selectedProject);

  const privilegedCount = useMemo(
    () => members.filter((member) => isLeaderRole(member.role)).length,
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

  useEffect(() => {
    if (didInitialLoad.current) return;
    didInitialLoad.current = true;
    (async () => {
      setLoading(true);
      try {
        const [currentUser, departmentRows, projectRows] = await Promise.all([
          getMe(),
          listProjectMemoryDepartments(),
          listProjectCatalog(),
        ]);
        setMe(currentUser);
        setDepartments(departmentRows);
        setProjects(projectRows);
        const firstDepartment = departmentRows[0]?.id || 'research';
        setDepartmentId(firstDepartment);
        const firstProject =
          projectRows.find((project) => (project.department_id || 'research') === firstDepartment) ||
          projectRows[0];
        if (firstProject) {
          setSelectedProjectId(firstProject.id);
          await loadMembers(firstProject.id);
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
  }, [loadMembers, router]);

  async function handleProjectChange(projectId: string) {
    setSelectedProjectId(projectId);
    await loadMembers(projectId);
  }

  async function handleDepartmentChange(nextDepartmentId: string) {
    const next = nextDepartmentId as DepartmentId;
    setDepartmentId(next);
    const nextProject = projects.find((project) => (project.department_id || 'research') === next);
    setMembers([]);
    setPasswordTarget(null);
    setNewPassword('');
    setSelectedProjectId(nextProject?.id || '');
    if (nextProject) {
      await loadMembers(nextProject.id);
    }
  }

  async function handleAddMember(e: React.FormEvent) {
    e.preventDefault();
    const identifier = memberIdentifier.trim();
    if (!selectedProjectCanManage || !selectedProjectId || !identifier || saving) return;
    setSaving(true);
    try {
      await addProjectMember(selectedProjectId, {
        identifier,
        role: memberRole,
      });
      setMemberIdentifier('');
      await loadMembers(selectedProjectId);
      setToast({ msg: '成员已添加或更新', kind: 'info' });
    } catch (e: any) {
      setToast({ msg: e?.message || '添加成员失败', kind: 'error' });
    } finally {
      setSaving(false);
    }
  }

  async function handleRemoveMember(member: ProjectMember) {
    if (!selectedProjectCanManage || !selectedProjectId || deletingUserId) return;
    if (!window.confirm(`确认删除成员 ${member.email}？`)) return;
    setDeletingUserId(member.user_id);
    try {
      await removeProjectMember(selectedProjectId, member.user_id);
      if (passwordTarget?.user_id === member.user_id) {
        setPasswordTarget(null);
        setNewPassword('');
      }
      await loadMembers(selectedProjectId);
      setToast({ msg: '成员已删除', kind: 'info' });
    } catch (e: any) {
      setToast({ msg: e?.message || '删除成员失败', kind: 'error' });
    } finally {
      setDeletingUserId(null);
    }
  }

  function openPasswordEditor(member: ProjectMember) {
    if (!selectedProjectCanManage) return;
    setPasswordTarget(member);
    setNewPassword('');
  }

  async function handleResetPassword(e: React.FormEvent) {
    e.preventDefault();
    const password = newPassword.trim();
    if (!selectedProjectCanManage || !selectedProjectId || !passwordTarget || password.length < 6 || resettingPassword) return;
    setResettingPassword(true);
    try {
      await resetProjectMemberPassword(selectedProjectId, passwordTarget.user_id, password);
      setPasswordTarget(null);
      setNewPassword('');
      setToast({ msg: '登录密码已修改', kind: 'info' });
    } catch (e: any) {
      setToast({ msg: e?.message || '修改密码失败', kind: 'error' });
    } finally {
      setResettingPassword(false);
    }
  }

  return (
    <div className="flex h-screen flex-col bg-[#eef3f9] text-[#10213e]">
      <header className="sticky top-0 z-10 border-b border-[#d7e0ec] bg-white/95 px-4 py-4 backdrop-blur md:px-6">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-bold text-brand-600">ADMIN WORKBENCH</div>
            <h1 className="mt-1 text-[26px] font-semibold leading-tight tracking-normal text-[#10213e]">成员管理</h1>
            <p className="mt-1 text-sm text-[#6e7d97]">维护项目成员、角色权限和登录凭据。</p>
          </div>
          {me && (
            <div className="flex h-10 w-full items-center gap-2 rounded-lg border border-[#d7e0ec] bg-[#f7f9fc] px-3 text-xs text-[#6e7d97] sm:w-auto">
              <ShieldCheck size={14} className={selectedProjectCanManage ? 'text-[#17a58a]' : 'text-[#8b99ae]'} aria-hidden={true} />
              <span className="max-w-[220px] truncate">{me.email}</span>
              <span className={selectedProjectCanManage ? 'text-[#137f6d]' : 'text-[#6e7d97]'}>
                {selectedProjectCanManage ? '项目负责人' : '成员列表可见'}
              </span>
            </div>
          )}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6 md:px-6">
        <div className="mx-auto grid max-w-[1320px] gap-5">
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
                      ? '先按部门定位项目，再维护成员权限和登录密码。'
                      : '同项目成员可以查看负责人和成员名单。'}
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

            <div className="p-4 md:p-5">
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-[160px_minmax(220px,300px)_minmax(0,1fr)]">
                <label className="block">
                  <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">选择部门</span>
                  <Select
                    value={departmentId}
                    onChange={handleDepartmentChange}
                    placeholder={loading ? '加载中' : '暂无部门'}
                    disabled={loading || departments.length === 0}
                    options={departmentOptions}
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">选择项目</span>
                  <Select
                    value={selectedProjectId}
                    onChange={handleProjectChange}
                    placeholder={loading ? '加载中' : '当前部门暂无项目'}
                    disabled={loading || filteredProjects.length === 0}
                    options={filteredProjects.map((project) => ({
                      value: project.id,
                      label: `${project.name} (${project.environment})`,
                    }))}
                  />
                </label>

                {selectedProjectCanManage && (
                  <form onSubmit={handleAddMember} className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(180px,1fr)_150px_112px]">
                    <label className="block">
                      <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">用户名或邮箱</span>
                      <Input
                        value={memberIdentifier}
                        onChange={(e) => setMemberIdentifier(e.target.value)}
                        placeholder="test2 或 test2@local.dev"
                        disabled={!selectedProjectId || saving}
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">成员角色</span>
                      <Select
                        value={memberRole}
                        onChange={(value) => setMemberRole(value as ProjectRole)}
                        options={ROLE_OPTIONS}
                        disabled={!selectedProjectId || saving}
                      />
                    </label>
                    <div className="flex items-end">
                      <Button
                        type="submit"
                        className="w-full"
                        disabled={!selectedProjectId || !memberIdentifier.trim() || saving}
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
                  <>
                    <span>短用户名会自动识别为本地账号邮箱，例如 test2。</span>
                    <span>账号不存在时会自动创建，初始密码 123456。</span>
                  </>
                ) : (
                  <span>此页面只展示同项目成员和角色，不开放成员管理操作。</span>
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
            ) : filteredProjects.length === 0 ? (
              <EmptyState title="当前部门暂无可查看项目" hint="请联系项目负责人把你加入对应项目" />
            ) : members.length === 0 ? (
              <EmptyState title="暂无成员" />
            ) : (
              <div>
                <div className={`hidden gap-4 border-b border-[#d7e0ec] bg-[#f7f9fc] px-4 py-2.5 text-xs font-semibold text-[#6e7d97] md:px-5 lg:grid ${selectedProjectCanManage ? 'grid-cols-[minmax(220px,1.35fr)_120px_220px]' : 'grid-cols-[minmax(220px,1.35fr)_160px]'}`}>
                  <div>成员账号</div>
                  <div>角色</div>
                  {selectedProjectCanManage && <div className="text-right">操作</div>}
                </div>
                <div className="divide-y divide-[#d7e0ec]">
                  {members.map((member) => (
                    <div key={member.user_id} className="px-4 py-3 text-sm hover:bg-[#f7faff] md:px-5">
                      {(() => {
                        const isCurrentUser = member.user_id === me?.user_id;
                        return (
                      <div className={`grid grid-cols-1 gap-3 lg:items-center ${selectedProjectCanManage ? 'lg:grid-cols-[minmax(220px,1.35fr)_120px_220px]' : 'lg:grid-cols-[minmax(220px,1.35fr)_160px]'}`}>
                        <div className="min-w-0">
                          <div className="break-words font-medium text-[#10213e]">
                            {member.display_name || member.nickname || member.email}
                          </div>
                          {(member.display_name || member.nickname) && (
                            <div className="mt-0.5 break-all text-xs text-[#6e7d97]">{member.email}</div>
                          )}
                          <div className="mt-1 break-all font-mono text-[11px] text-[#8b99ae]">{member.user_id}</div>
                        </div>
                        <span className={`w-fit rounded-full border px-2.5 py-1 text-xs font-medium ${roleTone(member.role)}`}>
                          {roleLabel(member.role)}
                        </span>
                        {selectedProjectCanManage && (
                          <div className="flex items-center gap-2 lg:justify-end">
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              className="min-w-[88px]"
                              aria-label={`修改 ${member.email} 密码`}
                              title={`修改 ${member.email} 密码`}
                              onClick={() => openPasswordEditor(member)}
                            >
                              <KeyRound size={15} aria-hidden={true} />
                              <span>改密码</span>
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="danger"
                              className="min-w-[72px]"
                              aria-label={isCurrentUser ? `不能删除当前账号 ${member.email}` : `删除 ${member.email}`}
                              title={isCurrentUser ? '不能删除当前登录账号' : `删除 ${member.email}`}
                              disabled={isCurrentUser || deletingUserId === member.user_id}
                              onClick={() => handleRemoveMember(member)}
                            >
                              <Trash2 size={15} aria-hidden={true} />
                              <span>{deletingUserId === member.user_id ? '删除中' : '删除'}</span>
                            </Button>
                          </div>
                        )}
                      </div>
                        );
                      })()}

                      {selectedProjectCanManage && passwordTarget?.user_id === member.user_id && (
                        <form
                          onSubmit={handleResetPassword}
                          className="mt-3 grid grid-cols-1 gap-3 rounded-lg border border-brand-500/20 bg-brand-500/5 p-3 sm:grid-cols-[1fr_120px_88px]"
                        >
                          <label className="block">
                            <span className="mb-1 block text-xs font-medium text-[#253655]">新登录密码</span>
                            <Input
                              type="password"
                              value={newPassword}
                              onChange={(e) => setNewPassword(e.target.value)}
                              placeholder="至少 6 位"
                              minLength={6}
                              autoComplete="new-password"
                            />
                          </label>
                          <div className="flex items-end">
                            <Button
                              type="submit"
                              size="sm"
                              className="w-full"
                              disabled={newPassword.trim().length < 6 || resettingPassword}
                            >
                              {resettingPassword ? <LoadingDots /> : '保存新密码'}
                            </Button>
                          </div>
                          <div className="flex items-end">
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              className="w-full"
                              onClick={() => {
                                setPasswordTarget(null);
                                setNewPassword('');
                              }}
                              disabled={resettingPassword}
                            >
                              取消
                            </Button>
                          </div>
                        </form>
                      )}
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
