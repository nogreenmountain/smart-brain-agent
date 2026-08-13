'use client';

import { CSSProperties, FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  CalendarDays,
  Crown,
  Database,
  Gauge,
  Medal,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Trophy,
  Users,
  Zap,
} from 'lucide-react';

import { Button } from '@/components/Button';
import { EmptyState, LoadingDots } from '@/components/Feedback';
import { Input } from '@/components/Input';
import {
  AIUsageLeaderboardDistributionPoint,
  AIUsageLeaderboardMember,
  AIUsageLeaderboardResult,
  getAIUsageLeaderboard,
} from '@/lib/api';

const COLORS = ['#3979bf', '#17a58a', '#f0a23a', '#8b6ad9', '#df5a67', '#55a07a', '#6f87a8'];

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function shiftDate(value: string, days: number): string {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function formatCount(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value || 0);
}

function formatCompact(value: number): string {
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(value >= 1_000_000_000 ? 2 : 1)} 亿`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(value >= 100_000_000 ? 0 : 1)} 万`;
  return formatCount(value);
}

function initials(name: string): string {
  const text = name.trim();
  if (!text) return 'AI';
  return text.length <= 2 ? text : text.slice(0, 2).toUpperCase();
}

export default function LeaderboardPage({ embedded = false }: { embedded?: boolean } = {}) {
  const end = today();
  const [startDate, setStartDate] = useState(() => shiftDate(end, -29));
  const [endDate, setEndDate] = useState(end);
  const [result, setResult] = useState<AIUsageLeaderboardResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function load(start = startDate, finish = endDate) {
    if (start > finish) {
      setError('开始日期不能晚于结束日期');
      return;
    }
    setLoading(true);
    setError('');
    try {
      setResult(await getAIUsageLeaderboard({ startDate: start, endDate: finish }));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '加载排行榜失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(startDate, endDate);
    // The initial range is intentionally fixed at mount time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyPreset(days: number) {
    const finish = today();
    const start = shiftDate(finish, -(days - 1));
    setStartDate(start);
    setEndDate(finish);
    void load(start, finish);
  }

  function submitDates(event: FormEvent) {
    event.preventDefault();
    void load();
  }

  const topMembers = result?.members.slice(0, 3) ?? [];

  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden bg-[#eef3f9] text-[#10213e]">
      {!embedded && <header className="border-b border-[#d7e0ec] bg-white/95 px-4 py-4 backdrop-blur md:px-6">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[12px] font-bold tracking-[0.08em] text-brand-600">
              <Trophy size={15} aria-hidden={true} /> TEAM AI PULSE
            </div>
            <h1 className="mt-1 text-[26px] font-semibold leading-tight tracking-normal">AI Token 排行榜</h1>
            <p className="mt-1 text-sm leading-6 text-[#6e7d97]">全员可见的团队 AI 使用概览，展示排行、趋势与 Token 构成。</p>
          </div>
          <div className="flex-1" />
          <div className="rounded-full border border-[#cfe0f4] bg-[#f3f8ff] px-3 py-1.5 text-xs font-medium text-[#2463a9]">
            {result ? `${result.start_date} 至 ${result.end_date}` : `${startDate} 至 ${endDate}`}
          </div>
        </div>
      </header>}

      <main className="min-w-0 flex-1 overflow-y-auto px-4 py-5 md:px-6 md:py-6">
        <div className="mx-auto grid max-w-[1440px] gap-5">
          <section className="rounded-2xl border border-[#d7e0ec] bg-white p-4 shadow-[0_16px_38px_rgba(15,35,66,0.06)] md:p-5">
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex flex-wrap gap-2">
                {[7, 30, 90].map((days) => (
                  <button
                    key={days}
                    type="button"
                    onClick={() => applyPreset(days)}
                    className="rounded-lg border border-[#d7e0ec] bg-[#f8fafc] px-3 py-2 text-sm font-medium text-[#53647d] transition hover:border-brand-500/40 hover:bg-brand-500/5 hover:text-brand-700"
                  >
                    最近 {days} 天
                  </button>
                ))}
              </div>
              <form onSubmit={submitDates} className="flex flex-1 flex-wrap items-end justify-end gap-2">
                <DateField label="开始日期">
                  <Input type="date" value={startDate} max={endDate} onChange={(event) => setStartDate(event.target.value)} />
                </DateField>
                <DateField label="结束日期">
                  <Input type="date" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} />
                </DateField>
                <Button type="submit" disabled={loading}>
                  {loading ? <LoadingDots /> : <><RefreshCw size={15} aria-hidden={true} />更新</>}
                </Button>
              </form>
            </div>
            {error && <div className="mt-3 rounded-lg border border-[#df5a67]/25 bg-[#fff4f5] px-3 py-2 text-sm text-[#b83d49]">{error}</div>}
          </section>

          {loading && !result ? (
            <div className="rounded-2xl border border-[#d7e0ec] bg-white py-24 text-center text-[#6e7d97]"><LoadingDots /></div>
          ) : !result || result.members.length === 0 ? (
            <div className="rounded-2xl border border-[#d7e0ec] bg-white p-8">
              <EmptyState title="当前日期范围暂无 AI Token 数据" hint="可切换到最近 30 天或 90 天查看已同步的团队使用情况" />
            </div>
          ) : (
            <>
              <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <MetricCard icon={<Zap size={18} />} label="团队 Token" value={formatCompact(result.total_tokens)} detail={formatCount(result.total_tokens)} tone="blue" />
                <MetricCard icon={<Activity size={18} />} label="AI 请求" value={formatCompact(result.request_count)} detail={`${result.active_days} 个活跃日`} tone="green" />
                <MetricCard icon={<Users size={18} />} label="活跃成员" value={`${result.active_users} 人`} detail={`人均 ${formatCompact(result.average_tokens_per_user)}`} tone="violet" />
                <MetricCard icon={<Database size={18} />} label="官方统计覆盖" value={`${result.official_cc_switch_users} 人`} detail="CC Switch 官方日汇总" tone="amber" />
                <MetricCard icon={<Gauge size={18} />} label="日均 Token" value={formatCompact(result.total_tokens / Math.max(result.active_days, 1))} detail={`${result.period_days} 天统计窗口`} tone="rose" />
              </section>

              <section className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
                <div className="overflow-hidden rounded-2xl border border-[#d7e0ec] bg-white shadow-[0_16px_38px_rgba(15,35,66,0.05)]">
                  <SectionTitle icon={<Crown size={18} />} title="团队巅峰榜" subtitle="按所选日期范围的 Token 总量排名" />
                  <Podium members={topMembers} />
                </div>
                <div className="rounded-2xl border border-[#d7e0ec] bg-white p-5 shadow-[0_16px_38px_rgba(15,35,66,0.05)]">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="text-base font-semibold">团队 Token 趋势</h2>
                      <p className="mt-1 text-xs text-[#7a889d]">每日总量与团队活跃变化</p>
                    </div>
                    <span className="rounded-full bg-[#eef5ff] px-2.5 py-1 text-[11px] font-medium text-[#3979bf]">Asia/Shanghai</span>
                  </div>
                  <TrendChart points={result.daily_usage} />
                </div>
              </section>

              <section className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
                <DonutCard title="AI 来源构成" ariaLabel="AI 来源构成" points={result.source_usage} centerLabel="来源" />
                <DonutCard title="应用类型构成" ariaLabel="应用类型构成" points={result.app_usage} centerLabel="应用" />
                <DonutCard title="Token 构成" ariaLabel="Token 构成" points={result.token_usage} centerLabel="构成" />
              </section>

              <section className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(340px,0.75fr)]">
                <div className="overflow-hidden rounded-2xl border border-[#d7e0ec] bg-white shadow-[0_16px_38px_rgba(15,35,66,0.05)]">
                  <SectionTitle icon={<Trophy size={18} />} title="完整排行榜" subtitle="总量、占比、活跃度和单次使用强度" />
                  <RankingTable members={result.members} />
                </div>
                <div className="rounded-2xl border border-[#d7e0ec] bg-white p-5 shadow-[0_16px_38px_rgba(15,35,66,0.05)]">
                  <div className="flex items-center gap-2">
                    <Sparkles className="text-[#8b6ad9]" size={18} aria-hidden={true} />
                    <h2 className="text-base font-semibold">热门模型</h2>
                  </div>
                  <p className="mt-1 text-xs text-[#7a889d]">按 Token 消耗统计模型使用热度</p>
                  <ModelBars points={result.model_usage} />
                </div>
              </section>

              <section className="flex items-start gap-3 rounded-2xl border border-[#cfe0f4] bg-[#f4f8ff] p-4 text-sm text-[#53647d]">
                <ShieldCheck className="mt-0.5 shrink-0 text-[#3979bf]" size={18} aria-hidden={true} />
                <div>
                  <p className="font-medium text-[#253655]">统计公开，内容仍然私密</p>
                  <p className="mt-1 leading-6">{result.privacy_notice} CC Switch 覆盖完整时采用官方日汇总，其他情况使用已同步会话统计。</p>
                </div>
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function DateField({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1 text-xs font-medium text-[#6e7d97]"><span>{label}</span><span className="block w-40">{children}</span></label>;
}

function MetricCard({ icon, label, value, detail, tone }: { icon: ReactNode; label: string; value: string; detail: string; tone: 'blue' | 'green' | 'violet' | 'amber' | 'rose' }) {
  const tones = {
    blue: 'bg-[#eaf2ff] text-[#3979bf]',
    green: 'bg-[#eaf8f4] text-[#17a58a]',
    violet: 'bg-[#f1edfb] text-[#8b6ad9]',
    amber: 'bg-[#fff5e5] text-[#c47918]',
    rose: 'bg-[#fff0f2] text-[#c94d5b]',
  };
  return <article className="rounded-2xl border border-[#d7e0ec] bg-white p-4 shadow-[0_10px_26px_rgba(15,35,66,0.04)]"><div className={`flex h-9 w-9 items-center justify-center rounded-xl ${tones[tone]}`}>{icon}</div><p className="mt-3 text-xs font-medium text-[#7a889d]">{label}</p><p className="mt-1 text-2xl font-semibold tracking-tight text-[#10213e]">{value}</p><p className="mt-1 truncate text-[11px] text-[#8b99ae]" title={detail}>{detail}</p></article>;
}

function SectionTitle({ icon, title, subtitle }: { icon: ReactNode; title: string; subtitle: string }) {
  return <div className="flex items-center gap-3 border-b border-[#e3e9f1] bg-[#fbfcfe] px-5 py-4"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500/10 text-brand-600">{icon}</div><div><h2 className="text-base font-semibold">{title}</h2><p className="mt-0.5 text-xs text-[#7a889d]">{subtitle}</p></div></div>;
}

function Podium({ members }: { members: AIUsageLeaderboardMember[] }) {
  const arranged = [members[1], members[0], members[2]].filter(Boolean);
  const heights = ['h-28', 'h-36', 'h-24'];
  const colors = ['from-[#dfe7f1] to-[#f6f8fb]', 'from-[#ffe2a6] to-[#fff8e9]', 'from-[#f4c6a6] to-[#fff4ec]'];
  return <div className="grid min-h-[270px] grid-cols-3 items-end gap-3 bg-[radial-gradient(circle_at_50%_0%,rgba(74,123,255,0.09),transparent_48%)] px-4 pb-5 pt-7 md:px-8">{arranged.map((member, index) => <div key={member.employee_id} className="flex min-w-0 flex-col items-center"><div className={`flex h-14 w-14 items-center justify-center rounded-2xl border-4 border-white text-sm font-bold shadow-[0_10px_24px_rgba(15,35,66,0.13)] ${index === 1 ? 'bg-[#3979bf] text-white' : 'bg-[#eef2f7] text-[#50627b]'}`}>{initials(member.employee_name)}</div><p className="mt-2 max-w-full truncate text-sm font-semibold">{member.employee_name}</p><p className="text-[11px] text-[#8b99ae]">{member.account}</p><p className="mt-1 text-sm font-bold text-[#3979bf]">{formatCompact(member.total_tokens)}</p><div className={`mt-2 flex w-full max-w-36 flex-col items-center justify-start rounded-t-2xl bg-gradient-to-b pt-3 ${heights[index]} ${colors[index]}`}><span className="text-2xl font-bold text-[#53647d]">#{member.rank}</span><span className="mt-1 text-[11px] text-[#7a889d]">占团队 {member.share_percent}%</span></div></div>)}</div>;
}

function TrendChart({ points }: { points: AIUsageLeaderboardResult['daily_usage'] }) {
  const chartPoints = useMemo(() => {
    if (points.length === 0) return [];
    const max = Math.max(...points.map((item) => item.total_tokens), 1);
    return points.map((item, index) => ({
      ...item,
      x: points.length === 1 ? 400 : 28 + (index / (points.length - 1)) * 744,
      y: 178 - (item.total_tokens / max) * 138,
    }));
  }, [points]);
  const line = chartPoints.map((item) => `${item.x},${item.y}`).join(' ');
  const area = chartPoints.length ? `M ${chartPoints[0].x} 178 L ${line.replaceAll(' ', ' L ')} L ${chartPoints[chartPoints.length - 1].x} 178 Z` : '';
  return <div className="mt-4" role="img" aria-label="团队 Token 趋势"><svg viewBox="0 0 800 210" className="h-56 w-full overflow-visible"><defs><linearGradient id="leaderboard-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#3979bf" stopOpacity="0.32" /><stop offset="100%" stopColor="#3979bf" stopOpacity="0.02" /></linearGradient></defs>{[40, 86, 132, 178].map((y) => <line key={y} x1="28" x2="772" y1={y} y2={y} stroke="#e7ecf3" strokeWidth="1" />)}{area && <path d={area} fill="url(#leaderboard-area)" />}{line && <polyline points={line} fill="none" stroke="#3979bf" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />}{chartPoints.map((item, index) => <g key={item.date}><circle cx={item.x} cy={item.y} r="5" fill="#fff" stroke="#3979bf" strokeWidth="3"><title>{item.date} · {formatCount(item.total_tokens)} Tokens</title></circle>{(chartPoints.length <= 8 || index === 0 || index === chartPoints.length - 1) && <text x={item.x} y="199" textAnchor="middle" fontSize="10" fill="#8491a4">{item.date.slice(5)}</text>}</g>)}</svg><div className="-mt-2 flex items-center justify-between text-[11px] text-[#7a889d]"><span>峰值 {formatCompact(Math.max(...points.map((item) => item.total_tokens), 0))}</span><span>最近一天 {formatCompact(points.at(-1)?.total_tokens ?? 0)}</span></div></div>;
}

function DonutCard({ title, ariaLabel, points, centerLabel }: { title: string; ariaLabel: string; points: AIUsageLeaderboardDistributionPoint[]; centerLabel: string }) {
  let cursor = 0;
  const segments = points.map((point, index) => {
    const start = cursor;
    cursor += point.percentage;
    return `${COLORS[index % COLORS.length]} ${start}% ${cursor}%`;
  });
  const style: CSSProperties = { background: points.length ? `conic-gradient(${segments.join(', ')})` : '#eef2f7' };
  return <article className="rounded-2xl border border-[#d7e0ec] bg-white p-5 shadow-[0_14px_32px_rgba(15,35,66,0.05)]"><div className="flex items-center justify-between"><h2 className="text-base font-semibold">{title}</h2><span className="text-[11px] text-[#8b99ae]">按 Token</span></div><div className="mt-5 grid grid-cols-[128px_minmax(0,1fr)] items-center gap-5"><div className="relative h-32 w-32 rounded-full" style={style} role="img" aria-label={ariaLabel}><div className="absolute inset-5 flex flex-col items-center justify-center rounded-full bg-white shadow-inner"><span className="text-[11px] text-[#8b99ae]">{centerLabel}</span><span className="mt-1 text-sm font-semibold">{points.length} 类</span></div></div><div className="min-w-0 space-y-2.5">{points.slice(0, 5).map((point, index) => <div key={point.key} className="grid grid-cols-[10px_minmax(0,1fr)_auto] items-center gap-2 text-xs"><span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: COLORS[index % COLORS.length] }} /><span className="truncate text-[#53647d]" title={point.label}>{point.label}</span><span className="font-medium text-[#253655]">{point.percentage}%</span></div>)}</div></div></article>;
}

function RankingTable({ members }: { members: AIUsageLeaderboardMember[] }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[900px] border-collapse text-sm"><thead><tr className="border-b border-[#e3e9f1] bg-[#f8fafc] text-left text-[11px] font-semibold uppercase tracking-[0.04em] text-[#7a889d]"><th className="px-5 py-3">排名</th><th className="px-3 py-3">成员</th><th className="px-3 py-3 text-right">Token 总量</th><th className="px-3 py-3 text-right">团队占比</th><th className="px-3 py-3 text-right">请求</th><th className="px-3 py-3 text-right">活跃天数</th><th className="px-5 py-3 text-right">单次均值</th></tr></thead><tbody>{members.map((member) => <tr key={member.employee_id} className="border-b border-[#edf1f6] transition hover:bg-[#f8fbff]"><td className="px-5 py-4"><span className={`inline-flex h-8 w-8 items-center justify-center rounded-lg font-bold ${member.rank <= 3 ? 'bg-[#fff4d8] text-[#a8650d]' : 'bg-[#eef2f7] text-[#64748b]'}`}>{member.rank <= 3 ? <Medal size={16} aria-label={`第 ${member.rank} 名`} /> : member.rank}</span></td><td className="px-3 py-4"><div className="flex items-center gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500/10 text-xs font-bold text-brand-700">{initials(member.employee_name)}</div><div><div className="flex items-center gap-2 font-medium text-[#253655]">{member.employee_name}{member.official_cc_switch && <span className="rounded-full bg-[#eaf8f4] px-2 py-0.5 text-[10px] font-medium text-[#137f6d]">官方统计</span>}</div><div className="mt-0.5 text-[11px] text-[#8b99ae]">账号：{member.account}</div></div></div></td><td className="px-3 py-4 text-right"><div className="font-semibold text-[#253655]">{formatCompact(member.total_tokens)}</div><div className="text-[10px] text-[#8b99ae]">{formatCount(member.total_tokens)}</div></td><td className="px-3 py-4 text-right"><div className="font-medium">{member.share_percent}%</div><div className="ml-auto mt-1 h-1.5 w-20 overflow-hidden rounded-full bg-[#edf1f6]"><div className="h-full rounded-full bg-[#3979bf]" style={{ width: `${Math.min(member.share_percent * 1.7, 100)}%` }} /></div></td><td className="px-3 py-4 text-right">{formatCount(member.request_count)}</td><td className="px-3 py-4 text-right">{member.active_days}</td><td className="px-5 py-4 text-right font-medium">{formatCompact(member.average_tokens_per_request)}</td></tr>)}</tbody></table></div>;
}

function ModelBars({ points }: { points: AIUsageLeaderboardDistributionPoint[] }) {
  const max = Math.max(...points.map((item) => item.total_tokens), 1);
  return <div className="mt-5 space-y-4">{points.slice(0, 8).map((point, index) => <div key={point.key}><div className="mb-1.5 flex items-center justify-between gap-3 text-xs"><span className="truncate font-medium text-[#53647d]" title={point.label}>{index + 1}. {point.label}</span><span className="shrink-0 text-[#253655]">{formatCompact(point.total_tokens)}</span></div><div className="h-2.5 overflow-hidden rounded-full bg-[#edf1f6]"><div className="h-full rounded-full bg-gradient-to-r from-[#3979bf] to-[#67a7ea]" style={{ width: `${Math.max((point.total_tokens / max) * 100, 3)}%` }} /></div><div className="mt-1 text-right text-[10px] text-[#8b99ae]">{point.percentage}% · {formatCount(point.request_count)} 次</div></div>)}</div>;
}
