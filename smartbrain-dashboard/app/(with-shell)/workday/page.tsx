'use client';

import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  Bot,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  Clock3,
  ExternalLink,
  FileText,
  Hash,
  MessageSquareText,
  Search,
  Sparkles,
  TriangleAlert,
  Zap,
} from 'lucide-react';

import { Button } from '@/components/Button';
import { EmptyState, LoadingDots } from '@/components/Feedback';
import { Input } from '@/components/Input';
import { PageHeader, PageShell } from '@/components/PageLayout';
import {
  AIUsageOptions,
  AIUsageQueryParams,
  AIUsageQueryResult,
  AIUsageRecord,
  AIUsageReport,
  AIUsageSource,
  createAIUsageReport,
  getAIUsageOptions,
  getAIUsageRecords,
} from '@/lib/api';

const SOURCE_LABELS: Record<string, string> = {
  cc_switch: 'CC Switch / 编程工具',
  chatgpt_web: 'ChatGPT 网页版',
  chatgpt_desktop: 'ChatGPT 桌面端',
  openai_compliance: 'OpenAI 合规接口',
  smartbrain: '智慧大脑',
};

const selectClass =
  'h-10 w-full rounded-lg border border-[#d7e0ec] bg-white px-3 text-sm text-[#10213e] outline-none transition focus:border-brand-500 focus:ring-4 focus:ring-brand-500/15 disabled:bg-[#f7f9fc] disabled:text-[#8b99ae]';

