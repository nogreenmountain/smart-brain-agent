'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, FolderKanban, KeyRound, ShieldCheck, UserRound } from 'lucide-react';

import { Button } from '@/components/Button';
import { Input } from '@/components/Input';
import { PageBody, PageHeader, PageShell } from '@/components/PageLayout';
import {
  ApiError,
  changeMyPassword,
  getMe,
  listProjectMemoryDepartments,
  listProjects,
  updateMyProfile,
  type Department,
  type Me,
  type Project,
} from '@/lib/api';

type Notice = { kind: 'success' | 'error'; text: string } | null;

export default function ProfilePage() {
  const [email, setEmail] = useState('');
  const [me, setMe] = useState<Me | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [projectWindowStart, setProjectWindowStart] = useState(0);
  const [nickname, setNickname] = useState('');
  const [aiDetailVisibleToAdmin, setAiDetailVisibleToAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [profileNotice, setProfileNotice] = useState<Notice>(null);
  const [passwordNotice, setPasswordNotice] = useState<Notice>(null);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then(async (me) => {
        if (cancelled) return;
        setMe(me);
        setEmail(me.email);
        setNickname(me.nickname || '');
        setAiDetailVisibleToAdmin(Boolean(me.ai_detail_visible_to_admin));
        if (me.can_manage_projects === false) {
          const [projectRows, departmentRows] = await Promise.all([
            listProjects(),
            listProjectMemoryDepartments(true),
          ]);
          if (cancelled) return;
          setProjects(projectRows);
          setDepartments(departmentRows);
          setSelectedProjectId(projectRows[0]?.id || '');
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setProfileNotice({ kind: 'error', text: error?.message || '个人资料加载失败' });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) || projects[0] || null,
    [projects, selectedProjectId],
  );
  const visibleProjects = projects.slice(projectWindowStart, projectWindowStart + 3);
  const canShowPreviousProjects = projectWindowStart > 0;
  const canShowNextProjects = projectWindowStart + 3 < projects.length;

  function departmentPath(project: Project): string {
    const department = departments.find((item) => item.id === project.department_id);
    if (!department) return '未分类';
    const parent = department.parent_id
      ? departments.find((item) => item.id === department.parent_id)
      : null;
    return parent ? `${parent.name} / ${department.name}` : department.name;
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setSavingProfile(true);
    setProfileNotice(null);
    try {
      const updated = await updateMyProfile(
        nickname.trim() || null,
        aiDetailVisibleToAdmin,
      );
      setNickname(updated.nickname || '');
      setAiDetailVisibleToAdmin(Boolean(updated.ai_detail_visible_to_admin));
      setProfileNotice({ kind: 'success', text: '个人设置已保存' });
    } catch (error) {
      setProfileNotice({ kind: 'error', text: error instanceof Error ? error.message : '昵称保存失败' });
    } finally {
      setSavingProfile(false);
    }
  }

  async function savePassword(event: FormEvent) {
    event.preventDefault();
    setPasswordNotice(null);
    if (newPassword !== confirmPassword) {
      setPasswordNotice({ kind: 'error', text: '两次输入的新密码不一致' });
      return;
    }
    setChangingPassword(true);
    try {
      await changeMyPassword(currentPassword, newPassword);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setPasswordNotice({ kind: 'success', text: '密码已修改' });
    } catch (error) {
      const text =
        error instanceof ApiError && error.status === 400
          ? '当前密码不正确'
          : error instanceof Error
            ? error.message
            : '密码修改失败';
      setPasswordNotice({ kind: 'error', text });
    } finally {
      setChangingPassword(false);
    }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="账号设置"
        icon={UserRound}
        title="个人中心"
        description="维护成员展示昵称、AI 记录隐私和当前账号密码。"
      />
      <PageBody contentClassName="grid max-w-[1100px] gap-5 lg:grid-cols-2">
        {me?.can_manage_projects === false && (
          <section className="rounded-lg border border-[#d7e0ec] bg-white shadow-[0_10px_24px_rgba(15,35,66,0.04)] lg:col-span-2">
            <div className="flex flex-wrap items-center gap-3 border-b border-[#d7e0ec] bg-[#f7faff] px-5 py-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
                <FolderKanban size={20} aria-hidden="true" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-lg font-semibold text-[#10213e]">我的参与项目</h2>
                <p className="mt-0.5 text-sm text-[#6e7d97]">这里只列出你作为直接项目成员参与的项目，每次显示三个。</p>
              </div>
              {projects.length > 3 && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    aria-label="上一组项目"
                    disabled={!canShowPreviousProjects}
                    onClick={() => setProjectWindowStart((current) => Math.max(0, current - 3))}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[#d7e0ec] text-[#50627b] hover:bg-white disabled:opacity-40"
                  >
                    <ChevronLeft size={17} aria-hidden="true" />
                  </button>
                  <span className="text-xs text-[#6e7d97]">{Math.floor(projectWindowStart / 3) + 1} / {Math.ceil(projects.length / 3)}</span>
                  <button
                    type="button"
                    aria-label="下一组项目"
                    disabled={!canShowNextProjects}
                    onClick={() => setProjectWindowStart((current) => Math.min(projects.length - 1, current + 3))}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[#d7e0ec] text-[#50627b] hover:bg-white disabled:opacity-40"
                  >
                    <ChevronRight size={17} aria-hidden="true" />
                  </button>
                </div>
              )}
            </div>
            {projects.length > 0 ? (
              <div className="p-5">
                <div className="grid gap-3 md:grid-cols-3">
                  {visibleProjects.map((project) => (
                    <button
                      key={project.id}
                      type="button"
                      onClick={() => setSelectedProjectId(project.id)}
                      className={`min-w-0 rounded-lg border p-4 text-left transition-colors ${
                        selectedProject?.id === project.id
                          ? 'border-brand-500/35 bg-brand-500/10'
                          : 'border-[#d7e0ec] bg-white hover:bg-[#f7faff]'
                      }`}
                    >
                      <span className="block truncate text-sm font-semibold text-[#10213e]">{project.name}</span>
                      <span className="mt-2 block truncate text-xs text-[#6e7d97]">{departmentPath(project)}</span>
                      <span className="mt-3 inline-flex rounded-full border border-[#d7e0ec] bg-white px-2.5 py-1 text-[11px] font-medium text-[#50627b]">
                        {project.completed_at ? '已结项' : '进行中'}
                      </span>
                    </button>
                  ))}
                </div>

                {selectedProject && (
                  <div className="mt-5 overflow-hidden rounded-lg border border-[#d7e0ec]">
                    <div className="border-b border-[#d7e0ec] bg-[#10213e] px-5 py-4 text-white">
                      <h3 className="text-sm font-semibold tracking-[0.08em]">PROJECT PROFILE</h3>
                      <h2 className="mt-2 break-words text-xl font-semibold">{selectedProject.name}</h2>
                      <p className="mt-1 text-sm text-white/70">只读项目概览</p>
                    </div>
                    <dl className="grid gap-px bg-[#d7e0ec] sm:grid-cols-2 lg:grid-cols-4">
                      <ProfileDatum label="项目分类" value={departmentPath(selectedProject)} />
                      <ProfileDatum label="我的角色" value={projectRoleLabel(selectedProject.role)} />
                      <ProfileDatum label="创建日期" value={formatDate(selectedProject.created_at)} icon={<CalendarDays size={14} aria-hidden="true" />} />
                      <ProfileDatum label="结项状态" value={selectedProject.completed_at ? `已结项 · ${formatDate(selectedProject.completed_at)}` : '进行中'} />
                    </dl>
                  </div>
                )}
              </div>
            ) : (
              <div className="px-5 py-10 text-center text-sm text-[#6e7d97]">你目前还没有直接参与的项目。</div>
            )}
          </section>
        )}

        <section className="rounded-lg border border-[#d7e0ec] bg-white p-5 shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
          <div className="flex items-center gap-2">
            <UserRound size={18} className="text-brand-600" aria-hidden="true" />
            <h2 className="text-lg font-semibold text-[#10213e]">显示信息</h2>
          </div>
          <form className="mt-5 space-y-4" onSubmit={saveProfile}>
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-[#6e7d97]">登录账号</span>
              <Input value={email} disabled aria-label="登录账号" />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold text-[#6e7d97]">昵称</span>
              <Input
                aria-label="昵称"
                value={nickname}
                maxLength={80}
                disabled={loading || savingProfile}
                placeholder="例如：研发小王"
                onChange={(event) => setNickname(event.target.value)}
              />
            </label>
            <p className="text-xs leading-5 text-[#6e7d97]">
              未设置昵称时，成员信息显示 {email || '当前登录邮箱'}
            </p>
            <label className="flex items-start gap-3 rounded-lg border border-[#d7e0ec] bg-[#f7faff] p-3">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 shrink-0 accent-[#4a7bff]"
                checked={aiDetailVisibleToAdmin}
                disabled={loading || savingProfile}
                onChange={(event) => setAiDetailVisibleToAdmin(event.target.checked)}
                aria-label="允许管理员查看详细 AI 工作记录"
              />
              <span className="min-w-0">
                <span className="flex items-center gap-1.5 text-sm font-medium text-[#253655]">
                  <ShieldCheck size={15} className="text-brand-600" aria-hidden="true" />
                  允许管理员查看详细 AI 工作记录
                </span>
                <span className="mt-1 block text-xs leading-5 text-[#6e7d97]">
                  关闭时，管理员仍可查看你的 AI 工作日志和汇总，但不能读取详细会话记录。
                </span>
              </span>
            </label>
            {profileNotice && <NoticeMessage notice={profileNotice} />}
            <Button type="submit" className="w-full" disabled={loading || savingProfile}>
              {savingProfile ? '保存中…' : '保存个人设置'}
            </Button>
          </form>
        </section>

        <section className="rounded-lg border border-[#d7e0ec] bg-white p-5 shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
          <div className="flex items-center gap-2">
            <KeyRound size={18} className="text-brand-600" aria-hidden="true" />
            <h2 className="text-lg font-semibold text-[#10213e]">修改密码</h2>
          </div>
          <form className="mt-5 space-y-4" onSubmit={savePassword}>
            <PasswordField
              label="当前密码"
              value={currentPassword}
              autoComplete="current-password"
              disabled={changingPassword}
              onChange={setCurrentPassword}
            />
            <PasswordField
              label="新密码"
              value={newPassword}
              autoComplete="new-password"
              disabled={changingPassword}
              onChange={setNewPassword}
            />
            <PasswordField
              label="确认新密码"
              value={confirmPassword}
              autoComplete="new-password"
              disabled={changingPassword}
              onChange={setConfirmPassword}
            />
            <p className="text-xs leading-5 text-[#6e7d97]">密码长度至少 6 位；保存前会校验当前密码。</p>
            {passwordNotice && <NoticeMessage notice={passwordNotice} />}
            <Button
              type="submit"
              className="w-full"
              disabled={changingPassword || !currentPassword || !newPassword || !confirmPassword}
            >
              {changingPassword ? '修改中…' : '修改密码'}
            </Button>
          </form>
        </section>
      </PageBody>
    </PageShell>
  );
}

function PasswordField({
  label,
  value,
  autoComplete,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  autoComplete: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold text-[#6e7d97]">{label}</span>
      <Input
        type="password"
        aria-label={label}
        value={value}
        minLength={6}
        maxLength={128}
        autoComplete={autoComplete}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function NoticeMessage({ notice }: { notice: Exclude<Notice, null> }) {
  return (
    <div
      role="status"
      className={`rounded-lg border px-3 py-2 text-sm ${
        notice.kind === 'success'
          ? 'border-[#7ec49a]/40 bg-[#eef9f2] text-[#237347]'
          : 'border-[#df5a67]/35 bg-[#fff2f3] text-[#a43d49]'
      }`}
    >
      {notice.text}
    </div>
  );
}

function projectRoleLabel(role?: Project['role']): string {
  return role === 'owner' || role === 'admin' ? '项目负责人' : '项目成员';
}

function formatDate(value?: string | null): string {
  if (!value) return '未设置';
  return new Date(value).toLocaleDateString('zh-CN', { hour12: false });
}

function ProfileDatum({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="min-w-0 bg-white px-4 py-3">
      <dt className="text-xs font-medium text-[#6e7d97]">{label}</dt>
      <dd className="mt-1.5 flex min-w-0 items-center gap-1.5 break-words text-sm font-semibold text-[#253655]">
        {icon}{value}
      </dd>
    </div>
  );
}
