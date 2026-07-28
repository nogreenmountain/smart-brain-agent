'use client';

import { FormEvent, ReactNode, useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Bot,
  CalendarCheck,
  CircleDollarSign,
  Clock3,
  ExternalLink,
  FileWarning,
  Gauge,
  Lightbulb,
  ListTodo,
  Route,
  Sparkles,
  Wrench,
} from 'lucide-react';

import { Button } from '@/components/Button';
import { EmptyState, LoadingDots } from '@/components/Feedback';
import { Input } from '@/components/Input';
import {
  getWorkdaySummary,
  listProjects,
  Project,
  WorkdayFinding,
  WorkdayImportantTrace,
  WorkdaySummary,
} from '@/lib/api';

function shanghaiToday(): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

function formatCount(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value);
}

function formatCost(value: number): string {
  return value < 0.01 && value > 0 ? value.toFixed(6) : value.toFixed(2);
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  if (minutes < 60) return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes ? `${hours} 小时 ${restMinutes} 分` : `${hours} 小时`;
}

function formatTime(value: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
  });
}

function replayHref(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  if (typeof window === 'undefined') return `http://localhost:3001${path}`;
  return `${window.location.protocol}//${window.location.hostname}:3001${path}`;
}

export default function WorkdayPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState('');
  const [employeeId, setEmployeeId] = useState('');
  const [workDate, setWorkDate] = useState(shanghaiToday);
  const [includeTraces, setIncludeTraces] = useState(true);
  const [includeReplayRefs, setIncludeReplayRefs] = useState(true);
  const [includeRawMetrics, setIncludeRawMetrics] = useState(true);
  const [summary, setSummary] = useState<WorkdaySummary | null>(null);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    listProjects()
      .then((rows) => {
        if (!active) return;
        setProjects(rows);
        if (rows.length) setProjectId(rows[0].id);
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        setError(
          requestError instanceof Error ? requestError.message : '加载项目失败',
        );
      })
      .finally(() => {
        if (active) setLoadingProjects(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function generate(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !employeeId.trim() || !workDate || generating) return;
    setGenerating(true);
    setError('');
    setSummary(null);
    try {
      const result = await getWorkdaySummary(projectId, {
        employeeId: employeeId.trim(),
        date: workDate,
        includeTraces,
        includeReplayRefs: includeTraces && includeReplayRefs,
        includeRawMetrics,
      });
      setSummary(result);
    } catch (requestError: unknown) {
      setError(
        requestError instanceof Error ? requestError.message : '生成日报失败',
      );
    } finally {
      setGenerating(false);
    }
  }

  function toggleTraces(enabled: boolean) {
    setIncludeTraces(enabled);
    if (!enabled) setIncludeReplayRefs(false);
  }

  return (
    <div className="flex h-screen min-w-0 flex-col">
      <header className="flex min-h-16 items-center gap-3 border-b border-gray-200 bg-white px-4 py-3 md:px-6">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-gray-950">AI 工作日</h1>
          <p className="text-xs text-gray-500">Asia/Shanghai 业务日</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <form
          onSubmit={generate}
          className="border-b border-gray-200 bg-white px-4 py-4 md:px-6"
        >
          <div className="grid items-end gap-3 md:grid-cols-2 xl:grid-cols-[minmax(220px,1.25fr)_minmax(190px,1fr)_170px_auto]">
            <Field label="项目" htmlFor="workday-project">
              <select
                id="workday-project"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                disabled={loadingProjects || projects.length === 0}
                className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100 disabled:bg-gray-50 disabled:text-gray-400"
              >
                {projects.length === 0 && (
                  <option value="">
                    {loadingProjects ? '正在加载项目' : '暂无可访问项目'}
                  </option>
                )}
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name} ({project.environment})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="员工 ID" htmlFor="workday-employee">
              <Input
                id="workday-employee"
                value={employeeId}
                onChange={(event) => setEmployeeId(event.target.value)}
                placeholder="例如 employee-001"
                maxLength={200}
              />
            </Field>
            <Field label="工作日期" htmlFor="workday-date">
              <Input
                id="workday-date"
                type="date"
                value={workDate}
                onChange={(event) => setWorkDate(event.target.value)}
              />
            </Field>
            <Button
              type="submit"
              className="h-[38px] whitespace-nowrap"
              disabled={
                loadingProjects ||
                !projectId ||
                !employeeId.trim() ||
                !workDate ||
                generating
              }
            >
              {generating ? (
                <>
                  <LoadingDots /> 生成中
                </>
              ) : (
                <>
                  <CalendarCheck size={17} aria-hidden="true" />
                  生成日报
                </>
              )}
            </Button>
          </div>

          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
            <CheckOption
              checked={includeTraces}
              label="关键 Trace"
              onChange={toggleTraces}
            />
            <CheckOption
              checked={includeReplayRefs}
              disabled={!includeTraces}
              label="Replay 链接"
              onChange={setIncludeReplayRefs}
            />
            <CheckOption
              checked={includeRawMetrics}
              label="详细指标"
              onChange={setIncludeRawMetrics}
            />
          </div>
        </form>

        {error && (
          <div
            role="alert"
            className="mx-4 mt-5 flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 md:mx-6"
          >
            <AlertTriangle className="mt-0.5 shrink-0" size={17} aria-hidden="true" />
            <span className="min-w-0 break-words">{error}</span>
          </div>
        )}

        {!summary && !error && !generating && (
          <EmptyState
            icon=""
            title="选择项目、员工和日期后生成日报"
            hint="汇总仅使用结构化 Trace 指标"
          />
        )}

        {generating && (
          <div className="flex items-center justify-center gap-3 py-20 text-sm text-gray-500">
            <LoadingDots />
            正在聚合工作日数据
          </div>
        )}

        {summary?.status === 'no_data' && (
          <EmptyState
            icon=""
            title="当天没有匹配的工作数据"
            hint="请检查员工 ID、日期和 Trace 标签"
          />
        )}

        {summary?.status === 'ok' && (
          <Report
            includeRawMetrics={includeRawMetrics}
            includeTraces={includeTraces}
            summary={summary}
          />
        )}
      </div>
    </div>
  );
}