function shanghaiToday(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

function shiftDate(value: string, days: number): string {
  const date = new Date(`${value}T12:00:00+08:00`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatCount(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value);
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(value: number | null): string | null {
  if (value === null) return null;
  if (value < 1000) return `${value} ms`;
  const seconds = Math.round(value / 1000);
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`;
}

function replayHref(traceId: string): string {
  const path = `/traces?trace_id=${encodeURIComponent(traceId)}`;
  if (typeof window === 'undefined') return `http://localhost:3001${path}`;
  return `${window.location.protocol}//${window.location.hostname}:3001${path}`;
}

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

export default function WorkdayPage() {
  const today = useMemo(shanghaiToday, []);
  const [options, setOptions] = useState<AIUsageOptions | null>(null);
  const [employeeId, setEmployeeId] = useState('');
  const [startDate, setStartDate] = useState(() => shiftDate(today, -6));
  const [endDate, setEndDate] = useState(today);
  const [source, setSource] = useState<AIUsageSource | ''>('');
  const [result, setResult] = useState<AIUsageQueryResult | null>(null);
  const [report, setReport] = useState<AIUsageReport | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [loadingRecords, setLoadingRecords] = useState(false);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [error, setError] = useState('');

  const adminMode = options?.mode === 'admin';
  const employeeOptions = options?.employees ?? [];

  useEffect(() => {
    let active = true;
    getAIUsageOptions()
      .then(async (loaded) => {
        if (!active) return;
        setOptions(loaded);
        const initialEmployee = loaded.mode === 'admin' ? loaded.employees[0]?.id ?? '' : '';
        if (initialEmployee) setEmployeeId(initialEmployee);
        if (loaded.mode === 'self' || initialEmployee) {
          await loadRecords(loaded.mode, initialEmployee);
        }
      })
      .catch((requestError: unknown) => {
        if (active) setError(requestError instanceof Error ? requestError.message : '加载 AI 使用范围失败');
      })
      .finally(() => {
        if (active) setLoadingOptions(false);
      });
    return () => {
      active = false;
    };
    // The initial range is intentionally captured once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadRecords(modeOverride?: 'self' | 'admin', employeeOverride?: string) {
    const mode = modeOverride ?? options?.mode;
    if (!mode || loadingRecords) return;
    const selectedEmployee = employeeOverride ?? employeeId;
    if (startDate > endDate) {
      setError('开始日期不能晚于结束日期');
      return;
    }
    if (mode === 'admin' && !selectedEmployee) return;

    const params: AIUsageQueryParams = {
      startDate,
      endDate,
      employeeId: mode === 'admin' ? selectedEmployee : undefined,
      source: source || undefined,
      includeMessages: true,
      limit: 100,
    };
    setLoadingRecords(true);
    setError('');
    setReport(null);
    try {
      setResult(await getAIUsageRecords(params));
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'AI 使用记录查询失败');
    } finally {
      setLoadingRecords(false);
    }
  }

  function submitQuery(event: FormEvent) {
    event.preventDefault();
    void loadRecords();
  }

  function setRange(days: number) {
    setStartDate(shiftDate(today, -(days - 1)));
    setEndDate(today);
    setResult(null);
    setReport(null);
  }

  async function generateReport() {
    if (!adminMode || !employeeId || !result || generatingReport) return;
    setGeneratingReport(true);
    setError('');
    try {
      setReport(await createAIUsageReport({
        employeeId,
        startDate,
        endDate,
        source: source || undefined,
      }));
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'AI 使用工作报告生成失败');
    } finally {
      setGeneratingReport(false);
    }
  }

  function toggleRecord(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow={adminMode ? 'TEAM AI ACTIVITY' : 'PERSONAL AI ACTIVITY'}
        icon={CalendarDays}
        title={adminMode ? '团队 AI 使用' : '我的 AI 使用'}
        description={`${options?.current_employee.name ?? '正在确认账号权限'} · Asia/Shanghai · 按员工账号统计`}
        actions={
          <>
            {!loadingOptions && options && (
              <span className="inline-flex h-8 items-center rounded-md border border-[#cbd8e8] bg-[#f5f8fc] px-3 text-xs font-medium text-[#53647d]">
                {adminMode ? '管理员视图' : '仅本人可见'}
              </span>
            )}
            {result && (
              <div className="hidden text-right sm:block">
                <p className="text-xs text-[#6c7b91]">当前统计区间</p>
                <p className="text-sm font-medium text-[#253655]">{startDate} 至 {endDate}</p>
              </div>
            )}
          </>
        }
      />

      <main className="flex-1 overflow-y-auto">
        <form onSubmit={submitQuery} className="border-b border-[#d7e0ec] bg-white px-4 py-4 md:px-6">
          <div className="mx-auto max-w-[1320px]">
          {adminMode && (
            <div className="mb-3 grid gap-3 sm:grid-cols-[minmax(260px,420px)]">
              <Field label="员工" htmlFor="usage-employee">
                <select id="usage-employee" className={selectClass} value={employeeId} onChange={(event) => { setEmployeeId(event.target.value); setResult(null); setReport(null); }}>
                  {employeeOptions.length === 0 && <option value="">暂无可查询员工</option>}
                  {employeeOptions.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.email.split('@')[0]})</option>)}
                </select>
              </Field>
            </div>
          )}

          <div className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-[150px_150px_minmax(190px,1fr)_auto]">
            <Field label="开始日期" htmlFor="usage-start-date">
              <Input id="usage-start-date" type="date" value={startDate} max={endDate} onChange={(event) => { setStartDate(event.target.value); setResult(null); setReport(null); }} />
            </Field>
            <Field label="结束日期" htmlFor="usage-end-date">
              <Input id="usage-end-date" type="date" value={endDate} min={startDate} onChange={(event) => { setEndDate(event.target.value); setResult(null); setReport(null); }} />
            </Field>
            <Field label="AI 来源" htmlFor="usage-source">
              <select id="usage-source" className={selectClass} value={source} onChange={(event) => { setSource(event.target.value as AIUsageSource | ''); setResult(null); setReport(null); }}>
                <option value="">全部来源</option>
                {Object.entries(SOURCE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
            <Button type="submit" className="w-full lg:w-auto" disabled={loadingOptions || loadingRecords || (adminMode && !employeeId)}>
              {loadingRecords ? <><LoadingDots /> 查询中</> : <><Search size={16} aria-hidden="true" /> 查询记录</>}
            </Button>
          </div>
          <div className="mt-3 inline-flex h-9 items-center rounded-lg border border-[#d7e0ec] bg-[#f7f9fc] p-0.5">
            {[7, 30, 90].map((days) => (
              <button key={days} type="button" onClick={() => setRange(days)} className="h-8 rounded-md px-3 text-xs font-medium text-[#53647d] hover:bg-white hover:text-[#10213e]">
                近 {days} 天
              </button>
            ))}
          </div>
          </div>
        </form>

        {error && <ErrorBanner message={error} />}
        {(loadingOptions || loadingRecords) && !result && (
          <div className="flex items-center justify-center gap-3 py-24 text-sm text-[#6c7b91]"><LoadingDots />正在汇总 AI 使用记录</div>
        )}
        {!loadingOptions && !loadingRecords && !result && !error && (
          <EmptyState icon="" title={adminMode ? '选择员工后查询 AI 使用记录' : '选择日期区间后查询自己的 AI 使用记录'} />
        )}

        {result && (
          <div className="mx-auto w-full max-w-[1320px] px-4 py-6 md:px-6">
            <section aria-label="AI 使用概览" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <Metric icon={<Zap size={17} />} label="Token 总量" value={formatCount(result.summary.total_tokens)} detail={`${formatCount(result.summary.prompt_tokens)} 输入 · ${formatCount(result.summary.completion_tokens)} 输出`} tone="blue" />
              <Metric icon={<BarChart3 size={17} />} label="自然日均值" value={formatCount(result.summary.average_tokens_per_day)} detail={`按 ${result.summary.period_days} 个自然日计算`} tone="green" />
              <Metric icon={<MessageSquareText size={17} />} label="使用记录" value={formatCount(result.summary.record_count)} detail={`${result.summary.source_usage.length} 个 AI 来源`} tone="violet" />
              <Metric icon={<CalendarDays size={17} />} label="活跃天数" value={`${result.summary.active_days} 天`} detail={`覆盖区间 ${result.summary.period_days} 天`} tone="cyan" />
              <Metric icon={<TriangleAlert size={17} />} label="错误记录" value={formatCount(result.summary.error_count)} detail={result.summary.error_count ? '建议展开记录复盘' : '所选区间无已记录错误'} tone={result.summary.error_count ? 'red' : 'gray'} />
            </section>

            {result.warnings.length > 0 && (
              <div className="mt-4 space-y-2">
                {result.warnings.map((warning) => <div key={warning} className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"><AlertTriangle className="mt-0.5 shrink-0" size={15} />{warning}</div>)}
              </div>
            )}

            {result.summary.record_count === 0 ? (
              <EmptyState icon="" title="所选区间没有 AI 使用记录" hint="可调整日期或 AI 来源后重新查询" />
            ) : (
              <>
                <section className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(340px,0.75fr)]">
                  <UsageTrend result={result} />
                  <HourlyUsage result={result} />
                </section>

                <section className="mt-6 border-t border-[#dde4ee] pt-5">
                  <div className="flex flex-wrap items-end justify-between gap-3">
                    <div>
                      <h2 className="text-base font-semibold text-[#0b1930]">AI 使用记录</h2>
                      <p className="mt-1 text-xs text-[#6c7b91]">{result.employee.name} · 按员工账号汇总，不按项目切分</p>
                    </div>
                    {adminMode && (
                      <Button type="button" onClick={generateReport} disabled={generatingReport || result.summary.record_count === 0}>
                        {generatingReport ? <><LoadingDots /> 生成中</> : <><Sparkles size={16} /> 生成区间工作报告</>}
                      </Button>
                    )}
                  </div>
                  <div className="mt-3 divide-y divide-[#e4eaf2] border-y border-[#dde4ee] bg-white">
                    {result.records.map((record) => (
                      <UsageRecordRow key={record.id} record={record} expanded={expanded.has(record.id)} onToggle={() => toggleRecord(record.id)} />
                    ))}
                  </div>
                  {result.has_more && <p className="mt-3 text-center text-xs text-[#6c7b91]">记录较多，当前显示最近 100 条</p>}
                </section>
              </>
            )}

            {report && <ReportPanel report={report} />}
          </div>
        )}
      </main>
    </PageShell>
  );
}

function Field({ children, htmlFor, label }: { children: ReactNode; htmlFor: string; label: string }) {
  return <label className="block min-w-0" htmlFor={htmlFor}><span className="mb-1.5 block text-xs font-medium text-[#53647d]">{label}</span>{children}</label>;
}

function ErrorBanner({ message }: { message: string }) {
  return <div role="alert" className="mx-4 mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 md:mx-6"><AlertTriangle className="mt-0.5 shrink-0" size={17} /><span className="min-w-0 break-words">{message}</span></div>;
}

const TONES = {
  blue: 'bg-[#eaf2ff] text-[#2463a9]',
  green: 'bg-[#e8f6ef] text-[#23704c]',
  violet: 'bg-[#f0ecfb] text-[#6547a5]',
  cyan: 'bg-[#e7f5f7] text-[#22717b]',
  red: 'bg-[#fdecee] text-[#b84552]',
  gray: 'bg-[#eef1f5] text-[#607086]',
};

function Metric({ icon, label, value, detail, tone }: { icon: ReactNode; label: string; value: string; detail: string; tone: keyof typeof TONES }) {
  return <div className="min-w-0 rounded-lg border border-[#dde4ee] bg-white p-4"><div className="flex items-center gap-2 text-xs font-medium text-[#6c7b91]"><span className={`flex h-7 w-7 items-center justify-center rounded-md ${TONES[tone]}`}>{icon}</span>{label}</div><p className="mt-3 truncate text-2xl font-semibold text-[#0b1930]">{value}</p><p className="mt-1 truncate text-[11px] text-[#8491a4]" title={detail}>{detail}</p></div>;
}

function UsageTrend({ result }: { result: AIUsageQueryResult }) {
  const points = result.summary.daily_usage.slice(-31);
  const max = Math.max(...points.map((item) => item.total_tokens), 1);
  return <section><div className="flex items-baseline justify-between gap-3"><h2 className="text-sm font-semibold text-[#0b1930]">每日 Token</h2><span className="text-[11px] text-[#8491a4]">{result.summary.daily_usage.length > 31 ? '最近 31 天' : `${result.summary.start_date} 至 ${result.summary.end_date}`}</span></div><div className="mt-3 flex h-52 items-end gap-1.5 border-b border-[#cfd8e5] bg-white px-3 pt-4" role="img" aria-label="每日 Token 趋势"><div className="flex h-full w-full items-end gap-1.5">{points.map((item) => { const height = item.total_tokens ? Math.max((item.total_tokens / max) * 100, 4) : 1; return <div key={item.date} className="group flex min-w-0 flex-1 flex-col items-center justify-end" title={`${item.date} · ${formatCount(item.total_tokens)} Tokens`}><div className="w-full max-w-8 rounded-t-sm bg-[#3979bf] transition group-hover:bg-[#245f9e]" style={{ height: `${height}%` }} /><span className="mt-1 hidden text-[9px] text-[#8491a4] 2xl:block">{item.date.slice(5)}</span></div>; })}</div></div><div className="mt-2 flex flex-wrap gap-2">{result.summary.source_usage.map((item) => <span key={item.source} className="rounded-md bg-white px-2 py-1 text-[11px] text-[#53647d]"><span className="font-medium text-[#253655]">{sourceLabel(item.source)}</span> · {formatCount(item.total_tokens)}</span>)}</div></section>;
}

function HourlyUsage({ result }: { result: AIUsageQueryResult }) {
  const max = Math.max(...result.summary.hourly_usage.map((item) => item.total_tokens), 1);
  const top = [...result.summary.hourly_usage].filter((item) => item.total_tokens > 0).sort((a, b) => b.total_tokens - a.total_tokens)[0];
  return <section><div className="flex items-baseline justify-between gap-3"><h2 className="text-sm font-semibold text-[#0b1930]">高频使用时段</h2><span className="text-[11px] text-[#8491a4]">{top ? `${String(top.hour).padStart(2, '0')}:00-${String((top.hour + 1) % 24).padStart(2, '0')}:00` : '暂无'}</span></div><div className="mt-3 grid h-52 grid-cols-[repeat(24,minmax(0,1fr))] items-end gap-x-1 border-b border-[#cfd8e5] bg-white px-3 pt-4">{result.summary.hourly_usage.map((item) => <div key={item.hour} className="flex h-full min-w-0 flex-col items-center justify-end" title={`${String(item.hour).padStart(2, '0')}:00 · ${formatCount(item.total_tokens)} Tokens`}><div className="w-full max-w-4 rounded-t-sm bg-[#55a07a]" style={{ height: `${item.total_tokens ? Math.max((item.total_tokens / max) * 100, 5) : 1}%` }} /><span className="mt-1 text-[8px] text-[#8491a4]">{item.hour % 3 === 0 ? String(item.hour).padStart(2, '0') : ''}</span></div>)}</div></section>;
}

function UsageRecordRow({ record, expanded, onToggle }: { record: AIUsageRecord; expanded: boolean; onToggle: () => void }) {
  const duration = formatDuration(record.duration_ms);
  return <article className="min-w-0"><button type="button" onClick={onToggle} className="flex w-full items-start gap-3 px-3 py-3 text-left hover:bg-[#f8fafc] md:px-4" aria-expanded={expanded} aria-label={record.title}>{expanded ? <ChevronDown className="mt-1 shrink-0 text-[#6c7b91]" size={17} /> : <ChevronRight className="mt-1 shrink-0 text-[#6c7b91]" size={17} />}<span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${record.record_type === 'chat' ? 'bg-[#eaf2ff] text-[#2463a9]' : 'bg-[#eef1f5] text-[#607086]'}`}>{record.record_type === 'chat' ? <MessageSquareText size={16} /> : <Bot size={16} />}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-[#172844]">{record.title}</span><span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[#6c7b91]"><span>{formatDateTime(record.started_at)}</span><span>{sourceLabel(record.source)}</span>{record.model && <span>{record.model}</span>}{duration && <span>{duration}</span>}</span></span><span className="shrink-0 text-right"><span className="block text-sm font-semibold text-[#253655]">{formatCount(record.total_tokens)}</span><span className="text-[10px] text-[#8491a4]">Tokens</span></span></button>{expanded && <div className="border-t border-[#edf1f6] bg-[#f8fafc] px-4 py-4 md:pl-[76px] md:pr-5"><div className="flex flex-wrap gap-2 text-[11px]"><Badge icon={<Hash size={12} />} text={record.task_title ?? record.task_id} /><Badge icon={<Bot size={12} />} text={record.model ?? '模型未上报'} />{record.error_count > 0 && <Badge icon={<TriangleAlert size={12} />} text={`${record.error_count} 个错误`} danger />}{record.trace_id && <a href={replayHref(record.trace_id)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-md border border-[#cbd8e8] bg-white px-2 py-1 font-medium text-[#2463a9] hover:border-[#8eb4dd]"><ExternalLink size={12} />打开 Trace</a>}</div>{record.messages && record.messages.length > 0 ? <div className="mt-4 space-y-3">{record.messages.map((message, index) => <div key={`${record.id}-${index}`} className={`max-w-4xl rounded-lg border px-3 py-2.5 text-sm leading-6 ${message.role === 'user' ? 'border-[#cfe0f4] bg-white text-[#1d3554]' : 'border-[#dbe7df] bg-[#f3faf6] text-[#234536]'}`}><p className="mb-1 text-[10px] font-semibold uppercase text-[#78869a]">{message.role === 'user' ? '用户' : message.role === 'assistant' ? 'AI' : message.role}</p><p className="whitespace-pre-wrap break-words">{message.content}</p></div>)}</div> : <p className="mt-4 text-xs text-[#6c7b91]">该记录暂未同步到可展开的对话正文。</p>}</div>}</article>;
}

function Badge({ icon, text, danger = false }: { icon: ReactNode; text: string; danger?: boolean }) {
  return <span className={`inline-flex max-w-full items-center gap-1 rounded-md border px-2 py-1 ${danger ? 'border-red-200 bg-red-50 text-red-700' : 'border-[#d7e0ec] bg-white text-[#53647d]'}`}>{icon}<span className="truncate">{text}</span></span>;
}

function ReportPanel({ report }: { report: AIUsageReport }) {
  const sections = report.report.split(/(?=^##\s)/m).map((item) => item.trim()).filter(Boolean);
  return <section className="mt-7 border-t-2 border-[#b9c9dc] pt-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><FileText size={18} className="text-[#3979bf]" /><h2 className="text-base font-semibold text-[#0b1930]">AI 使用工作报告</h2></div><p className="mt-1 text-xs text-[#6c7b91]">{report.employee.name} · {report.summary.start_date} 至 {report.summary.end_date}</p></div><span className="rounded-md border border-[#d7e0ec] bg-white px-2 py-1 text-[11px] text-[#6c7b91]">{report.model}</span></div><div className="mt-4 grid gap-3 sm:grid-cols-3"><MiniFact icon={<Clock3 size={15} />} label="高频时段" value={report.high_frequency_periods.join('、') || '暂无'} /><MiniFact icon={<Zap size={15} />} label="Token 总量" value={formatCount(report.summary.total_tokens)} /><MiniFact icon={<BarChart3 size={15} />} label="自然日均值" value={formatCount(report.summary.average_tokens_per_day)} /></div><div className="mt-5 grid gap-x-8 gap-y-5 lg:grid-cols-2">{sections.map((section) => { const [heading, ...body] = section.split('\n'); return <div key={heading} className="border-l-2 border-[#8eb4dd] pl-4"><h3 className="text-sm font-semibold text-[#172844]">{heading.replace(/^##\s*/, '')}</h3><p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-[#465873]">{body.join('\n').trim().replace(/\*\*/g, '')}</p></div>; })}</div></section>;
}

function MiniFact({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="rounded-lg border border-[#dde4ee] bg-white px-3 py-3"><div className="flex items-center gap-1.5 text-[11px] text-[#6c7b91]">{icon}{label}</div><p className="mt-1.5 truncate text-sm font-semibold text-[#253655]" title={value}>{value}</p></div>;
}
