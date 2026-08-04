'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  FileText,
  Search,
} from 'lucide-react';

import { Button } from '@/components/Button';
import { LoadingDots } from '@/components/Feedback';
import { Input } from '@/components/Input';
import { PageHeader, PageShell } from '@/components/PageLayout';
import {
  AIDailyWorkLogList,
  AIUsageOptions,
  getAIDailyWorkLogs,
  getAIUsageOptions,
} from '@/lib/api';

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

export default function WorklogsPage() {
  const today = useMemo(shanghaiToday, []);
  const [options, setOptions] = useState<AIUsageOptions | null>(null);
  const [employeeId, setEmployeeId] = useState('');
  const [date, setDate] = useState(today);
  const [logs, setLogs] = useState<AIDailyWorkLogList | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [loadingLogs, setLoadingLogs] = useState(false);
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
          await loadLogs(loaded.mode, initialEmployee, today);
        }
      })
      .catch((requestError: unknown) => {
        if (active) setError(requestError instanceof Error ? requestError.message : '加载 AI 工作日志范围失败');
      })
      .finally(() => {
        if (active) setLoadingOptions(false);
      });
    return () => {
      active = false;
    };
    // The initial date is intentionally captured once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadLogs(
    modeOverride?: 'self' | 'admin',
    employeeOverride?: string,
    dateOverride?: string,
  ) {
    const mode = modeOverride ?? options?.mode;
    const selectedEmployee = employeeOverride ?? employeeId;
    const selectedDate = dateOverride ?? date;
    if (!mode || loadingLogs || !selectedDate) return;
    if (mode === 'admin' && !selectedEmployee) return;

    setLoadingLogs(true);
    setError('');
    setExpanded(new Set());
    try {
      setLogs(await getAIDailyWorkLogs({
        employeeId: mode === 'admin' ? selectedEmployee : undefined,
        startDate: selectedDate,
        endDate: selectedDate,
      }));
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : 'AI 工作日志查询失败');
    } finally {
      setLoadingLogs(false);
    }
  }

  function submitQuery(event: FormEvent) {
    event.preventDefault();
    void loadLogs();
  }

  function chooseDate(nextDate: string) {
    setDate(nextDate);
    setLogs(null);
    setExpanded(new Set());
  }

  function queryAdjacentDay(days: number) {
    const nextDate = shiftDate(date, days);
    if (nextDate > today) return;
    chooseDate(nextDate);
    void loadLogs(undefined, undefined, nextDate);
  }

  function selectEmployee(nextEmployeeId: string) {
    setEmployeeId(nextEmployeeId);
    setLogs(null);
    setExpanded(new Set());
    if (nextEmployeeId) void loadLogs('admin', nextEmployeeId, date);
  }

  function toggleLog(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const selectedEmployeeName = adminMode
    ? employeeOptions.find((item) => item.id === employeeId)?.name ?? '选择员工'
    : options?.current_employee.name ?? '正在确认账号权限';
  const items = logs?.items ?? [];

  return (
    <PageShell>
      <PageHeader
        eyebrow={adminMode ? 'TEAM AI WORK LOGS' : 'PERSONAL AI WORK LOGS'}
        icon={FileText}
        title={adminMode ? '团队 AI 工作日志' : '我的 AI 工作日志'}
        description={`${selectedEmployeeName} · Asia/Shanghai · 仅记录实际执行的 Agent 工作`}
        actions={
          !loadingOptions && options ? (
            <span className="inline-flex h-8 items-center rounded-md border border-[#cbd8e8] bg-[#f5f8fc] px-3 text-xs font-medium text-[#53647d]">
              {adminMode ? '管理员视图' : '仅本人可见'}
            </span>
          ) : undefined
        }
      />

      <main className="flex-1 overflow-y-auto">
        <form onSubmit={submitQuery} className="border-b border-[#d7e0ec] bg-white px-4 py-4 md:px-6">
          <div className="mx-auto flex max-w-[1320px] flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2 lg:max-w-[720px] lg:grid-cols-[minmax(260px,1fr)_180px]">
              {adminMode && (
                <Field label="员工" htmlFor="worklog-employee">
                  <select
                    id="worklog-employee"
                    className={selectClass}
                    value={employeeId}
                    onChange={(event) => selectEmployee(event.target.value)}
                  >
                    {employeeOptions.length === 0 && <option value="">暂无可查询员工</option>}
                    {employeeOptions.map((item) => (
                      <option key={item.id} value={item.id}>{item.name} ({item.email.split('@')[0]})</option>
                    ))}
                  </select>
                </Field>
              )}
              <Field label="日志日期" htmlFor="worklog-date">
                <Input
                  id="worklog-date"
                  type="date"
                  value={date}
                  max={today}
                  onChange={(event) => chooseDate(event.target.value)}
                />
              </Field>
            </div>

            <div className="flex w-full items-end gap-2 lg:w-auto">
              <div className="inline-flex h-10 shrink-0 items-center rounded-lg border border-[#d7e0ec] bg-[#f7f9fc] p-0.5">
                <button type="button" title="前一天" aria-label="前一天" onClick={() => queryAdjacentDay(-1)} className="flex h-9 w-9 items-center justify-center rounded-md text-[#53647d] hover:bg-white hover:text-[#10213e]">
                  <ChevronLeft size={17} aria-hidden="true" />
                </button>
                <button type="button" onClick={() => { chooseDate(today); void loadLogs(undefined, undefined, today); }} className="h-9 px-3 text-xs font-medium text-[#53647d] hover:bg-white hover:text-[#10213e]">
                  今天
                </button>
                <button type="button" title="后一天" aria-label="后一天" disabled={date >= today} onClick={() => queryAdjacentDay(1)} className="flex h-9 w-9 items-center justify-center rounded-md text-[#53647d] hover:bg-white hover:text-[#10213e] disabled:cursor-not-allowed disabled:text-[#b5bfce]">
                  <ChevronRight size={17} aria-hidden="true" />
                </button>
              </div>
              <Button type="submit" className="min-w-0 flex-1 sm:flex-none" disabled={loadingOptions || loadingLogs || !date || (adminMode && !employeeId)}>
                {loadingLogs ? <><LoadingDots /> 查询中</> : <><Search size={16} aria-hidden="true" /> 查询日志</>}
              </Button>
            </div>
          </div>
        </form>

        {error && <ErrorBanner message={error} />}

        <div className="mx-auto w-full max-w-[1320px] px-4 py-6 md:px-6">
          {loadingOptions || (loadingLogs && logs === null) ? (
            <div className="flex items-center justify-center gap-3 py-20 text-sm text-[#6c7b91]"><LoadingDots />正在读取 AI 工作日志</div>
          ) : logs === null ? (
            <CompactState title="选择日期后查询当天工作日志" />
          ) : items.length === 0 ? (
            <CompactState title={`${date} 暂无有效 Agent 工作日志`} hint="当晚 20:00 自动生成，只保留实际执行过的 Agent 工作" />
          ) : (
            <section aria-label="AI 工作日志列表" className="divide-y divide-[#dde4ee] border-y border-[#dde4ee] bg-white">
              {items.map((log) => {
                const isExpanded = expanded.has(log.id);
                return (
                  <article key={log.id}>
                    <button
                      type="button"
                      onClick={() => toggleLog(log.id)}
                      aria-expanded={isExpanded}
                      aria-label={`${isExpanded ? '收起' : '展开'} ${log.work_date} 工作日志`}
                      className="flex w-full items-center gap-3 px-4 py-4 text-left hover:bg-[#f8fafc] md:px-5"
                    >
                      {isExpanded ? <ChevronDown className="shrink-0 text-[#607086]" size={18} /> : <ChevronRight className="shrink-0 text-[#607086]" size={18} />}
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[#eaf2ff] text-[#2463a9]"><FileText size={17} /></span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-[#172844]">{log.work_date}</span>
                        <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[#6c7b91]">
                          <span>{log.work_items.length} 项工作</span>
                          <span>{log.source_count} 个来源会话</span>
                          <span className="inline-flex items-center gap-1"><Clock3 size={12} />{formatDateTime(log.generated_at)}</span>
                        </span>
                      </span>
                      <span className="hidden max-w-56 truncate rounded-md border border-[#d7e0ec] bg-[#f8fafc] px-2 py-1 text-[11px] text-[#6c7b91] sm:inline" title={log.model}>{log.model}</span>
                    </button>

                    {isExpanded && (
                      <div className="border-t border-[#edf1f6] bg-[#fbfcfe] px-4 py-5 md:px-5">
                        <div className="grid gap-x-8 gap-y-6 lg:grid-cols-2">
                          {log.work_items.map((item) => (
                            <div key={`${log.id}-${item.title}`} className="min-w-0 border-l-2 border-[#8eb4dd] pl-4">
                              <h2 className="text-sm font-semibold text-[#172844]">{item.title}</h2>
                              {item.problem && <p className="mt-2 text-sm leading-6 text-[#53647d]">{item.problem}</p>}
                              {item.actions.length > 0 && <WorklogList label="执行" values={item.actions} />}
                              {item.result && <div className="mt-3"><p className="text-[11px] font-medium text-[#7a879a]">结果</p><p className="mt-1 text-sm leading-6 text-[#334760]">{item.result}</p></div>}
                              {item.artifacts.length > 0 && <WorklogList label="产出" values={item.artifacts} />}
                              {item.validation.length > 0 && <WorklogList label="验证" values={item.validation} />}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </section>
          )}
        </div>
      </main>
    </PageShell>
  );
}

function Field({ children, htmlFor, label }: { children: React.ReactNode; htmlFor: string; label: string }) {
  return <label className="block min-w-0" htmlFor={htmlFor}><span className="mb-1.5 block text-xs font-medium text-[#53647d]">{label}</span>{children}</label>;
}

function ErrorBanner({ message }: { message: string }) {
  return <div role="alert" className="mx-4 mt-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 md:mx-6"><AlertTriangle className="mt-0.5 shrink-0" size={17} /><span className="min-w-0 break-words">{message}</span></div>;
}

function CompactState({ title, hint }: { title: string; hint?: string }) {
  return <div className="border-y border-[#dde4ee] bg-white px-4 py-8 text-center"><p className="text-sm font-medium text-[#53647d]">{title}</p>{hint && <p className="mt-1 text-xs text-[#8491a4]">{hint}</p>}</div>;
}

function WorklogList({ label, values }: { label: string; values: string[] }) {
  return <div className="mt-3"><p className="text-[11px] font-medium text-[#7a879a]">{label}</p><ul className="mt-1 space-y-1 text-sm leading-6 text-[#334760]">{values.map((value) => <li key={value} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[#6d91b8]" /><span className="min-w-0 break-words">{value}</span></li>)}</ul></div>;
}