function Field({
  children,
  htmlFor,
  label,
}: {
  children: ReactNode;
  htmlFor: string;
  label: string;
}) {
  return (
    <label className="block min-w-0" htmlFor={htmlFor}>
      <span className="mb-1.5 block text-xs font-medium text-gray-600">{label}</span>
      {children}
    </label>
  );
}

function CheckOption({
  checked,
  disabled = false,
  label,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 text-xs text-gray-600">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500 disabled:opacity-50"
      />
      {label}
    </label>
  );
}

function Report({
  includeRawMetrics,
  includeTraces,
  summary,
}: {
  includeRawMetrics: boolean;
  includeTraces: boolean;
  summary: WorkdaySummary;
}) {
  const overview = summary.overview;
  const stats = [
    { label: '任务', value: formatCount(overview.task_count), icon: ListTodo, tone: 'emerald' },
    { label: 'Trace', value: formatCount(overview.trace_count), icon: Route, tone: 'blue' },
    { label: 'Span', value: formatCount(overview.span_count), icon: Activity, tone: 'cyan' },
    { label: 'LLM 调用', value: formatCount(overview.llm_call_count), icon: Bot, tone: 'violet' },
    { label: '工具调用', value: formatCount(overview.tool_call_count), icon: Wrench, tone: 'amber' },
    { label: '错误', value: formatCount(overview.error_count), icon: FileWarning, tone: 'rose' },
    { label: 'Tokens', value: formatCount(overview.total_tokens), icon: Gauge, tone: 'slate' },
    { label: '成本', value: formatCost(overview.total_cost), icon: CircleDollarSign, tone: 'lime' },
  ] as const;

  return (
    <div className="mx-auto max-w-[1500px] space-y-8 px-4 py-6 md:px-6">
      <section aria-labelledby="workday-overview">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h2 id="workday-overview" className="break-words text-xl font-semibold text-gray-950">
              {summary.employee.name} 的 AI 工作日
            </h2>
            <p className="mt-1 text-sm text-gray-500">
              {summary.date} · 员工 ID：{summary.employee.id}
            </p>
          </div>
          <div className="text-right text-xs text-gray-500">
            <div>{formatTime(overview.active_start)}</div>
            <div>至 {formatTime(overview.active_end)}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
          {stats.map((stat) => (
            <Metric key={stat.label} {...stat} />
          ))}
        </div>
        <div className="mt-3 grid gap-3 border-y border-gray-200 bg-white px-4 py-3 text-sm sm:grid-cols-3">
          <SmallMetric label="活跃时间范围" value={formatDuration(overview.active_time_range_seconds)} />
          <SmallMetric label="LLM 平均延迟" value={`${formatCount(Math.round(overview.avg_llm_latency_ms))} ms`} />
          <SmallMetric label="LLM P95 延迟" value={`${formatCount(Math.round(overview.p95_llm_latency_ms))} ms`} />
        </div>
      </section>

      {summary.narrative_summary && (
        <section aria-labelledby="workday-summary">
          <SectionTitle icon={Sparkles} id="workday-summary">确定性摘要</SectionTitle>
          <p className="max-w-5xl break-words text-sm leading-7 text-gray-700">
            {summary.narrative_summary}
          </p>
        </section>
      )}

      {summary.warnings.length > 0 && (
        <section aria-labelledby="workday-warnings">
          <SectionTitle icon={AlertTriangle} id="workday-warnings">数据提醒</SectionTitle>
          <div className="divide-y divide-amber-100 rounded-md border border-amber-200 bg-amber-50">
            {summary.warnings.map((warning) => (
              <div key={warning} className="break-words px-4 py-2.5 text-sm text-amber-900">
                {warning}
              </div>
            ))}
          </div>
        </section>
      )}

      <section aria-labelledby="workday-tasks">
        <SectionTitle icon={ListTodo} id="workday-tasks">任务拆分</SectionTitle>
        {summary.tasks.length === 0 ? (
          <p className="text-sm text-gray-500">暂无任务。</p>
        ) : (
          <div className="overflow-x-auto border-y border-gray-200 bg-white">
            <table className="min-w-[980px] w-full text-left text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500">
                <tr>
                  <TableHead>任务</TableHead>
                  <TableHead>活跃时长</TableHead>
                  <TableHead>Trace / Span</TableHead>
                  <TableHead>LLM / 工具</TableHead>
                  <TableHead>错误</TableHead>
                  <TableHead>Tokens</TableHead>
                  <TableHead>成本</TableHead>
                  <TableHead>LLM 平均延迟</TableHead>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {summary.tasks.map((task) => (
                  <tr key={task.task_id} className="align-top">
                    <td className="max-w-[280px] px-4 py-3">
                      <div className="break-words font-medium text-gray-900">{task.title}</div>
                      <div className="mt-1 break-all font-mono text-[11px] text-gray-400">{task.task_id}</div>
                    </td>
                    <TableCell>{formatDuration(task.duration_seconds)}</TableCell>
                    <TableCell>{task.trace_count} / {task.span_count}</TableCell>
                    <TableCell>{task.llm_call_count} / {task.tool_call_count}</TableCell>
                    <TableCell emphasis={task.error_count > 0}>{task.error_count}</TableCell>
                    <TableCell>{formatCount(task.total_tokens)}</TableCell>
                    <TableCell>{formatCost(task.total_cost)}</TableCell>
                    <TableCell>{formatCount(Math.round(task.avg_llm_latency_ms))} ms</TableCell>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="workday-findings">
        <SectionTitle icon={AlertTriangle} id="workday-findings">Findings</SectionTitle>
        {summary.findings.length === 0 ? (
          <p className="text-sm text-gray-500">没有命中成本、延迟或错误规则。</p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {summary.findings.map((finding, index) => (
              <FindingItem key={`${finding.title}-${index}`} finding={finding} />
            ))}
          </div>
        )}
      </section>

      {includeTraces && (
        <section aria-labelledby="workday-traces">
          <SectionTitle icon={Route} id="workday-traces">关键 Trace</SectionTitle>
          {summary.important_traces.length === 0 ? (
            <p className="text-sm text-gray-500">没有命中关键 Trace 规则。</p>
          ) : (
            <div className="divide-y divide-gray-200 border-y border-gray-200 bg-white">
              {summary.important_traces.map((trace) => (
                <TraceItem key={trace.trace_id} trace={trace} />
              ))}
            </div>
          )}
        </section>
      )}

      <section aria-labelledby="workday-candidates">
        <SectionTitle icon={Lightbulb} id="workday-candidates">蒸馏候选</SectionTitle>
        {summary.distillation_candidates.length === 0 ? (
          <p className="text-sm text-gray-500">暂无待复核候选。</p>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {summary.distillation_candidates.map((candidate) => (
              <article key={candidate.candidate_id} className="rounded-md border border-gray-200 bg-white p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
                    pending
                  </span>
                  <h3 className="min-w-0 break-words text-sm font-semibold text-gray-900">
                    {candidate.title}
                  </h3>
                </div>
                <p className="mt-2 break-words text-sm leading-6 text-gray-600">{candidate.reason}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {candidate.signals.map((signal) => (
                    <span key={signal} className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {signal}
                    </span>
                  ))}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {includeRawMetrics && summary.raw_metrics && (
        <section aria-labelledby="workday-raw">
          <SectionTitle icon={Gauge} id="workday-raw">详细指标</SectionTitle>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <RawMetric label="Prompt" value={summary.raw_metrics.prompt_tokens} />
            <RawMetric label="Completion" value={summary.raw_metrics.completion_tokens} />
            <RawMetric label="Reasoning" value={summary.raw_metrics.reasoning_tokens} />
            <RawMetric label="Cache Read" value={summary.raw_metrics.cache_read_input_tokens} />
            <RawMetric label="Total" value={summary.raw_metrics.total_tokens} />
          </div>
          <div className="mt-5 grid gap-6 xl:grid-cols-2">
            <UsageTable
              headers={['模型', '调用', 'Tokens', '成本']}
              rows={summary.raw_metrics.model_usage.map((model) => [
                model.name,
                formatCount(model.call_count),
                formatCount(model.total_tokens),
                formatCost(model.total_cost),
              ])}
              title="模型明细"
            />
            <UsageTable
              headers={['工具', '调用', '错误']}
              rows={summary.raw_metrics.tool_usage.map((tool) => [
                tool.name,
                formatCount(tool.call_count),
                formatCount(tool.error_count),
              ])}
              title="工具明细"
            />
          </div>
        </section>
      )}
    </div>
  );
}

const toneClass = {
  emerald: 'border-t-emerald-500 text-emerald-700',
  blue: 'border-t-blue-500 text-blue-700',
  cyan: 'border-t-cyan-500 text-cyan-700',
  violet: 'border-t-violet-500 text-violet-700',
  amber: 'border-t-amber-500 text-amber-700',
  rose: 'border-t-rose-500 text-rose-700',
  slate: 'border-t-gray-500 text-gray-700',
  lime: 'border-t-lime-500 text-lime-700',
} as const;

function Metric({
  icon: Icon,
  label,
  tone,
  value,
}: {
  icon: typeof Activity;
  label: string;
  tone: keyof typeof toneClass;
  value: string;
}) {
  return (
    <div className={`min-w-0 rounded-md border border-t-2 border-gray-200 bg-white p-3 ${toneClass[tone]}`}>
      <div className="flex items-center gap-1.5 text-xs text-gray-500">
        <Icon size={15} aria-hidden="true" />
        <span>{label}</span>
      </div>
      <div className="mt-2 break-all text-lg font-semibold text-gray-950">{value}</div>
    </div>
  );
}

function SmallMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 sm:block">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-0 sm:mt-1 font-medium text-gray-900">{value}</div>
    </div>
  );
}

function SectionTitle({
  children,
  icon: Icon,
  id,
}: {
  children: ReactNode;
  icon: typeof Activity;
  id: string;
}) {
  return (
    <h2 id={id} className="mb-3 flex items-center gap-2 text-base font-semibold text-gray-950">
      <Icon size={18} className="text-gray-500" aria-hidden="true" />
      {children}
    </h2>
  );
}

function TableHead({ children }: { children: ReactNode }) {
  return <th className="whitespace-nowrap px-4 py-2.5 font-medium">{children}</th>;
}

function TableCell({
  children,
  emphasis = false,
}: {
  children: ReactNode;
  emphasis?: boolean;
}) {
  return (
    <td className={`whitespace-nowrap px-4 py-3 ${emphasis ? 'font-semibold text-red-700' : 'text-gray-700'}`}>
      {children}
    </td>
  );
}

function FindingItem({ finding }: { finding: WorkdayFinding }) {
  const isHigh = finding.severity === 'high';
  return (
    <article className={`rounded-md border bg-white p-4 ${isHigh ? 'border-red-200' : 'border-amber-200'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${isHigh ? 'bg-red-50 text-red-700' : 'bg-amber-50 text-amber-800'}`}>
          {finding.severity}
        </span>
        <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
          {finding.finding_type}
        </span>
      </div>
      <h3 className="mt-3 break-words text-sm font-semibold text-gray-950">{finding.title}</h3>
      <p className="mt-1 break-words text-sm leading-6 text-gray-600">{finding.description}</p>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
        <span>阈值 {finding.threshold}</span>
        <span>实际 {finding.actual_value}</span>
        {finding.task_id && <span className="break-all font-mono">{finding.task_id}</span>}
      </div>
    </article>
  );
}

function TraceItem({ trace }: { trace: WorkdayImportantTrace }) {
  return (
    <article className="grid gap-3 px-4 py-4 lg:grid-cols-[minmax(200px,1.4fr)_repeat(5,minmax(70px,.5fr))_auto] lg:items-center">
      <div className="min-w-0">
        <div className="break-all font-mono text-sm font-medium text-gray-900">{trace.trace_id}</div>
        <div className="mt-1 break-all font-mono text-[11px] text-gray-400">{trace.task_id}</div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {trace.reasons.map((reason) => (
            <span key={reason} className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
              {reason}
            </span>
          ))}
        </div>
      </div>
      <TraceMetric label="时长" value={formatDuration(trace.duration_seconds)} />
      <TraceMetric label="Span" value={formatCount(trace.span_count)} />
      <TraceMetric label="LLM" value={formatCount(trace.llm_call_count)} />
      <TraceMetric label="工具" value={formatCount(trace.tool_call_count)} />
      <TraceMetric label="错误" value={formatCount(trace.error_count)} />
      {trace.replay_url ? (
        <a
          href={replayHref(trace.replay_url)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex w-fit items-center gap-1.5 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <ExternalLink size={15} aria-hidden="true" />
          打开 Trace
        </a>
      ) : (
        <span className="text-xs text-gray-400">Replay 已隐藏</span>
      )}
    </article>
  );
}

function TraceMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-gray-400">{label}</div>
      <div className="mt-0.5 text-sm font-medium text-gray-800">{value}</div>
    </div>
  );
}

function RawMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-gray-200 bg-white p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 break-all font-semibold text-gray-950">{formatCount(value)}</div>
    </div>
  );
}

function UsageTable({
  headers,
  rows,
  title,
}: {
  headers: string[];
  rows: string[][];
  title: string;
}) {
  return (
    <div className="min-w-0">
      <h3 className="mb-2 text-sm font-medium text-gray-800">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-gray-500">暂无明细。</p>
      ) : (
        <div className="overflow-x-auto border-y border-gray-200 bg-white">
          <table className="w-full min-w-[420px] text-left text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500">
              <tr>
                {headers.map((header) => <TableHead key={header}>{header}</TableHead>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((row) => (
                <tr key={row.join('|')}>
                  {row.map((cell, index) => (
                    <td key={`${index}-${cell}`} className={`px-4 py-2.5 ${index === 0 ? 'break-all font-medium text-gray-900' : 'whitespace-nowrap text-gray-600'}`}>
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
