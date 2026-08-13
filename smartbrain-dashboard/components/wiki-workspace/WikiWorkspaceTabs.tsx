'use client';

import { BookOpen, Network } from 'lucide-react';
import Link from 'next/link';

export type WikiWorkspaceView = 'project' | 'member';

const views = [
  {
    id: 'project' as const,
    label: '项目 Wiki',
    description: '项目级已验证知识、来源、关系和 MCP 接入',
    icon: Network,
  },
  {
    id: 'member' as const,
    label: '成员 Wiki',
    description: '从 AI 工作记录提炼的个人长期经验资产',
    icon: BookOpen,
  },
];

export function WikiWorkspaceTabs({
  activeView,
  onChange,
}: {
  activeView: WikiWorkspaceView;
  onChange?: (view: WikiWorkspaceView) => void;
}) {
  return (
    <div role="tablist" aria-label="智慧 Wiki 视图" className="grid grid-cols-2 gap-2">
      {views.map((view) => {
        const Icon = view.icon;
        const selected = activeView === view.id;
        const className = `min-w-0 rounded-xl border px-3 py-3 text-left transition sm:px-4 ${
          selected
            ? 'border-brand-500/35 bg-brand-500/10 text-brand-700 shadow-sm'
            : 'border-[#d7e0ec] bg-[#f8fafc] text-[#53647d] hover:border-brand-500/25 hover:bg-white'
        }`;
        const content = (
          <>
            <span className="flex items-center gap-2 text-sm font-semibold">
              <Icon size={17} aria-hidden="true" />{view.label}
            </span>
            <span className="mt-1 hidden truncate text-xs text-[#7a889d] sm:block">{view.description}</span>
          </>
        );
        return onChange ? (
          <button
            key={view.id}
            type="button"
            role="tab"
            aria-label={view.label}
            aria-selected={selected}
            onClick={() => onChange(view.id)}
            className={className}
          >
            {content}
          </button>
        ) : (
          <Link
            key={view.id}
            href={view.id === 'project' ? '/wiki' : '/member-wiki'}
            role="tab"
            aria-label={view.label}
            aria-selected={selected}
            className={className}
          >
            {content}
          </Link>
        );
      })}
    </div>
  );
}
