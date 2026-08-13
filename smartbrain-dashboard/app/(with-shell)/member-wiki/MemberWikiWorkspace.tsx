'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  BookOpen,
  CalendarClock,
  CheckCircle2,
  Clock3,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UserRound,
} from 'lucide-react';

import { Card } from '@/components/Card';
import { PageBody, PageHeader, PageShell } from '@/components/PageLayout';
import { WikiWorkspaceTabs } from '@/components/wiki-workspace/WikiWorkspaceTabs';
import {
  getMemberWikiOptions,
  getMemberWikiOverview,
  type MemberWikiExperience,
  type MemberWikiOptions,
  type MemberWikiOutcome,
  type MemberWikiOverview,
  type MemberWikiTaskType,
} from '@/lib/api';


const TASK_TYPES: Array<{ value: MemberWikiTaskType | ''; label: string }> = [
  { value: '', label: '全部任务类型' },
  { value: 'development', label: '开发' },
  { value: 'debugging', label: '调试排障' },
  { value: 'deployment', label: '部署' },
  { value: 'configuration', label: '配置' },
  { value: 'data_processing', label: '数据处理' },
  { value: 'documentation', label: '文档' },
  { value: 'testing', label: '测试' },
  { value: 'research', label: '调研' },
  { value: 'operations', label: '运维' },
  { value: 'other', label: '其他' },
];

const OUTCOMES: Array<{ value: MemberWikiOutcome | ''; label: string }> = [
  { value: '', label: '全部结果' },
  { value: 'success', label: '成功经验' },
  { value: 'partial', label: '部分完成' },
  { value: 'failure', label: '失败经验' },
];

