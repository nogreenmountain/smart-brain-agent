'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { CalendarDays, ClipboardList, FileUp, RefreshCw, Search, ShieldCheck, TriangleAlert, UsersRound } from 'lucide-react';

import { Card } from '@/components/Card';
import { PageBody, PageHeader, PageShell } from '@/components/PageLayout';
import {
  createMeetingSummary,
  listMeetingSummaries,
  listProjectCatalog,
  type MeetingSummary,
  type Project,
} from '@/lib/api';


function localDate(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

function canManage(project: Project | undefined): boolean {
  return project?.role === 'owner' || project?.role === 'admin';
}

export default function MeetingNotesPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState('');
  const [items, setItems] = useState<MeetingSummary[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [query, setQuery] = useState('');
  const [tag, setTag] = useState('');
  const [title, setTitle] = useState('');
  const [meetingDate, setMeetingDate] = useState(localDate());
  const [participants, setParticipants] = useState('');
  const [tags, setTags] = useState('');
  const [summary, setSummary] = useState('');
  const [decisions, setDecisions] = useState('');
  const [actionItems, setActionItems] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const selectedProject = projects.find((project) => project.id === projectId);
  const selected = useMemo(
    () => items.find((item) => item.id === selectedId) ?? items[0] ?? null,
    [items, selectedId],
  );

  const load = useCallback(async (targetProjectId: string, filters?: { query?: string; tag?: string }) => {
    if (!targetProjectId) return;
    setLoading(true);
    setError('');
    try {
      const data = await listMeetingSummaries({
        projectId: targetProjectId,
        query: filters?.query?.trim() || undefined,
        tag: filters?.tag?.trim() || undefined,
        limit: 100,
      });
      setItems(data.items);
      setSelectedId(data.items[0]?.id ?? '');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '会议记录加载失败');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    listProjectCatalog()
      .then((data) => {
        if (!active) return;
        setProjects(data);
        const initial = data[0]?.id ?? '';
        setProjectId(initial);
        if (initial) return load(initial);
        setLoading(false);
      })
      .catch((requestError) => {
        if (!active) return;
        setError(requestError instanceof Error ? requestError.message : '项目加载失败');
        setLoading(false);
      });
    return () => { active = false; };
  }, [load]);

  function handleSearch(event: FormEvent) {
    event.preventDefault();
    void load(projectId, { query, tag });
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !title.trim() || !meetingDate || (!summary.trim() && !file)) {
      setError('请填写会议标题、日期，并粘贴摘要或上传 Markdown/TXT 文件。');
      return;
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      await createMeetingSummary({
        projectId, title: title.trim(), meetingDate, participants, tags,
        summary, decisions, actionItems, file,
      });
      setTitle('');
      setParticipants('');
      setTags('');
      setSummary('');
      setDecisions('');
      setActionItems('');
      setFile(null);
      setNotice('会议摘要已保存，并可通过智慧大脑 MCP 检索。');
      await load(projectId, { query, tag });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '会议摘要上传失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <PageShell>
      <PageHeader
        eyebrow="项目会议长期记录"
        icon={ClipboardList}
        title="会议记录"
        description="直接粘贴或上传会议记录摘要，形成项目内可检索、可由 MCP 读取的标准 Markdown。"
        actions={(
          <button type="button" onClick={() => void load(projectId, { query, tag })} disabled={!projectId || loading} className="inline-flex h-10 items-center gap-2 rounded-md border border-[#cbd8e8] bg-white px-4 text-sm font-medium text-[#355170] hover:bg-[#f7f9fc] disabled:opacity-50">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />刷新
          </button>
        )}
      />
      <PageBody contentClassName="space-y-4">
        <Card className="p-4">
          <div className="flex items-start gap-3 text-sm leading-6 text-[#50627b]">
            <ShieldCheck size={19} className="mt-0.5 shrink-0 text-[#2c7a59]" />
            <p>所有已登录用户都可查看全部项目的会议摘要；只有项目负责人或管理员可以上传。</p>
          </div>
        </Card>

        <div className="grid min-w-0 gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
          <div className="space-y-4">
            <Card className="p-4">
              <label className="block text-xs font-medium text-[#50627b]">
                所属项目
                <select aria-label="所属项目" value={projectId} onChange={(event) => { setProjectId(event.target.value); void load(event.target.value); }} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] bg-white px-3 text-sm text-[#172844]">
                  {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                </select>
              </label>
            </Card>

            {canManage(selectedProject) ? (
              <Card className="p-4">
                <form onSubmit={handleCreate} className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-semibold text-[#172844]"><FileUp size={17} />上传会议摘要</div>
                  <label className="block text-xs font-medium text-[#50627b]">会议标题<input aria-label="会议标题" value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" placeholder="例如：产品研发周会" /></label>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block text-xs font-medium text-[#50627b]">会议日期<input aria-label="会议日期" type="date" value={meetingDate} onChange={(event) => setMeetingDate(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" /></label>
                    <label className="block text-xs font-medium text-[#50627b]">参会人<input value={participants} onChange={(event) => setParticipants(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" placeholder="逗号或换行分隔" /></label>
                  </div>
                  <label className="block text-xs font-medium text-[#50627b]">标签<input value={tags} onChange={(event) => setTags(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" placeholder="周会, MCP, 产品" /></label>
                  <label className="block text-xs font-medium text-[#50627b]">会议摘要<textarea aria-label="会议摘要" value={summary} onChange={(event) => setSummary(event.target.value)} className="mt-1 min-h-28 w-full resize-y rounded-md border border-[#cbd8e8] px-3 py-2 text-sm" placeholder="直接粘贴会议摘要；也可以在下方上传文件。" /></label>
                  <label className="block text-xs font-medium text-[#50627b]">关键决策<textarea value={decisions} onChange={(event) => setDecisions(event.target.value)} className="mt-1 min-h-20 w-full resize-y rounded-md border border-[#cbd8e8] px-3 py-2 text-sm" placeholder="每行一项" /></label>
                  <label className="block text-xs font-medium text-[#50627b]">行动项<textarea value={actionItems} onChange={(event) => setActionItems(event.target.value)} className="mt-1 min-h-20 w-full resize-y rounded-md border border-[#cbd8e8] px-3 py-2 text-sm" placeholder="负责人：任务（每行一项）" /></label>
                  <label className="block text-xs font-medium text-[#50627b]">上传 Markdown 或 TXT<input aria-label="上传 Markdown 或 TXT" type="file" accept=".md,.txt,text/markdown,text/plain" onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="mt-1 block w-full text-sm text-[#50627b] file:mr-3 file:h-9 file:rounded-md file:border-0 file:bg-[#edf4ff] file:px-3 file:text-[#315f9f]" /></label>
                  <button type="submit" disabled={saving} className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-brand-600 px-4 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"><FileUp size={16} />{saving ? '正在上传…' : '上传会议摘要'}</button>
                </form>
              </Card>
            ) : selectedProject ? (
              <Card className="p-4 text-sm leading-6 text-[#6e7d97]">你可以查看该项目会议摘要；上传需要项目负责人或管理员权限。</Card>
            ) : null}
          </div>

          <div className="min-w-0 space-y-4">
            <form onSubmit={handleSearch} className="grid gap-3 rounded-lg border border-[#d7e0ec] bg-white p-4 sm:grid-cols-[minmax(0,1fr)_180px_auto]">
              <label className="text-xs font-medium text-[#50627b]">搜索会议内容<input value={query} onChange={(event) => setQuery(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" placeholder="决策、行动项、参会人…" /></label>
              <label className="text-xs font-medium text-[#50627b]">标签<input value={tag} onChange={(event) => setTag(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-[#cbd8e8] px-3 text-sm" placeholder="周会" /></label>
              <button type="submit" disabled={!projectId || loading} className="inline-flex h-10 items-center justify-center gap-2 self-end rounded-md border border-[#cbd8e8] bg-white px-4 text-sm font-semibold text-[#355170] hover:bg-[#f7f9fc] disabled:opacity-50"><Search size={16} />检索</button>
            </form>

            {error && <div className="rounded-lg border border-[#efc9c9] bg-[#fff7f7] px-4 py-3 text-sm text-[#a33a3a]"><TriangleAlert size={16} className="mr-2 inline" />{error}</div>}
            {notice && <div className="rounded-lg border border-[#bee2cf] bg-[#f2fbf6] px-4 py-3 text-sm text-[#28714f]">{notice}</div>}

            {items.length > 0 ? (
              <div className="grid min-w-0 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
                <Card className="max-h-[calc(100vh-300px)] overflow-y-auto">
                  <div className="divide-y divide-[#edf1f6]">
                    {items.map((item) => (
                      <button key={item.id} type="button" onClick={() => setSelectedId(item.id)} className={`w-full px-4 py-3 text-left ${selected?.id === item.id ? 'bg-[#edf4ff]' : 'hover:bg-[#f8fafc]'}`}>
                        <div className="truncate text-sm font-semibold text-[#172844]">{item.title}</div>
                        <div className="mt-1 flex items-center gap-1 text-xs text-[#6e7d97]"><CalendarDays size={13} />{item.meeting_date}</div>
                        <div className="mt-2 flex flex-wrap gap-1">{item.tags.slice(0, 3).map((value) => <span key={value} className="rounded bg-[#eef2f7] px-1.5 py-0.5 text-[10px] text-[#50627b]">{value}</span>)}</div>
                      </button>
                    ))}
                  </div>
                </Card>
                {selected && (
                  <Card className="min-w-0 overflow-hidden">
                    <header className="border-b border-[#e5ebf3] px-5 py-4">
                      <h2 className="text-lg font-semibold text-[#172844]">{selected.title}</h2>
                      <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-[#6e7d97]"><span className="inline-flex items-center gap-1"><CalendarDays size={14} />{selected.meeting_date}</span><span className="inline-flex items-center gap-1"><UsersRound size={14} />{selected.participants.join('、') || '未填写参会人'}</span><span>上传人：{selected.created_by_name}</span></div>
                    </header>
                    <pre className="max-h-[calc(100vh-380px)] min-h-72 overflow-auto whitespace-pre-wrap break-words bg-[#fbfcfe] px-5 py-5 font-sans text-sm leading-7 text-[#243a57]">{selected.summary_markdown}</pre>
                  </Card>
                )}
              </div>
            ) : !loading && projectId ? (
              <Card className="flex min-h-64 flex-col items-center justify-center px-6 text-center"><ClipboardList size={30} className="text-[#8aa0ba]" /><p className="mt-3 text-base font-semibold text-[#253655]">暂无会议摘要</p><p className="mt-1 text-sm text-[#6e7d97]">项目负责人或管理员上传后，会在这里形成长期会议记录。</p></Card>
            ) : loading ? <Card className="flex min-h-64 items-center justify-center text-sm text-[#6e7d97]">正在加载会议记录…</Card> : null}
          </div>
        </div>
      </PageBody>
    </PageShell>
  );
}
