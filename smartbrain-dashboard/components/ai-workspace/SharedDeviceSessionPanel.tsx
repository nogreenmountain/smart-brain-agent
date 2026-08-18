'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, Clock3, Download, MonitorUp, RefreshCw, Square } from 'lucide-react';

import { Button } from '@/components/Button';
import { Input } from '@/components/Input';
import {
  AIMonitorStatus,
  createTemporaryMonitorProbe,
  getAIMonitorStatus,
  getCurrentSharedCCSwitchSession,
  getSharedCCSwitchSession,
  getTemporaryMonitorProbe,
  logout,
  SharedCCSwitchSession,
  SharedSessionStopMode,
  TemporaryMonitorProbe,
  startSharedCCSwitchSession,
  stopSharedCCSwitchSession,
  updateSharedCCSwitchSessionSchedule,
} from '@/lib/api';

const LOCAL_SESSION_KEY = 'smartbrain-shared-session';
const DOWNLOAD_URL = '/downloads/SmartBrain-Temporary-Token-Monitor-Setup-latest.exe';
const INSTALLATION_PROBE_TIMEOUT_MS = 15_000;
const INSTALLATION_PROBE_TIMEOUT_MESSAGE = '未收到临时 Token Monitor 的确认，请确认浏览器已允许打开本机应用，然后重新检测。';

function localDateTime(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
}

function launchLocalSession(url: string, afterLaunch?: () => void) {
  const launcher = document.createElement('a');
  launcher.href = url;
  launcher.hidden = true;
  launcher.setAttribute('aria-hidden', 'true');
  document.body.appendChild(launcher);
  launcher.click();
  launcher.remove();
  afterLaunch?.();
}

