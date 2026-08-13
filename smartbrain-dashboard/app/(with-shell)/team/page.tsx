'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { KeyRound, PencilLine, RotateCcw, ShieldCheck, UserPlus, UserX } from 'lucide-react';

import {
  ApiError,
  createTeamMember,
  deactivateTeamMember,
  getMe,
  listTeamMembers,
  reactivateTeamMember,
  renameTeamMemberUsername,
  resetTeamMemberPassword,
  type Me,
  type TeamMember,
} from '@/lib/api';
import { Button } from '@/components/Button';
import { EmptyState, LoadingDots, Toast } from '@/components/Feedback';
import { Input } from '@/components/Input';


function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}


export default function TeamPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [username, setUsername] = useState('');
  const [nickname, setNickname] = useState('');
  const [password, setPassword] = useState('');
  const [creating, setCreating] = useState(false);
  const [busyUserId, setBusyUserId] = useState<string | null>(null);
  const [usernameTarget, setUsernameTarget] = useState<TeamMember | null>(null);
  const [newUsername, setNewUsername] = useState('');
  const [passwordTarget, setPasswordTarget] = useState<TeamMember | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [toast, setToast] = useState<{ msg: string; kind: 'info' | 'error' } | null>(null);

  const activeCount = useMemo(() => members.filter((member) => member.is_active).length, [members]);
  const inactiveCount = members.length - activeCount;

  const refresh = useCallback(async () => {
    setMembers(await listTeamMembers());
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const current = await getMe();
        if (cancelled) return;
        setMe(current);
        if (!current.is_system_admin) {
          router.replace('/chat');
          return;
        }
        const rows = await listTeamMembers();
        if (!cancelled) setMembers(rows);
      } catch (error) {
        if (!cancelled) setToast({ msg: errorMessage(error, '加载团队成员失败'), kind: 'error' });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleCreate() {
    const normalizedUsername = username.trim().toLowerCase();
    if (!normalizedUsername || password.length < 6 || creating) return;
    setCreating(true);
    try {
      await createTeamMember({
        username: normalizedUsername,
        nickname: nickname.trim(),
        password,
      });
      setUsername('');
      setNickname('');
      setPassword('');
      await refresh();
      setToast({ msg: `团队成员 ${normalizedUsername} 已创建`, kind: 'info' });
    } catch (error) {
      setToast({ msg: errorMessage(error, '创建团队成员失败'), kind: 'error' });
    } finally {
      setCreating(false);
    }
  }

  async function handleDeactivate(member: TeamMember) {
    if (!window.confirm(`确认将 ${member.display_name || member.username} 移出智慧大脑团队？该账号会立即停止登录，并从所有项目移除。`)) return;
    setBusyUserId(member.user_id);
    try {
      await deactivateTeamMember(member.user_id);
      await refresh();
      setToast({ msg: `${member.username} 已移出团队，历史记录已保留`, kind: 'info' });
    } catch (error) {
      setToast({ msg: errorMessage(error, '移出团队失败'), kind: 'error' });
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleReactivate(member: TeamMember) {
    setBusyUserId(member.user_id);
    try {
      await reactivateTeamMember(member.user_id);
      await refresh();
      setToast({ msg: `${member.username} 已恢复为团队成员`, kind: 'info' });
    } catch (error) {
      setToast({ msg: errorMessage(error, '恢复团队成员失败'), kind: 'error' });
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleRename(member: TeamMember) {
    const normalized = newUsername.trim().toLowerCase();
    if (!normalized || busyUserId) return;
    setBusyUserId(member.user_id);
    try {
      await renameTeamMemberUsername(member.user_id, normalized);
      setUsernameTarget(null);
      setNewUsername('');
      await refresh();
      setToast({ msg: `登录用户名已修改为 ${normalized}`, kind: 'info' });
    } catch (error) {
      setToast({ msg: errorMessage(error, '修改用户名失败'), kind: 'error' });
    } finally {
      setBusyUserId(null);
    }
  }

  async function handleResetPassword(member: TeamMember) {
    if (newPassword.length < 6 || busyUserId) return;
    setBusyUserId(member.user_id);
    try {
      await resetTeamMemberPassword(member.user_id, newPassword);
      setPasswordTarget(null);
      setNewPassword('');
      setToast({ msg: `${member.username} 的登录密码已更新`, kind: 'info' });
    } catch (error) {
      setToast({ msg: errorMessage(error, '重置密码失败'), kind: 'error' });
    } finally {
      setBusyUserId(null);
    }
  }

  if (!loading && me && !me.is_system_admin) return null;

  return (
    <div className="flex h-screen flex-col bg-[#eef3f9] text-[#10213e]">
      {toast && <Toast message={toast.msg} kind={toast.kind} />}
      <header className="border-b border-[#d7e0ec] bg-white/95 px-4 py-4 md:px-6">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-bold text-brand-600">TEAM DIRECTORY</div>
            <h1 className="mt-1 text-[26px] font-semibold leading-tight">团队管理</h1>
            <p className="mt-1 text-sm text-[#6e7d97]">统一维护智慧大脑账号；停用成员时保留全部历史记录。</p>
          </div>
          <div className="flex items-center gap-3 text-sm text-[#6e7d97]">
            <span>启用 {activeCount}</span>
            <span>停用 {inactiveCount}</span>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6 md:px-6">
        <div className="mx-auto grid max-w-[1320px] gap-5">
          <section className="rounded-lg border border-[#d7e0ec] bg-white shadow-sm">
            <div className="flex items-center gap-3 border-b border-[#d7e0ec] bg-[#f7faff] px-4 py-3 md:px-5">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                <UserPlus size={20} aria-hidden="true" />
              </div>
              <div>
                <h2 className="text-lg font-semibold">新增团队成员</h2>
                <p className="mt-0.5 text-sm text-[#6e7d97]">这里只创建智慧大脑账号，不自动加入任何项目。</p>
              </div>
            </div>
            <div className="grid gap-4 p-4 md:grid-cols-[1fr_1fr_1fr_auto] md:items-end md:p-5">
              <label className="grid gap-1.5 text-sm font-medium">
                用户名
                <Input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="例如 zhangsan" />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                昵称
                <Input value={nickname} onChange={(event) => setNickname(event.target.value)} placeholder="例如 张三" />
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                初始密码
                <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="至少 6 位" autoComplete="new-password" />
              </label>
              <Button disabled={!username.trim() || password.length < 6 || creating} onClick={handleCreate}>
                <UserPlus size={16} aria-hidden="true" />
                {creating ? '创建中' : '创建团队成员'}
              </Button>
            </div>
          </section>

          <section className="rounded-lg border border-[#d7e0ec] bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-[#d7e0ec] px-4 py-3 md:px-5">
              <div>
                <h2 className="text-lg font-semibold">团队成员</h2>
                <p className="mt-0.5 text-sm text-[#6e7d97]">账号级操作统一在此完成；项目归属请前往成员管理。</p>
              </div>
              <ShieldCheck size={20} className="text-[#17a58a]" aria-hidden="true" />
            </div>

            {loading ? (
              <div className="p-8"><LoadingDots /></div>
            ) : members.length === 0 ? (
              <EmptyState title="暂无团队成员" hint="创建第一个智慧大脑团队账号。" />
            ) : (
              <div className="divide-y divide-[#e5ebf3]">
                {members.map((member) => {
                  const isCurrentUser = member.user_id === me?.user_id;
                  const busy = busyUserId === member.user_id;
                  return (
                    <div key={member.user_id} className={`px-4 py-4 md:px-5 ${member.is_active ? '' : 'bg-[#f7f9fc]'}`}>
                      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-semibold">{member.display_name || member.username}</span>
                            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${member.is_active ? 'bg-[#e8f7f3] text-[#137f6d]' : 'bg-[#eef1f5] text-[#6e7d97]'}`}>
                              {member.is_active ? '已启用' : '已停用'}
                            </span>
                            {member.is_system_admin && <span className="rounded-full bg-brand-500/10 px-2 py-0.5 text-xs font-medium text-brand-700">系统管理员</span>}
                          </div>
                          {member.nickname && <div className="mt-1 text-xs text-[#6e7d97]">账号：{member.username}</div>}
                          {!member.nickname && <div className="mt-1 text-xs text-[#6e7d97]">账号：{member.username}</div>}
                          <div className="mt-1 text-xs text-[#8b99ae]">已加入 {member.project_count} 个项目</div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            aria-label={`修改 ${member.username} 用户名`}
                            disabled={busy}
                            onClick={() => {
                              setUsernameTarget(member);
                              setNewUsername(member.username);
                              setPasswordTarget(null);
                            }}
                          >
                            <PencilLine size={15} aria-hidden="true" />改用户名
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            aria-label={`修改 ${member.username} 密码`}
                            disabled={busy}
                            onClick={() => {
                              setPasswordTarget(member);
                              setNewPassword('');
                              setUsernameTarget(null);
                            }}
                          >
                            <KeyRound size={15} aria-hidden="true" />改密码
                          </Button>
                          {member.is_active ? (
                            !member.is_system_admin && !isCurrentUser && (
                              <Button size="sm" variant="danger" aria-label={`移出团队 ${member.username}`} disabled={busy} onClick={() => handleDeactivate(member)}>
                                <UserX size={15} aria-hidden="true" />移出团队
                              </Button>
                            )
                          ) : (
                            <Button size="sm" aria-label={`恢复成员 ${member.username}`} disabled={busy} onClick={() => handleReactivate(member)}>
                              <RotateCcw size={15} aria-hidden="true" />恢复成员
                            </Button>
                          )}
                        </div>
                      </div>

                      {usernameTarget?.user_id === member.user_id && (
                        <div className="mt-3 flex flex-wrap items-end gap-2 rounded-lg border border-[#d7e0ec] bg-[#f7faff] p-3">
                          <label className="grid min-w-[240px] flex-1 gap-1.5 text-sm font-medium">
                            新登录用户名
                            <Input value={newUsername} onChange={(event) => setNewUsername(event.target.value)} />
                          </label>
                          <Button disabled={!newUsername.trim() || busy} onClick={() => handleRename(member)}>保存用户名</Button>
                          <Button variant="secondary" onClick={() => setUsernameTarget(null)}>取消</Button>
                        </div>
                      )}

                      {passwordTarget?.user_id === member.user_id && (
                        <div className="mt-3 flex flex-wrap items-end gap-2 rounded-lg border border-[#d7e0ec] bg-[#f7faff] p-3">
                          <label className="grid min-w-[240px] flex-1 gap-1.5 text-sm font-medium">
                            新登录密码
                            <Input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" />
                          </label>
                          <Button disabled={newPassword.length < 6 || busy} onClick={() => handleResetPassword(member)}>保存新密码</Button>
                          <Button variant="secondary" onClick={() => setPasswordTarget(null)}>取消</Button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
