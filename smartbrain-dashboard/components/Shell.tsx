'use client';

import * as React from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  Bot,
  BrainCircuit,
  LibraryBig,
  LogOut,
  MessageCircle,
  Settings,
  UploadCloud,
  UserRound,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { logout as logoutApi } from '@/lib/api';

interface Me {
  user_id: string;
  email: string;
  full_name: string | null;
  nickname?: string | null;
  display_name?: string;
  is_system_admin?: boolean;
  can_manage_projects?: boolean;
  memberships: { org_id: string; org_name: string; role: string }[];
}

const NAV: {
  href: string;
  label: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  systemAdminOnly?: boolean;
  activePaths?: string[];
}[] = [
  { href: '/chat', label: '问答', icon: MessageCircle },
  { href: '/knowledge', label: '知识库', icon: LibraryBig },
  { href: '/wiki', label: '智慧 Wiki', icon: LibraryBig, activePaths: ['/wiki', '/member-wiki'] },
  { href: '/uploads', label: '上传资料', icon: UploadCloud, activePaths: ['/uploads', '/meeting-notes'] },
  {
    href: '/workday',
    label: 'AI 工作台',
    icon: Bot,
    activePaths: ['/workday', '/leaderboard', '/worklogs', '/monitor/setup'],
  },
  { href: '/profile', label: '个人中心', icon: UserRound },
  { href: '/team', label: '团队管理', icon: Users, systemAdminOnly: true },
  { href: '/members', label: '成员管理', icon: Users },
  { href: '/admin', label: '项目管理', icon: Settings, adminOnly: true },
];

export function Shell({ me, children }: { me: Me; children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const isAdmin = Boolean(
    me.can_manage_projects ??
      (me.is_system_admin || me.memberships.some((membership) => membership.role === 'owner' || membership.role === 'admin')),
  );
  const isSystemAdmin = Boolean(me.is_system_admin);

  async function logout() {
    await logoutApi().catch(() => undefined);
    router.push('/login');
    router.refresh();
  }

  return (
    <div className="flex h-screen bg-[#eef3f9]">
      <aside className="flex w-16 shrink-0 flex-col border-r border-[#d7e0ec] bg-white/95 text-[#253655] backdrop-blur md:w-56">
        <div className="px-3 md:px-4 py-4 border-b border-[#d7e0ec]">
          <div className="flex items-center gap-2">
            <div className="w-9 h-9 shrink-0 rounded-lg bg-brand-500/10 text-brand-600 flex items-center justify-center ring-1 ring-brand-500/15">
              <BrainCircuit size={20} aria-hidden="true" />
            </div>
            <div className="hidden md:block min-w-0">
              <div className="text-base font-semibold leading-tight text-[#10213e]">智慧大脑</div>
              <div className="text-[11px] text-[#6e7d97]">研发知识工作台</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-2.5 py-3 space-y-1">
          {NAV.filter((n) => (!n.adminOnly || isAdmin) && (!n.systemAdminOnly || isSystemAdmin)).map((n) => {
            const active = (n.activePaths || [n.href]).some(
              (activePath) => pathname === activePath || pathname?.startsWith(activePath + '/'),
            );
            const Icon = n.icon;
            const label = n.href === '/members' && !isAdmin ? '成员信息' : n.label;
            return (
              <button
                key={n.href}
                type="button"
                title={label}
                onClick={() => router.push(n.href)}
                className={`flex h-10 w-full items-center justify-center gap-2.5 rounded-lg px-3 text-sm transition-all duration-150 active:scale-[0.98] md:justify-start ${
                  active
                    ? 'bg-brand-500/10 text-brand-700 shadow-[inset_3px_0_0_rgba(74,123,255,0.9)]'
                    : 'text-[#6e7d97] hover:bg-[#f7f9fc] hover:text-[#10213e]'
                }`}
              >
                <Icon size={18} aria-hidden={true} />
                <span className="hidden md:block">{label}</span>
              </button>
            );
          })}
        </nav>

        <div className="px-3 py-3 border-t border-[#d7e0ec]">
          <div className="hidden md:block px-2 py-1.5 text-xs text-[#6e7d97] truncate">
            <div className="truncate font-medium text-[#253655]">{me.display_name || me.nickname || me.email}</div>
            {(me.display_name || me.nickname) && <div className="mt-0.5 truncate text-[11px]">{me.email}</div>}
          </div>
          <button
            type="button"
            title="退出登录"
            onClick={logout}
            className="flex h-10 w-full items-center justify-center gap-2 rounded-lg px-3 text-sm text-[#6e7d97] transition-colors hover:bg-[#f7f9fc] hover:text-[#10213e] md:justify-start"
          >
            <LogOut size={17} aria-hidden="true" />
            <span className="hidden md:block">退出登录</span>
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-hidden bg-[var(--bg)]">{children}</main>
    </div>
  );
}