export function SharedDeviceSessionPanel({ status: suppliedStatus }: { status?: AIMonitorStatus | null } = {}) {
  const [status, setStatus] = useState<AIMonitorStatus | null>(suppliedStatus || null);
  const [session, setSession] = useState<SharedCCSwitchSession | null>(null);
  const [stopMode, setStopMode] = useState<SharedSessionStopMode>('default_19');
  const [customStop, setCustomStop] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [logoutSeconds, setLogoutSeconds] = useState<number | null>(null);
  const [probe, setProbe] = useState<TemporaryMonitorProbe | null>(null);
  const [probing, setProbing] = useState(false);
  const activeSessionId = session?.id;
  const activeSessionStatus = session?.status;

  useEffect(() => {
    let active = true;
    const statusRequest = suppliedStatus ? Promise.resolve(suppliedStatus) : getAIMonitorStatus();
    Promise.all([statusRequest, getCurrentSharedCCSwitchSession()])
      .then(([currentStatus, current]) => {
        if (!active) return;
        setStatus(currentStatus);
        setSession(current);
        if (current) setStopMode(current.stop_mode);
      })
      .catch((requestError: unknown) => {
        if (active) setError(requestError instanceof Error ? requestError.message : '加载临时记录失败');
      });
    return () => { active = false; };
  }, [suppliedStatus]);

  useEffect(() => {
    if (!status?.employee_id) return;
    try {
      const stored = JSON.parse(window.localStorage.getItem(LOCAL_SESSION_KEY) || 'null') as { sessionId?: string; employeeId?: string } | null;
      if (!stored?.sessionId || stored.employeeId !== status.employee_id) return;
      getSharedCCSwitchSession(stored.sessionId).then((current) => {
        if (current.status === 'finalized') {
          setSession(current);
          setLogoutSeconds(30);
        } else if (!['cancelled', 'expired'].includes(current.status)) {
          setSession(current);
        } else {
          window.localStorage.removeItem(LOCAL_SESSION_KEY);
        }
      }).catch(() => undefined);
    } catch {
      window.localStorage.removeItem(LOCAL_SESSION_KEY);
    }
  }, [status?.employee_id]);

  useEffect(() => {
    if (!activeSessionId || !activeSessionStatus || !['starting', 'active', 'finalizing', 'pending_sync'].includes(activeSessionStatus)) return;
    const timer = window.setInterval(() => {
      getSharedCCSwitchSession(activeSessionId).then((current) => {
        setSession(current);
        if (['cancelled', 'expired'].includes(current.status)) setError(current.error_message || '本机未能启动临时记录');
        if (current.status === 'finalized') setLogoutSeconds(30);
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeSessionId, activeSessionStatus]);

  useEffect(() => {
    if (logoutSeconds === null) return;
    if (logoutSeconds <= 0) {
      window.localStorage.removeItem(LOCAL_SESSION_KEY);
      void logout().finally(() => window.location.assign('/login'));
      return;
    }
    const timer = window.setTimeout(() => setLogoutSeconds((value) => value === null ? null : value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [logoutSeconds]);

  const probeId = probe?.id;
  const probeStatus = probe?.status;

  useEffect(() => {
    if (!probeId || probeStatus !== 'pending') return;
    let active = true;
    const timer = window.setInterval(() => {
      getTemporaryMonitorProbe(probeId).then((current) => {
        if (!active) return;
        setProbe(current);
        if (current.status !== 'pending') {
          setProbing(false);
          if (current.status !== 'detected') {
            setError('本次安装检测已失效，请重新检测临时 Token Monitor。');
          }
        }
      }).catch(() => undefined);
    }, 1000);
    const timeout = window.setTimeout(() => {
      active = false;
      window.clearInterval(timer);
      setProbing(false);
      setProbe(null);
      setError(INSTALLATION_PROBE_TIMEOUT_MESSAGE);
    }, INSTALLATION_PROBE_TIMEOUT_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.clearTimeout(timeout);
    };
  }, [probeId, probeStatus]);

  async function detectInstallation() {
    if (probing || busy) return;
    setProbing(true);
    setError('');
    try {
      const created = await createTemporaryMonitorProbe();
      setProbe(created);
      launchLocalSession(
        `smartbrain-temp-token://session?action=status&probe_id=${encodeURIComponent(created.id)}`
        + `&probe_token=${encodeURIComponent(created.probe_token || '')}`,
        () => setProbe(created),
      );
    } catch (requestError: unknown) {
      setProbing(false);
      setError(requestError instanceof Error ? requestError.message : '临时 Token Monitor 检测失败');
    }
  }

  async function start() {
    if (busy || probe?.status !== 'detected') return;
    setBusy(true);
    setError('');
    try {
      const created = await startSharedCCSwitchSession({
        installationProbeId: probe.id,
        stopMode,
        scheduledStopAt: stopMode === 'custom' && customStop ? new Date(customStop).toISOString() : undefined,
      });
      setSession(created);
      window.localStorage.setItem(LOCAL_SESSION_KEY, JSON.stringify({ sessionId: created.id, employeeId: created.target_employee_id }));
      launchLocalSession(`smartbrain-temp-token://session?action=start&session_id=${encodeURIComponent(created.id)}&activation_token=${encodeURIComponent(created.activation_token || '')}`);
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
      setSession(await stopSharedCCSwitchSession(session.id));
      launchLocalSession('smartbrain-temp-token://session?action=stop');
    } catch (requestError: unknown) {
      launchLocalSession('smartbrain-temp-token://session?action=stop');
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
      setSession(await updateSharedCCSwitchSessionSchedule(session.id, stopMode, stopMode === 'custom' && customStop ? new Date(customStop).toISOString() : undefined));
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : '修改停止时间失败');
    } finally {
      setBusy(false);
    }
  }

  function cancelAutomaticLogout() {
    window.localStorage.removeItem(LOCAL_SESSION_KEY);
    setLogoutSeconds(null);
    setSession(null);
  }

  const inactive = !session || ['cancelled', 'expired'].includes(session.status);
  return (
    <section className="rounded-xl border border-[#bfd3e8] bg-[#f8fbff] p-4 shadow-[0_10px_24px_rgba(15,35,66,0.04)] md:p-5">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-base font-semibold text-[#10213e]"><MonitorUp size={19} className="text-brand-600" />临时 Token Monitor</div>
          <p className="mt-2 text-sm text-[#53647d]">当前登录成员：{status?.employee_name || status?.employee_id || '正在确认账号'}</p>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-[#6e7d97]">本页按当前成员记录公用电脑上的 CC Switch 用量，不选择项目、不产生项目归属。记录期间每 2 分钟自动增量同步，停止时只补传尚未同步的尾段。</p>
        </div>
        <a href={DOWNLOAD_URL} className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-medium text-white shadow-sm hover:bg-brand-700"><Download size={17} />下载临时 Token Monitor</a>
      </div>

      {error && <p role="alert" className="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {inactive && (
        <div className="mt-4 flex flex-col gap-3 rounded-lg border border-[#d7e0ec] bg-white p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-[#253655]">
              {probe?.status === 'detected' ? <CheckCircle2 size={17} className="text-emerald-600" /> : <MonitorUp size={17} className="text-[#8b99ae]" />}
              {probe?.status === 'detected' ? '已检测到临时 Token Monitor' : '开始记录前请先检测本机安装状态'}
            </div>
            <p className="mt-1 text-xs text-[#6e7d97]">
              {probe?.status === 'detected'
                ? `版本 ${probe.installer_version || '-'} · 本机安装可供不同成员账号重复检测使用，无需重新安装。`
                : '检测只确认这台电脑已安装临时版；切换成员账号后重新点一次检测即可。'}
            </p>
          </div>
          <Button type="button" variant="secondary" disabled={probing || busy} onClick={detectInstallation}>
            <RefreshCw size={17} className={probing ? 'animate-spin' : ''} />
            {probing ? '检测中' : '检测临时 Token Monitor'}
          </Button>
        </div>
      )}
      {logoutSeconds !== null && <div className="mt-4 flex flex-col gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 sm:flex-row sm:items-center sm:justify-between"><span>本次已同步：{session?.request_count || 0} 次请求，{(session?.total_tokens || 0).toLocaleString('zh-CN')} Token。{logoutSeconds} 秒后自动退出智慧大脑。</span><Button type="button" size="sm" variant="secondary" onClick={cancelAutomaticLogout}>取消自动退出</Button></div>}

      {inactive ? (
        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(420px,1fr)_auto] lg:items-end">
          <fieldset className="grid gap-2 text-sm text-[#53647d] sm:grid-cols-3">
            <legend className="mb-1 text-xs font-medium">停止方式</legend>
            <label className="rounded-md border border-[#cbd8e8] bg-white px-3 py-2"><input type="radio" name="shared-stop" checked={stopMode === 'default_19'} onChange={() => setStopMode('default_19')} /><span className="ml-2">每天 19:00 自动停止并同步</span></label>
            <label className="rounded-md border border-[#cbd8e8] bg-white px-3 py-2"><input type="radio" name="shared-stop" checked={stopMode === 'custom'} onChange={() => setStopMode('custom')} /><span className="ml-2">自定义时间</span></label>
            <label className="rounded-md border border-[#cbd8e8] bg-white px-3 py-2"><input type="radio" name="shared-stop" checked={stopMode === 'manual_only'} onChange={() => setStopMode('manual_only')} /><span className="ml-2">使用结束后手动停止</span></label>
            {stopMode === 'custom' && <Input aria-label="自定义停止时间" type="datetime-local" value={customStop} onChange={(event) => setCustomStop(event.target.value)} className="sm:col-span-3" />}
          </fieldset>
          <Button type="button" disabled={busy || !status || probe?.status !== 'detected' || (stopMode === 'custom' && !customStop)} onClick={start}><MonitorUp size={17} />开始记录</Button>
        </div>
      ) : (
        <div className="mt-5 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Info label="当前成员" value={session.target_employee_name} />
            <Info label="本次 Token" value={session.total_tokens.toLocaleString('zh-CN')} />
            <Info label="请求数" value={session.request_count.toLocaleString('zh-CN')} />
            <Info label="最近同步" value={localDateTime(session.last_synced_at)} />
            <Info label="自动同步" value="每 2 分钟自动同步" />
          </div>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            {session.status === 'active' && <div className="grid flex-1 gap-2 sm:grid-cols-[220px_minmax(220px,1fr)_auto] sm:items-end"><label className="text-sm text-[#53647d]"><span className="mb-1 block text-xs font-medium">调整停止方式</span><select className="h-10 w-full rounded-md border border-[#cbd8e8] bg-white px-3 text-sm" value={stopMode} onChange={(event) => setStopMode(event.target.value as SharedSessionStopMode)}><option value="default_19">每天 19:00 自动停止</option><option value="custom">自定义停止时间</option><option value="manual_only">手动停止（24 小时安全截止）</option></select></label>{stopMode === 'custom' ? <Input aria-label="自定义停止时间" type="datetime-local" value={customStop} onChange={(event) => setCustomStop(event.target.value)} /> : <div />}<Button type="button" variant="secondary" disabled={busy || (stopMode === 'custom' && !customStop)} onClick={updateSchedule}><Clock3 size={17} />保存停止时间</Button></div>}
            <Button type="button" disabled={busy || session.status === 'finalizing'} onClick={stop}><Square size={16} />停止记录并完成最后同步</Button>
          </div>
          <p className="text-xs text-[#6e7d97]">计划停止：{localDateTime(session.scheduled_stop_at)}。如网络暂时中断，已同步数据不会丢失，安装器会保留固定停止边界并继续补传未同步尾段。</p>
        </div>
      )}
      {stopMode === 'manual_only' && inactive && <p className="mt-2 text-xs text-amber-700">不设置日常停止时间；为防止忘记关闭，最长记录 24 小时后自动停止并同步。</p>}
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border border-[#d7e0ec] bg-white px-3 py-2"><div className="text-xs text-[#8b99ae]">{label}</div><div className="mt-1 break-words text-sm font-medium text-[#253655]">{value}</div></div>;
}
