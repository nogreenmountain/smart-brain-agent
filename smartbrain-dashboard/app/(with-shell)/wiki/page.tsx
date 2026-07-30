'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  BookOpenText,
  Check,
  Clock3,
  GitBranch,
  Network,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react';
import {
  ApiError,
  Project,
  ProjectWikiChange,
  ProjectWikiOverview,
  ProjectWikiPage as WikiPageRecord,
  compileProjectWiki,
  getProjectWikiOverview,
  listProjects,
  reviewProjectWikiChange,
} from '@/lib/api';
import { Button } from '@/components/Button';
import { LoadingDots, Toast } from '@/components/Feedback';
import { Select } from '@/components/Select';

const TYPE_LABELS: Record<string, string> = {
  fact: '事实',
  concept: '概念',
  procedure: '流程',
  troubleshooting: '排障',
  lesson: '经验',
  decision: '决策',
  policy: '规则',
  architecture: '架构',
  requirement: '需求',
  note: '笔记',
};

function fmtTime(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

export default function ProjectWikiPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState('');
  const [overview, setOverview] = useState<ProjectWikiOverview | null>(null);
  const [selectedPageId, setSelectedPageId] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; kind: 'info' | 'error' } | null>(null);

  const selectedPage = useMemo(
    () => overview?.pages.find((page) => page.id === selectedPageId) || overview?.pages[0] || null,
    [overview, selectedPageId],
  );

  useEffect(() => {
    listProjects()
      .then((rows) => {
        setProjects(rows);
        const queryProjectId =
          typeof window !== 'undefined'
            ? new URLSearchParams(window.location.search).get('project_id')
            : null;
        const initial = rows.find((project) => project.id === queryProjectId) || rows[0];
        if (initial) setProjectId(initial.id);
      })
      .catch((error: Error) => setToast({ msg: error.message || '加载项目失败', kind: 'error' }))
      .finally(() => setLoading(false));
  }, []);

  const loadOverview = useCallback(async (id: string) => {
    if (!id) return;
    setRefreshing(true);
    try {
      const data = await getProjectWikiOverview(id);
      setOverview(data);
      setSelectedPageId((current) =>
        data.pages.some((page) => page.id === current) ? current : data.pages[0]?.id || '',
      );
    } catch (error: any) {
      if (error instanceof ApiError && error.status === 403) {
        setToast({ msg: '你不是这个项目的成员', kind: 'error' });
      } else {
        setToast({ msg: error?.message || '加载项目 Wiki 失败', kind: 'error' });
      }
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!projectId) {
      setOverview(null);
      return;
    }
    void loadOverview(projectId);
  }, [loadOverview, projectId]);

  async function handleCompile() {
    if (!projectId) return;
    setCompiling(true);
    try {
      const result = await compileProjectWiki(projectId);
      setToast({
        msg: `编译完成：自动入库 ${result.auto_applied_count}，待审批 ${result.pending_review_count}，丢弃 ${result.discarded_count}`,
        kind: 'info',
      });
      await loadOverview(projectId);
    } catch (error: any) {
      setToast({ msg: error?.message || '项目 Wiki 编译失败', kind: 'error' });
    } finally {
      setCompiling(false);
    }
  }

  async function handleReview(change: ProjectWikiChange, decision: 'approve' | 'reject') {
    setReviewingId(change.id);
    try {
      await reviewProjectWikiChange(
        change.id,
        decision,
        decision === 'approve' ? '管理员确认进入项目 Wiki' : '管理员驳回候选知识',
      );
      setToast({ msg: decision === 'approve' ? '知识变更已写入 Wiki' : '知识变更已驳回', kind: 'info' });
      await loadOverview(projectId);
    } catch (error: any) {
      setToast({ msg: error?.message || '处理 Wiki 变更失败', kind: 'error' });
    } finally {
      setReviewingId(null);
    }
  }

  return (
    <div className="flex h-screen min-w-0 flex-col bg-[#eef3f9] text-[#10213e]">
      <header className="border-b border-[#d7e0ec] bg-white px-5 py-4 md:px-6">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-3">
          <div>
            <div className="flex items-center gap-2 text-xs font-bold text-brand-600">
              <BookOpenText size={16} aria-hidden="true" />
              LIVING KNOWLEDGE
            </div>
            <h1 className="mt-1 text-[26px] font-semibold leading-tight">项目 Wiki</h1>
            <p className="mt-1 text-sm text-[#6e7d97]">当前项目的已验证知识、来源和关系。</p>
          </div>
          <div className="flex-1" />
          <div className="w-full sm:w-72">
            <Select
              value={projectId}
              onChange={setProjectId}
              options={projects.map((project) => ({ value: project.id, label: project.name }))}
              placeholder={loading ? '加载项目中' : '选择项目'}
              disabled={loading || projects.length === 0}
            />
          </div>
          <Button
            type="button"
            variant="secondary"
            title="刷新 Wiki"
            aria-label="刷新 Wiki"
            onClick={() => loadOverview(projectId)}
            disabled={!projectId || refreshing}
          >
            <RefreshCw size={17} className={refreshing ? 'animate-spin' : ''} aria-hidden="true" />
          </Button>
          {overview?.permissions.can_compile && (
            <Button type="button" onClick={handleCompile} disabled={compiling || refreshing}>
              <Sparkles size={17} aria-hidden="true" />
              {compiling ? '编译中' : '立即编译'}
            </Button>
          )}
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-5 py-5 md:px-6">
        <div className="mx-auto grid max-w-[1440px] gap-5">
          {loading || (refreshing && !overview) ? (
            <div className="py-24 text-center text-[#8b99ae]"><LoadingDots /></div>
          ) : !projectId ? (
            <EmptyPanel title="暂无可访问项目" />
          ) : !overview ? (
            <EmptyPanel title="Wiki 暂不可用" />
          ) : (
            <>
              <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Metric icon={BookOpenText} label="知识页面" value={overview.summary.page_count} />
                <Metric icon={Clock3} label="待审批" value={overview.summary.pending_review_count} />
                <Metric icon={ShieldCheck} label="已处理来源" value={overview.summary.source_count} />
                <Metric icon={GitBranch} label="知识链接" value={overview.summary.link_count} />
              </section>

              <section className="grid min-h-[620px] gap-4 xl:grid-cols-[280px_minmax(0,1fr)_360px]">
                <aside className="overflow-hidden rounded-lg border border-[#d7e0ec] bg-white">
                  <div className="border-b border-[#d7e0ec] bg-[#f7faff] px-4 py-3 text-sm font-semibold">
                    页面目录
                  </div>
                  {overview.pages.length === 0 ? (
                    <EmptyPanel title="尚未形成有用知识" compact />
                  ) : (
                    <div className="max-h-[720px] overflow-y-auto p-2">
                      {overview.pages.map((page) => (
                        <button
                          key={page.id}
                          type="button"
                          onClick={() => setSelectedPageId(page.id)}
                          className={`mb-1 w-full rounded-md px-3 py-3 text-left transition-colors ${
                            selectedPage?.id === page.id
                              ? 'bg-brand-500/10 text-brand-700'
                              : 'text-[#253655] hover:bg-[#f7f9fc]'
                          }`}
                        >
                          <div className="flex items-start gap-2">
                            <span className="mt-0.5 rounded border border-[#d7e0ec] bg-white px-1.5 py-0.5 text-[10px] font-semibold text-[#6e7d97]">
                              {TYPE_LABELS[page.page_type] || page.page_type}
                            </span>
                            <span className="min-w-0 break-words text-sm font-medium">{page.title}</span>
                          </div>
                          <div className="mt-2 line-clamp-2 text-xs leading-5 text-[#8b99ae]">{page.summary}</div>
                        </button>
                      ))}
                    </div>
                  )}
                </aside>

                <article className="min-w-0 overflow-hidden rounded-lg border border-[#d7e0ec] bg-white">
                  {selectedPage ? (
                    <>
                      <div className="border-b border-[#d7e0ec] px-5 py-4 md:px-6">
                        <div className="flex flex-wrap items-center gap-2 text-xs text-[#6e7d97]">
                          <span className="rounded border border-brand-500/20 bg-brand-500/10 px-2 py-1 font-medium text-brand-700">
                            {TYPE_LABELS[selectedPage.page_type] || selectedPage.page_type}
                          </span>
                          <span>版本 {selectedPage.current_version}</span>
                          <span>置信度 {(selectedPage.confidence * 100).toFixed(0)}%</span>
                          <span>更新于 {fmtTime(selectedPage.updated_at)}</span>
                        </div>
                        <h2 className="mt-3 break-words text-2xl font-semibold">{selectedPage.title}</h2>
                        <p className="mt-2 text-sm leading-6 text-[#6e7d97]">{selectedPage.summary}</p>
                      </div>
                      <div className="whitespace-pre-wrap break-words px-5 py-5 font-sans text-sm leading-7 text-[#253655] md:px-6">
                        {selectedPage.markdown_content}
                      </div>
                    </>
                  ) : (
                    <EmptyPanel title="请选择知识页面" />
                  )}
                </article>

                <aside className="grid content-start gap-4">
                  <section className="overflow-hidden rounded-lg border border-[#d7e0ec] bg-white">
                    <div className="flex items-center gap-2 border-b border-[#d7e0ec] bg-[#f7faff] px-4 py-3 text-sm font-semibold">
                      <Network size={17} className="text-brand-600" aria-hidden="true" />
                      知识关系
                    </div>
                    <WikiGraph pages={overview.pages} />
                  </section>

                  <section className="overflow-hidden rounded-lg border border-[#d7e0ec] bg-white">
                    <div className="border-b border-[#d7e0ec] bg-[#f7faff] px-4 py-3 text-sm font-semibold">来源</div>
                    <div className="p-4">
                      {!selectedPage || selectedPage.sources.length === 0 ? (
                        <div className="text-sm text-[#8b99ae]">暂无来源</div>
                      ) : (
                        <div className="space-y-2">
                          {selectedPage.sources.map((source) => (
                            <div key={`${source.source_type}:${source.source_id}`} className="break-all rounded-md border border-[#d7e0ec] bg-[#f7f9fc] px-3 py-2 text-xs text-[#253655]">
                              {source.source_type}:{source.source_id}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </section>

                  {overview.latest_run && (
                    <section className="rounded-lg border border-[#1f365b] bg-[#10213e] p-4 text-white">
                      <div className="text-xs font-semibold text-[#9fb0c8]">最近一次编译</div>
                      <div className="mt-2 flex items-center justify-between gap-3">
                        <span className="font-semibold">{overview.latest_run.model}</span>
                        <span className="text-xs text-[#c7d2e1]">{fmtTime(overview.latest_run.completed_at || overview.latest_run.started_at)}</span>
                      </div>
                      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                        <RunMetric label="入库" value={overview.latest_run.auto_applied_count} />
                        <RunMetric label="审批" value={overview.latest_run.pending_review_count} />
                        <RunMetric label="丢弃" value={overview.latest_run.discarded_count} />
                      </div>
                    </section>
                  )}
                </aside>
              </section>

              {overview.permissions.can_review && overview.pending_changes.length > 0 && (
                <section className="overflow-hidden rounded-lg border border-[#d7e0ec] bg-white">
                  <div className="flex items-center gap-2 border-b border-[#d7e0ec] bg-[#fff8ed] px-5 py-4">
                    <ShieldCheck size={18} className="text-[#9a5a0d]" aria-hidden="true" />
                    <h2 className="text-base font-semibold">待审批知识</h2>
                    <span className="rounded-full bg-[#f0a23a]/15 px-2.5 py-1 text-xs font-medium text-[#9a5a0d]">
                      {overview.pending_changes.length}
                    </span>
                  </div>
                  <div className="divide-y divide-[#d7e0ec]">
                    {overview.pending_changes.map((change) => (
                      <PendingChange
                        key={change.id}
                        change={change}
                        busy={reviewingId === change.id}
                        onApprove={() => handleReview(change, 'approve')}
                        onReject={() => handleReview(change, 'reject')}
                      />
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </main>
      {toast && <Toast message={toast.msg} kind={toast.kind} />}
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof BookOpenText; label: string; value: number }) {
  return (
    <div className="flex min-h-24 items-center gap-3 rounded-lg border border-[#d7e0ec] bg-white p-4 shadow-[0_12px_28px_rgba(15,35,66,0.05)]">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600">
        <Icon size={19} aria-hidden="true" />
      </div>
      <div>
        <div className="text-xs text-[#6e7d97]">{label}</div>
        <div className="mt-1 text-2xl font-semibold">{value}</div>
      </div>
    </div>
  );
}

function RunMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-white/10 px-2 py-2">
      <div className="text-[#9fb0c8]">{label}</div>
      <div className="mt-1 text-base font-semibold">{value}</div>
    </div>
  );
}

function PendingChange({
  change,
  busy,
  onApprove,
  onReject,
}: {
  change: ProjectWikiChange;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <div className="grid gap-4 px-5 py-5 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded border border-[#f0a23a]/25 bg-[#f0a23a]/15 px-2 py-1 text-xs font-medium text-[#9a5a0d]">
            {TYPE_LABELS[change.page_type] || change.page_type}
          </span>
          {change.contradiction && (
            <span className="rounded border border-[#df5a67]/25 bg-[#df5a67]/10 px-2 py-1 text-xs font-medium text-[#b83d49]">存在冲突</span>
          )}
          <span className="text-xs text-[#8b99ae]">置信度 {(change.confidence * 100).toFixed(0)}%</span>
        </div>
        <h3 className="mt-3 break-words text-base font-semibold">{change.title}</h3>
        <p className="mt-2 text-sm leading-6 text-[#6e7d97]">{change.summary}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {change.source_ids.map((source) => (
            <span key={source} className="rounded bg-[#f1f4f8] px-2 py-1 text-xs text-[#5e6b80]">{source}</span>
          ))}
        </div>
      </div>
      <div className="flex items-start gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          aria-label={`驳回 ${change.title}`}
          disabled={busy}
          onClick={onReject}
        >
          <X size={16} aria-hidden="true" />
          驳回
        </Button>
        <Button
          type="button"
          size="sm"
          aria-label={`批准 ${change.title}`}
          disabled={busy}
          onClick={onApprove}
        >
          <Check size={16} aria-hidden="true" />
          批准
        </Button>
      </div>
    </div>
  );
}

function EmptyPanel({ title, compact = false }: { title: string; compact?: boolean }) {
  return <div className={`${compact ? 'py-12' : 'py-24'} text-center text-sm text-[#8b99ae]`}>{title}</div>;
}

function WikiGraph({ pages }: { pages: WikiPageRecord[] }) {
  const nodes = pages.slice(0, 16);
  const width = 330;
  const height = 260;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * 0.34;
  const positions = new Map(
    nodes.map((page, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1) - Math.PI / 2;
      return [
        page.title,
        {
          x: centerX + Math.cos(angle) * radius,
          y: centerY + Math.sin(angle) * radius,
        },
      ] as const;
    }),
  );
  const edges = nodes.flatMap((page) =>
    page.links
      .map((link) => ({ from: positions.get(page.title), to: positions.get(link.to_title) }))
      .filter((edge) => edge.from && edge.to),
  );

  if (nodes.length === 0) return <EmptyPanel title="暂无关系数据" compact />;
  return (
    <svg
      role="img"
      aria-label="知识关系网络"
      viewBox={`0 0 ${width} ${height}`}
      className="block aspect-[33/26] w-full bg-[#fbfcfe]"
    >
      {edges.map((edge, index) => (
        <line
          key={index}
          x1={edge.from!.x}
          y1={edge.from!.y}
          x2={edge.to!.x}
          y2={edge.to!.y}
          stroke="#b8c6da"
          strokeWidth="1.5"
        />
      ))}
      {nodes.map((page) => {
        const position = positions.get(page.title)!;
        const label = page.title.length > 8 ? `${page.title.slice(0, 8)}…` : page.title;
        return (
          <g key={page.id}>
            <circle cx={position.x} cy={position.y} r="9" fill="#4a7bff" stroke="#ffffff" strokeWidth="3" />
            <text
              x={position.x}
              y={position.y + 22}
              textAnchor="middle"
              fontSize="10"
              fill="#253655"
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