function dateText(value: string | null | undefined): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00+08:00`));
}

function dateTimeText(value: string | null | undefined): string {
  if (!value) return '尚未运行';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(value));
}

function outcomeLabel(value: MemberWikiOutcome): string {
  return value === 'success' ? '成功' : value === 'failure' ? '失败' : '部分完成';
}

export function MemberWikiWorkspace({
  onWorkspaceViewChange,
}: {
  onWorkspaceViewChange?: (view: 'project' | 'member') => void;
}) {
  const [options, setOptions] = useState<MemberWikiOptions | null>(null);
  const [overview, setOverview] = useState<MemberWikiOverview | null>(null);
  const [employeeId, setEmployeeId] = useState('');
  const [query, setQuery] = useState('');
  const [taskType, setTaskType] = useState<MemberWikiTaskType | ''>('');
  const [outcome, setOutcome] = useState<MemberWikiOutcome | ''>('');
  const [tag, setTag] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadOverview = useCallback(async (targetEmployeeId: string, resetSelection = true) => {
    if (!targetEmployeeId) return;
    setLoading(true);
    setError('');
    try {
      const data = await getMemberWikiOverview({
        employeeId: targetEmployeeId,
        query: query.trim() || undefined,
        taskType: taskType || undefined,
        outcome: outcome || undefined,
        tag: tag.trim() || undefined,
        limit: 100,
      });
      setOverview(data);
      if (resetSelection) setSelectedId(data.experiences[0]?.id ?? '');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '成员 Wiki 加载失败');
      setOverview(null);
    } finally {
      setLoading(false);
    }
  }, [outcome, query, tag, taskType]);

  useEffect(() => {
    let active = true;
    getMemberWikiOptions()
      .then((data) => {
        if (!active) return;
        setOptions(data);
        const initial = data.mode === 'admin'
          ? data.members.find((member) => member.employee_id === data.current_member.employee_id)?.employee_id
            ?? data.members[0]?.employee_id
            ?? ''
          : data.current_member.employee_id;
        setEmployeeId(initial);
        if (initial) return loadOverview(initial);
        setLoading(false);
      })
      .catch((requestError) => {
        if (!active) return;
        setError(requestError instanceof Error ? requestError.message : '成员 Wiki 权限加载失败');
        setLoading(false);
      });
    return () => { active = false; };
  // The initial request deliberately uses the initial empty filters once.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = useMemo(
    () => overview?.experiences.find((item) => item.id === selectedId) ?? overview?.experiences[0] ?? null,
    [overview, selectedId],
  );

  function handleSearch(event: FormEvent) {
    event.preventDefault();
    void loadOverview(employeeId);
  }

  function handleMemberChange(value: string) {
    setEmployeeId(value);
    void loadOverview(value);
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="长期经验资产"
        icon={BookOpen}
        title="智慧 Wiki"
        description="统一查看项目知识与成员长期经验，在两个 Wiki 视图间快速切换。"
        actions={(
          <button
            type="button"
            onClick={() => void loadOverview(employeeId, false)}
            disabled={!employeeId || loading}
            className="inline-flex h-10 items-center gap-2 rounded-md border border-[#cbd8e8] bg-white px-4 text-sm font-medium text-[#355170] hover:bg-[#f7f9fc] disabled:opacity-50"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />刷新
          </button>
        )}
      />
      <PageBody contentClassName="space-y-4">
        <WikiWorkspaceTabs activeView="member" onChange={onWorkspaceViewChange} />
        <Card className="p-4">
          <div className="flex items-start gap-3 text-sm text-[#50627b]">
            <ShieldCheck size={19} className="mt-0.5 shrink-0 text-[#2c7a59]" />
            <p>每天 21:00（Asia/Shanghai）从 AI 工作记录提炼可复用经验。成员只能查看自己的 Wiki；组织负责人和管理员可查看其管理组织内的成员。MCP Token 继承同一权限，不返回原始完整对话。</p>
          </div>
        </Card>

        <form onSubmit={handleSearch} className="grid gap-3 rounded-lg border border-[#d7e0ec] bg-white p-4 md:grid-cols-6">
          {options?.mode === 'admin' && (
            <label className="md:col-span-2 text-xs font-medium text-[#50627b]">
              选择成员
              <select
                aria-label="选择成员"
                value={employeeId}
                onChange={(event) => handleMemberChange(event.target.value)}
                className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] bg-white px-3 text-sm text-[#172844]"
              >
                {options.members.map((member) => (
                  <option key={member.employee_id} value={member.employee_id}>{member.name} · {member.employee_id}</option>
                ))}
              </select>
            </label>
          )}
          <label className={`${options?.mode === 'admin' ? 'md:col-span-2' : 'md:col-span-3'} text-xs font-medium text-[#50627b]`}>
            相似任务或关键词
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：部署新版本、修复登录故障" className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" />
          </label>
          <label className="text-xs font-medium text-[#50627b]">任务类型<select value={taskType} onChange={(event) => setTaskType(event.target.value as MemberWikiTaskType | '')} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] bg-white px-2 text-sm">{TASK_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label className="text-xs font-medium text-[#50627b]">结果<select value={outcome} onChange={(event) => setOutcome(event.target.value as MemberWikiOutcome | '')} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] bg-white px-2 text-sm">{OUTCOMES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label className="text-xs font-medium text-[#50627b]">标签<input value={tag} onChange={(event) => setTag(event.target.value)} placeholder="docker" className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" /></label>
          <button type="submit" disabled={!employeeId || loading} className="inline-flex h-10 items-center justify-center gap-2 self-end rounded-md bg-brand-600 px-4 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"><Search size={16} />检索经验</button>
        </form>

        {error && <div className="rounded-lg border border-[#efc9c9] bg-[#fff7f7] px-4 py-3 text-sm text-[#a33a3a]"><TriangleAlert size={16} className="mr-2 inline" />{error}</div>}

        {overview && (
          <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric icon={Sparkles} label="经验页" value={overview.summary.experience_count} />
            <Metric icon={CheckCircle2} label="成功经验" value={overview.summary.success_count} />
            <Metric icon={CalendarClock} label="最近观察" value={dateText(overview.summary.latest_observed)} />
            <Metric icon={Clock3} label="最近更新" value={dateTimeText(overview.latest_run?.completed_at)} />
          </section>
        )}

        {loading && !overview ? (
          <Card className="flex min-h-64 items-center justify-center text-sm text-[#6e7d97]">正在读取成员经验…</Card>
        ) : overview && overview.experiences.length > 0 ? (
          <div className="grid min-w-0 gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
            <Card className="max-h-[calc(100vh-360px)] min-h-64 overflow-y-auto">
              <div className="border-b border-[#e5ebf3] px-4 py-3 text-sm font-semibold text-[#172844]">{overview.member.name} 的经验目录</div>
              <div className="divide-y divide-[#edf1f6]">
                {overview.experiences.map((item) => (
                  <ExperienceListItem key={item.id} item={item} active={selected?.id === item.id} onClick={() => setSelectedId(item.id)} />
                ))}
              </div>
            </Card>
            <Card className="min-w-0 overflow-hidden">
              {selected && <ExperienceDetail item={selected} />}
            </Card>
          </div>
        ) : !loading && employeeId ? (
          <Card className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
            <BookOpen size={30} className="text-[#8aa0ba]" />
            <p className="mt-3 text-base font-semibold text-[#253655]">暂时没有可复用经验</p>
            <p className="mt-1 text-sm text-[#6e7d97]">成员当天没有实际 AI 执行记录时会自动跳过，不生成空 Wiki。</p>
          </Card>
        ) : null}
      </PageBody>
    </PageShell>
  );
}


