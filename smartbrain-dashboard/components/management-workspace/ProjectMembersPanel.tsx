'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Trash2, UserPlus, Users } from 'lucide-react';

import { Button } from '@/components/Button';
import { EmptyState, LoadingDots, Toast } from '@/components/Feedback';
import { Select } from '@/components/Select';
import {
  addProjectMember,
  ApiError,
  listProjectMemberOptions,
  listProjectMembers,
  Me,
  Project,
  ProjectMember,
  ProjectMemberOption,
  ProjectRole,
  removeProjectMember,
} from '@/lib/api';

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
  if (isLeaderRole(role)) return 'border-brand-500/20 bg-brand-500/10 text-brand-700';
  return 'border-[#17a58a]/20 bg-[#17a58a]/10 text-[#137f6d]';
}

function CompactMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-[76px] rounded-lg border border-[#d7e0ec] bg-white px-3 py-2 shadow-sm">
      <div className="text-base font-semibold leading-none text-[#10213e]">{value}</div>
      <div className="mt-1 text-[11px] font-medium text-[#6e7d97]">{label}</div>
    </div>
  );
}

interface ProjectMembersPanelProps {
  project: Project | null;
  currentUser: Me | null;
  canManage: boolean;
}

export function ProjectMembersPanel({ project, currentUser, canManage }: ProjectMembersPanelProps) {
  const { replace } = useRouter();
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [memberOptions, setMemberOptions] = useState<ProjectMemberOption[]>([]);
  const [memberSearch, setMemberSearch] = useState('');
  const [selectedMemberId, setSelectedMemberId] = useState('');
  const [memberRole, setMemberRole] = useState<ProjectRole>('developer');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: 'info' | 'error' } | null>(null);

  const filteredMemberOptions = useMemo(() => {
    const query = memberSearch.trim().toLocaleLowerCase();
    if (!query) return memberOptions;
    return memberOptions.filter((member) => {
      const fields = [member.nickname, member.display_name, member.username, member.email];
      return fields.some((value) => value?.toLocaleLowerCase().includes(query));
    });
  }, [memberOptions, memberSearch]);

  const canAssignOwner = Boolean(currentUser?.is_system_admin) || project?.role === 'owner';
  const assignableRoleOptions = canAssignOwner
    ? ROLE_OPTIONS
    : ROLE_OPTIONS.filter((option) => option.value !== 'owner');

  const overallLeadCount = useMemo(
    () => members.filter((member) => member.role === 'owner').length,
    [members],
  );
  const projectLeadCount = useMemo(
    () => members.filter((member) => member.role === 'admin').length,
    [members],
  );
  const regularMemberCount = members.filter((member) => !isLeaderRole(member.role)).length;

  async function refresh(projectId: string, includeOptions = canManage) {
    const [memberRows, optionRows] = await Promise.all([
      listProjectMembers(projectId),
      includeOptions ? listProjectMemberOptions(projectId) : Promise.resolve([]),
    ]);
    setMembers(Array.isArray(memberRows) ? memberRows : []);
    setMemberOptions(Array.isArray(optionRows) ? optionRows : []);
  }

  useEffect(() => {
    let active = true;
    setMembers([]);
    setMemberOptions([]);
    setMemberSearch('');
    setSelectedMemberId('');
    if (!project) {
      setLoading(false);
      return () => {
        active = false;
      };
    }

    setLoading(true);
    Promise.all([
      listProjectMembers(project.id),
      canManage ? listProjectMemberOptions(project.id) : Promise.resolve([]),
    ])
      .then(([memberRows, optionRows]) => {
        if (!active) return;
        setMembers(Array.isArray(memberRows) ? memberRows : []);
        setMemberOptions(Array.isArray(optionRows) ? optionRows : []);
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          replace('/login');
          return;
        }
        setToast({ msg: error instanceof Error ? error.message : '加载项目成员失败', kind: 'error' });
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [canManage, project, replace]);

  async function handleAddMember(event: FormEvent) {
    event.preventDefault();
    if (!project || !canManage || !selectedMemberId || saving) return;
    setSaving(true);
    try {
      await addProjectMember(project.id, { user_id: selectedMemberId, role: memberRole });
      setMemberSearch('');
      setSelectedMemberId('');
      await refresh(project.id, true);
      setToast({ msg: '成员已添加或更新', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '添加成员失败', kind: 'error' });
    } finally {
      setSaving(false);
    }
  }

  async function handleRemoveMember(member: ProjectMember) {
    if (!project || !canManage || deletingUserId || member.user_id === currentUser?.user_id) return;
    if (!window.confirm(`确认将 ${member.username || member.email} 从当前项目移除？团队账号和历史记录不会受影响。`)) return;
    setDeletingUserId(member.user_id);
    try {
      await removeProjectMember(project.id, member.user_id);
      await refresh(project.id, true);
      setToast({ msg: '成员已从项目移除', kind: 'info' });
    } catch (error: unknown) {
      setToast({ msg: error instanceof Error ? error.message : '移出项目失败', kind: 'error' });
    } finally {
      setDeletingUserId(null);
    }
  }

  if (!project) {
    return (
      <section className="rounded-lg border border-[#d7e0ec] bg-white p-4 shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
        <EmptyState title="请选择或创建项目" hint="选中项目后，可在这里查看和维护项目成员。" />
      </section>
    );
  }

  return (
    <section className="min-w-0 overflow-hidden rounded-lg border border-[#d7e0ec] bg-white shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
      <div className="border-b border-[#d7e0ec] bg-[#f7faff] px-4 py-3 md:px-5">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
            <Users size={20} aria-hidden={true} />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="break-words text-lg font-semibold leading-tight text-[#10213e]">{project.name} 项目成员</h2>
            <p className="mt-0.5 text-sm text-[#6e7d97]">
              {canManage ? '从已启用团队账号中添加成员，并维护项目角色。' : '查看当前项目的负责人和成员名单。'}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-center sm:grid-cols-4">
            <CompactMetric label="成员" value={members.length} />
            <CompactMetric label="总负责人" value={overallLeadCount} />
            <CompactMetric label="项目负责人" value={projectLeadCount} />
            <CompactMetric label="项目成员" value={regularMemberCount} />
          </div>
        </div>
      </div>

      {canManage && (
        <form
          aria-label="添加项目成员"
          onSubmit={handleAddMember}
          className="grid min-w-0 grid-cols-1 gap-3 border-b border-[#d7e0ec] p-4 md:grid-cols-2 xl:grid-cols-[minmax(180px,0.8fr)_minmax(0,1fr)_minmax(140px,0.45fr)_140px] md:px-5"
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
              placeholder="输入姓名、昵称或账号"
              disabled={saving}
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
                label: member.nickname ? `${member.nickname}（账号：${member.username}）` : member.username,
              }))}
              disabled={saving}
            />
          </label>
          <label className="min-w-0">
            <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">成员角色</span>
            <Select
              aria-label="成员角色"
              value={memberRole}
              onChange={(value) => setMemberRole(value as ProjectRole)}
              options={assignableRoleOptions}
              disabled={saving}
            />
          </label>
          <div className="flex min-w-0 items-end md:col-span-2 xl:col-span-1">
            <Button type="submit" className="w-full" disabled={!selectedMemberId || saving}>
              <UserPlus size={16} aria-hidden={true} />
              {saving ? <LoadingDots /> : '添加成员'}
            </Button>
          </div>
          <p className="text-xs text-[#6e7d97] md:col-span-2 xl:col-span-4">这里只能选择成员管理中已启用的团队账号。</p>
        </form>
      )}

      {loading ? (
        <div className="py-12 text-center text-[#8b99ae]"><LoadingDots /></div>
      ) : members.length === 0 ? (
        <div className="p-4"><EmptyState title="暂无项目成员" /></div>
      ) : (
        <div>
          <div className={`hidden gap-4 border-b border-[#d7e0ec] bg-[#f7f9fc] px-4 py-2.5 text-xs font-semibold text-[#6e7d97] md:px-5 lg:grid ${canManage ? 'grid-cols-[minmax(220px,1.35fr)_140px_140px]' : 'grid-cols-[minmax(220px,1.35fr)_160px]'}`}>
            <div>成员</div>
            <div>角色</div>
            {canManage && <div className="text-right">操作</div>}
          </div>
          <div className="max-h-[440px] divide-y divide-[#d7e0ec] overflow-y-auto [scrollbar-gutter:stable]">
            {members.map((member) => {
              const isCurrentUser = member.user_id === currentUser?.user_id;
              const canOperateMember = canAssignOwner || member.role !== 'owner';
              const isLastOwner = member.role === 'owner' && overallLeadCount <= 1;
              const memberUsername = member.username || member.email.split('@', 1)[0];
              const memberNickname = member.nickname?.trim();
              return (
                <div key={member.user_id} className="px-4 py-3 text-sm hover:bg-[#f7faff] md:px-5">
                  <div className={`grid grid-cols-1 gap-3 lg:items-center ${canManage ? 'lg:grid-cols-[minmax(220px,1.35fr)_140px_140px]' : 'lg:grid-cols-[minmax(220px,1.35fr)_160px]'}`}>
                    <div className="min-w-0">
                      <div className="break-words font-medium text-[#10213e]">{memberNickname || memberUsername}</div>
                      {memberNickname && <div className="mt-1 break-words text-xs text-[#6e7d97]">账号：{memberUsername}</div>}
                      <div className="mt-1 break-all font-mono text-[11px] text-[#8b99ae]">{member.user_id}</div>
                    </div>
                    <span className={`w-fit rounded-full border px-2.5 py-1 text-xs font-medium ${roleTone(member.role)}`}>
                      {roleLabel(member.role)}
                    </span>
                    {canManage && canOperateMember && (
                      <div className="flex items-center gap-2 lg:justify-end">
                        <Button
                          type="button"
                          size="sm"
                          variant="danger"
                          className="min-w-[96px]"
                          aria-label={isCurrentUser ? `不能移出当前账号 ${memberUsername}` : isLastOwner ? `必须保留总负责人 ${memberUsername}` : `移出项目 ${memberUsername}`}
                          title={isCurrentUser ? '不能把当前登录账号移出项目' : isLastOwner ? '项目至少需要保留一名总负责人' : '从项目移除成员'}
                          disabled={isCurrentUser || isLastOwner || deletingUserId === member.user_id}
                          onClick={() => handleRemoveMember(member)}
                        >
                          <Trash2 size={15} aria-hidden={true} />
                          {deletingUserId === member.user_id ? '移除中' : '移出项目'}
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {toast && <Toast message={toast.msg} kind={toast.kind} />}
    </section>
  );
}
