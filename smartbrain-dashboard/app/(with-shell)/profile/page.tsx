'use client';

import { FormEvent, useEffect, useState } from 'react';
import { KeyRound, ShieldCheck, UserRound } from 'lucide-react';

import { Button } from '@/components/Button';
import { Input } from '@/components/Input';
import { PageBody, PageHeader, PageShell } from '@/components/PageLayout';
import { ApiError, changeMyPassword, getMe, updateMyProfile } from '@/lib/api';

type Notice = { kind: 'success' | 'error'; text: string } | null;

export default function ProfilePage() {
  const [email, setEmail] = useState('');
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
      .then((me) => {
        if (cancelled) return;
        setEmail(me.email);
        setNickname(me.nickname || '');
        setAiDetailVisibleToAdmin(Boolean(me.ai_detail_visible_to_admin));
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
      <PageBody contentClassName="grid max-w-[900px] gap-5 lg:grid-cols-2">
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
              未设置昵称时，成员管理显示 {email || '当前登录邮箱'}
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
