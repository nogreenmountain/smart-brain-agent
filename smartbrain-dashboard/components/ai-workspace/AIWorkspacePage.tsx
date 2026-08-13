'use client';

import { lazy, Suspense, useEffect, useState } from 'react';
import { Activity, CalendarDays, FileText, MonitorCheck, Trophy } from 'lucide-react';

import { LoadingDots } from '@/components/Feedback';

const AIRecordsPanel = lazy(() => import('./AIRecordsPanel'));
const AILeaderboardPanel = lazy(() => import('./AILeaderboardPanel'));
const AIWorklogsPanel = lazy(() => import('./AIWorklogsPanel'));
const AIMonitorPanel = lazy(() => import('./AIMonitorPanel'));

export type AIWorkspaceView = 'records' | 'leaderboard' | 'logs' | 'monitor';

const views: Array<{
  id: AIWorkspaceView;
  label: string;
  description: string;
  icon: typeof Activity;
}> = [
  { id: 'records', label: '工作记录', description: '对话、Trace 与 Token 趋势', icon: CalendarDays },
  { id: 'leaderboard', label: '团队排行', description: '团队聚合统计与模型热度', icon: Trophy },
  { id: 'logs', label: '工作日志', description: '按日查看结构化工作总结', icon: FileText },
  { id: 'monitor', label: '设备与同步', description: '安装检测与采集组件状态', icon: MonitorCheck },
];

function panel(view: AIWorkspaceView) {
  if (view === 'leaderboard') return <AILeaderboardPanel />;
  if (view === 'logs') return <AIWorklogsPanel />;
  if (view === 'monitor') return <AIMonitorPanel />;
  return <AIRecordsPanel />;
}

export function AIWorkspacePage({ initialView = 'records' }: { initialView?: AIWorkspaceView }) {
  const [activeView, setActiveView] = useState<AIWorkspaceView>(() => {
    if (typeof window === 'undefined') return initialView;
    const requested = new URLSearchParams(window.location.search).get('view');
    return views.some((view) => view.id === requested) ? requested as AIWorkspaceView : initialView;
  });

  useEffect(() => {
    function restoreView() {
      const requested = new URLSearchParams(window.location.search).get('view');
      if (views.some((view) => view.id === requested)) setActiveView(requested as AIWorkspaceView);
    }
    window.addEventListener('popstate', restoreView);
    return () => window.removeEventListener('popstate', restoreView);
  }, []);

  function selectView(view: AIWorkspaceView) {
    setActiveView(view);
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      url.pathname = '/workday';
      url.searchParams.set('view', view);
      window.history.pushState({}, '', `${url.pathname}${url.search}`);
    }
  }

  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden bg-[#eef3f9] text-[#10213e]">
      <header className="shrink-0 border-b border-[#d7e0ec] bg-white/95 px-4 py-4 backdrop-blur md:px-6">
        <div className="mx-auto max-w-[1440px]">
          <div className="flex items-center gap-2 text-[12px] font-bold tracking-[0.08em] text-brand-600">
            <Activity size={16} aria-hidden="true" /> AI OPERATIONS HUB
          </div>
          <h1 className="mt-1 text-[26px] font-semibold leading-tight">AI 工作台</h1>
          <p className="mt-1 text-sm leading-6 text-[#6e7d97]">
            在一个页面集中查看 AI 使用记录、团队排行、每日工作日志和设备同步状态。
          </p>

          <div
            role="tablist"
            aria-label="AI 工作台视图"
            className="mt-4 grid grid-cols-2 gap-2 lg:grid-cols-4"
          >
            {views.map((view) => {
              const Icon = view.icon;
              const selected = view.id === activeView;
              return (
                <button
                  key={view.id}
                  type="button"
                  role="tab"
                  aria-label={view.label}
                  aria-selected={selected}
                  onClick={() => selectView(view.id)}
                  className={`min-w-0 rounded-xl border px-3 py-3 text-left transition sm:px-4 ${
                    selected
                      ? 'border-brand-500/35 bg-brand-500/10 text-brand-700 shadow-sm'
                      : 'border-[#d7e0ec] bg-[#f8fafc] text-[#53647d] hover:border-brand-500/25 hover:bg-white'
                  }`}
                >
                  <span className="flex items-center gap-2 text-sm font-semibold">
                    <Icon size={17} aria-hidden="true" /> {view.label}
                  </span>
                  <span className="mt-1 hidden truncate text-xs text-[#7a889d] sm:block">{view.description}</span>
                </button>
              );
            })}
          </div>
        </div>
      </header>

      <section role="tabpanel" className="min-h-0 min-w-0 flex-1 overflow-hidden">
        <Suspense
          fallback={(
            <div className="flex h-full items-center justify-center gap-3 text-sm text-[#6e7d97]">
              <LoadingDots /> 正在加载工作台视图
            </div>
          )}
        >
          {panel(activeView)}
        </Suspense>
      </section>
    </div>
  );
}
