'use client';

import { useEffect, useMemo, useState } from 'react';
import { Clock3, MonitorUp, Square } from 'lucide-react';

import { Button } from '@/components/Button';
import { Input } from '@/components/Input';
import {
  AIMonitorStatus,
  getCurrentSharedCCSwitchSession,
  getSharedCCSwitchSession,
  listProjects,
  logout,
  Project,
  SharedCCSwitchSession,
  SharedSessionStopMode,
  startSharedCCSwitchSession,
  stopSharedCCSwitchSession,
  updateSharedCCSwitchSessionSchedule,
} from '@/lib/api';

const LOCAL_SESSION_KEY = 'smartbrain-shared-session';

function localDateTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
  });
}

function launchLocalSession(url: string) {
  const launcher = document.createElement('iframe');
  launcher.hidden = true;
  launcher.setAttribute('aria-hidden', 'true');
  launcher.src = url;
  document.body.appendChild(launcher);
  window.setTimeout(() => launcher.remove(), 5000);
}

export function SharedDeviceSessionPanel({ status }: { status: AIMonitorStatus | null }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState('');
  const [session, setSession] = useState<SharedCCSwitchSession | null>(null);
  const [stopMode, setStopMode] = useState<SharedSessionStopMode>('default_19');
  const [customStop, setCustomStop] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [logoutSeconds, setLogoutSeconds] = useState<number | null>(null);
  const sessionId = session?.id;
  const sessionStatus = session?.status;

  useEffect(() => {
    let active = true;
    Promise.all([listProjects(), getCurrentSharedCCSwitchSession()])
      .then(([projectRows, current]) => {
        if (!active) return;
        setProjects(projectRows);
        setProjectId(current?.project_id || projectRows[0]?.id || '');
        setSession(current);
        if (current) setStopMode(current.stop_mode);
      })
      .catch((requestError: unknown) => {
        if (active) setError(requestError instanceof Error ? requestError.message : '加载临时记录失败');
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!status?.employee_id) return;
    try {
      const stored = JSON.parse(window.localStorage.getItem(LOCAL_SESSION_KEY) || 'null') as {
        sessionId?: string;
        employeeId?: string;
      } | null;
      if (!stored?.sessionId || stored.employeeId !== status.employee_id) return;
      getSharedCCSwitchSession(stored.sessionId)
        .then((current) => {
          if (current.status === 'finalized') {
            setSession(current);
            setLogoutSeconds(30);
          } else if (!['cancelled', 'expired'].includes(current.status)) {
            setSession(current);
          } else {
            window.localStorage.removeItem(LOCAL_SESSION_KEY);
          }
        })
        .catch(() => undefined);
    } catch {
      window.localStorage.removeItem(LOCAL_SESSION_KEY);
    }
  }, [status?.employee_id]);

  useEffect(() => {
    if (!sessionId || !sessionStatus || !['starting', 'active', 'finalizing', 'pending_sync'].includes(sessionStatus)) return;
    const timer = window.setInterval(() => {
      getSharedCCSwitchSession(sessionId)
        .then((current) => {
          setSession(current);
          if (current.status === 'cancelled' || current.status === 'expired') {
            setError(current.error_message || '本机未能启动临时记录');
          }
          if (current.status === 'finalized') setLogoutSeconds(30);
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [sessionId, sessionStatus]);

  useEffect(() => {
    if (logoutSeconds === null) return;
    if (logoutSeconds <= 0) {
      window.localStorage.removeItem(LOCAL_SESSION_KEY);
      void logout().finally(() => {
        window.location.assign('/login');
      });
      return;
    }
    const timer = window.setTimeout(() => setLogoutSeconds((value) => value === null ? null : value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [logoutSeconds]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === projectId),
    [projectId, projects],
  );

  async function start() {
    if (!projectId || busy) return;
    setBusy(true);
    setError('');
    try {
      const created = await startSharedCCSwitchSession({
        projectId,
        stopMode,
        scheduledStopAt: stopMode === 'custom' && customStop
          ? new Date(customStop).toISOString()
          : undefined,
      });
      setSession(created);
      window.localStorage.setItem(
        LOCAL_SESSION_KEY,
        JSON.stringify({ sessionId: created.id, employeeId: created.target_employee_id }),
      );
      launchLocalSession(
        `smartbrain-ai-monitor://shared-session?action=start&session_id=${encodeURIComponent(created.id)}`
        + `&activation_token=${encodeURIComponent(created.activation_token || '')}`,
      );
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : '开始记录失败');
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!session || busy) return;
    setBusy(true);
    setError('');
    try {
      const stopped = await stopSharedCCSwitchSession(session.id);
      setSession(stopped);
      launchLocalSession('smartbrain-ai-monitor://shared-session?action=stop');
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : '停止同步失败');
    } finally {
      setBusy(false);
    }
  }

  async function updateSchedule() {
    if (!session || busy) return;
    setBusy(true);
    setError('');
    try {
      const updated = await updateSharedCCSwitchSessionSchedule(
        session.id,
        stopMode,
        stopMode === 'custom' && customStop ? new Date(customStop).toISOString() : undefined,
      );
      setSession(updated);
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : '修改停止时间失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-[#bfd3e8] bg-[#f8fbff] p-4 shadow-[0_10px_24px_rgba(15,35,66,0.04)]">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-[#10213e]">
            <MonitorUp size={18} className="text-brand-600" aria-hidden="true" />
            公用电脑临时记录
          </div>
          <p className="mt-1 text-sm text-[#53647d]">
            当前登录成员：{status?.employee_name || status?.employee_id || '正在确认账号'}
          </p>
          <p className="mt-1 text-xs leading-5 text-[#6e7d97]">
            只统计本次开始与停止之间的 CC Switch 请求；公用模式启用后不会再按安装账号执行个人整日同步。
          </p>
        </div>
        {session && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-800">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            {session.status === 'active' ? '正在记录' : session.status === 'starting' ? '正在启动' : '正在停止并同步'}
          </span>
        )}
      </div>

      {error && <p role="alert" className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {logoutSeconds !== null && (
        <div className="mt-3 flex flex-col gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 sm:flex-row sm:items-center sm:justify-between">
          <span>本次已同步：{session?.request_count || 0} 次请求，{(session?.total_tokens || 0).toLocaleString('zh-CN')} Token。{logoutSeconds} 秒后自动退出智慧大脑。</span>
          <Button type="button" size="sm" variant="secondary" onClick={() => setLogoutSeconds(null)}>取消自动退出</Button>
        </div>
      )}

      {!session || session.status === 'cancelled' || session.status === 'expired' ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(220px,0.8fr)_minmax(360px,1.2fr)_auto] lg:items-end">
          <label className="text-sm text-[#53647d]">
            <span className="mb-1 block text-xs font-medium">归属项目</span>
            <select className="h-10 w-full rounded-md border border-[#cbd8e8] bg-white px-3 text-sm" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
          </label>
          <fieldset className="grid gap-2 text-sm text-[#53647d] sm:grid-cols-3">
            <legend className="mb-1 text-xs font-medium">停止方式</legend>
            <label className="rounded-md border border-[#cbd8e8] bg-white px-3 py-2">
              <input type="radio" name="shared-stop" checked={stopMode === 'default_19'} onChange={() => setStopMode('default_19')} />
              <span className="ml-2">每天 19:00 自动停止并同步</span>
            </label>
            <label className="rounded-md border border-[#cbd8e8] bg-white px-3 py-2">
              <input type="radio" name="shared-stop" checked={stopMode === 'custom'} onChange={() => setStopMode('custom')} />
              <span className="ml-2">自定义时间</span>
            </label>
            <label className="rounded-md border border-[#cbd8e8] bg-white px-3 py-2">
              <input type="radio" name="shared-stop" checked={stopMode === 'manual_only'} onChange={() => setStopMode('manual_only')} />
              <span className="ml-2">使用结束后手动停止</span>
            </label>
            {stopMode === 'custom' && <Input aria-label="自定义停止时间" type="datetime-local" value={customStop} onChange={(event) => setCustomStop(event.target.value)} className="sm:col-span-3" />}
          </fieldset>
          <Button type="button" disabled={busy || !projectId || (stopMode === 'custom' && !customStop)} onClick={start}>
            <MonitorUp size={17} aria-hidden="true" /> 开始记录
          </Button>
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
              <Info label="成员" value={session.target_employee_name} />
              <Info label="项目" value={selectedProject?.name || session.project_id} />
              <Info label="停止时间" value={localDateTime(session.scheduled_stop_at)} />
          </div>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            {session.status === 'active' && (
              <div className="grid flex-1 gap-2 sm:grid-cols-[220px_minmax(220px,1fr)_auto] sm:items-end">
                <label className="text-sm text-[#53647d]">
                  <span className="mb-1 block text-xs font-medium">调整停止方式</span>
                  <select className="h-10 w-full rounded-md border border-[#cbd8e8] bg-white px-3 text-sm" value={stopMode} onChange={(event) => setStopMode(event.target.value as SharedSessionStopMode)}>
                    <option value="default_19">每天 19:00 自动停止</option>
                    <option value="custom">自定义停止时间</option>
                    <option value="manual_only">手动停止（24小时安全截止）</option>
                  </select>
                </label>
                {stopMode === 'custom' ? <Input aria-label="自定义停止时间" type="datetime-local" value={customStop} onChange={(event) => setCustomStop(event.target.value)} /> : <div />}
                <Button type="button" variant="secondary" disabled={busy || (stopMode === 'custom' && !customStop)} onClick={updateSchedule}><Clock3 size={17} />保存停止时间</Button>
              </div>
            )}
            <Button type="button" disabled={busy || session.status === 'finalizing'} onClick={stop}><Square size={16} />停止并同步</Button>
          </div>
        </div>
      )}
      {stopMode === 'manual_only' && !session && <p className="mt-2 text-xs text-amber-700">不设置日常停止时间；为防止忘记关闭，最长记录 24 小时后会自动停止并同步。</p>}
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border border-[#d7e0ec] bg-white px-3 py-2"><div className="text-xs text-[#8b99ae]">{label}</div><div className="mt-1 break-words text-sm font-medium text-[#253655]">{value}</div></div>;
}