function Metric({ icon: Icon, label, value }: { icon: typeof Sparkles; label: string; value: string | number }) {
  return <Card className="p-4"><div className="flex items-center gap-2 text-xs text-[#6e7d97]"><Icon size={15} />{label}</div><div className="mt-2 truncate text-xl font-semibold text-[#172844]">{value}</div></Card>;
}

function ExperienceListItem({ item, active, onClick }: { item: MemberWikiExperience; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={`w-full px-4 py-3 text-left ${active ? 'bg-[#edf4ff]' : 'hover:bg-[#f8fafc]'}`}>
      <div className="flex items-start justify-between gap-3"><span className="min-w-0 truncate text-sm font-semibold text-[#172844]">{item.title}</span><span className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold ${item.outcome === 'success' ? 'bg-[#e9f7ef] text-[#28714f]' : item.outcome === 'failure' ? 'bg-[#fff0f0] text-[#a33a3a]' : 'bg-[#fff6df] text-[#916b14]'}`}>{outcomeLabel(item.outcome)}</span></div>
      <div className="mt-2 flex flex-wrap gap-1">{item.tags.slice(0, 3).map((value) => <span key={value} className="rounded bg-[#eef2f7] px-1.5 py-0.5 text-[10px] text-[#50627b]">{value}</span>)}</div>
    </button>
  );
}

function ExperienceDetail({ item }: { item: MemberWikiExperience }) {
  return (
    <article className="min-w-0">
      <header className="border-b border-[#e5ebf3] px-5 py-4">
        <div className="flex flex-wrap items-center gap-2 text-xs text-[#6e7d97]"><UserRound size={14} />{item.employee_name}<span>·</span><span>v{item.current_version}</span><span>·</span><span>{item.observation_count} 次有效证据</span><span>·</span><span>置信度 {(item.confidence * 100).toFixed(0)}%</span></div>
        <p className="mt-2 text-sm leading-6 text-[#50627b]">{item.summary}</p>
      </header>
      <pre className="max-h-[calc(100vh-430px)] min-h-64 overflow-auto whitespace-pre-wrap break-words bg-[#fbfcfe] px-5 py-5 font-sans text-sm leading-7 text-[#243a57]">{item.markdown_content}</pre>
    </article>
  );
}
