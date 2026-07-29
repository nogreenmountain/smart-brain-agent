'use client';

import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Download,
  ExternalLink,
  MonitorCheck,
  RefreshCw,
  Search,
  ShieldCheck,
  XCircle,
} from 'lucide-react';

import { Button } from '@/components/Button';
import { EmptyState, LoadingDots } from '@/components/Feedback';
import { Input } from '@/components/Input';
import {
  AIMonitorComponentName,
  AIMonitorComponentStatus,
  AIMonitorStatus,
  getAIMonitorStatus,
} from '@/lib/api';

const DOWNLOAD_URL = '/downloads/ai-monitor-universal-latest.zip';

type ExtensionLiveStatus = {
  installed: boolean;
  version?: string;
  deviceId?: string;
  at?: string;
};

type SetupMessage = {
  type?: string;
  installed?: boolean;
  version?: string;
  deviceId?: string;
  at?: string;
};

const componentLabels: Record<AIMonitorComponentName, string> = {
  cc_switch: 'CC Switch / Claude / Codex',
  chatgpt_web_extension: 'ChatGPT 网页插件',
  browser_shortcut: '受监控网页快捷方式',
  chatgpt_desktop: 'ChatGPT 桌面端个人账号',
};

const componentDescriptions: Record<AIMonitorComponentName, string> = {
  cc_switch: '通过 CC Switch 转接的 Claude Code、Codex 调用会写入 Trace。',
  chatgpt_web_extension: '打开 ChatGPT 网页时同步项目、任务、聊天记录、token 估算和耗时。',
  browser_shortcut: '员工从桌面快捷方式启动浏览器，确保插件只在受控窗口里生效。',
  chatgpt_desktop: '个人账号桌面端暂不做本地强抓，正式方案走受监控网页或企业合规接口。',
};

const statusText: Record<AIMonitorComponentStatus, string> = {
  installed: '已安装',
  missing: '未检测到',
  unknown: '未知',
  unsupported: '暂不支持',
  error: '异常',
};

function statusClass(status: AIMonitorComponentStatus): string {
  if (status === 'installed') return 'border-emerald-200 bg-emerald-50 text-emerald-800';
  if (status === 'unsupported') return 'border-amber-200 bg-amber-50 text-amber-800';
  if (status === 'error') return 'border-red-200 bg-red-50 text-red-800';
  return 'border-gray-200 bg-gray-50 text-gray-600';
}

function StatusIcon({ status }: { status: AIMonitorComponentStatus }) {
  if (status === 'installed') {
    return <CheckCircle2 size={18} className="text-emerald-600" aria-hidden="true" />;
  }
  if (status === 'unsupported') {
    return <AlertTriangle size={18} className="text-amber-600" aria-hidden="true" />;
  }
  if (status === 'error') {
    return <XCircle size={18} className="text-red-600" aria-hidden="true" />;
  }
  return <Search size={18} className="text-gray-400" aria-hidden="true" />;
}

function formatTime(value?: string | null): string {
  if (!value) return '-';
  return new Date(value).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
  });
}

function effectiveSummary(
  status: AIMonitorStatus | null,
  liveExtension: ExtensionLiveStatus | null,
): Record<AIMonitorComponentName, AIMonitorComponentStatus> {
  const summary: Record<AIMonitorComponentName, AIMonitorComponentStatus> = {
    cc_switch: 'missing',
    chatgpt_web_extension: 'missing',
    browser_shortcut: 'missing',
    chatgpt_desktop: 'unsupported',
  };
  if (status) Object.assign(summary, status.summary);
  if (liveExtension?.installed) summary.chatgpt_web_extension = 'installed';
  summary.chatgpt_desktop = 'unsupported';
  return summary;
}

function installedCount(summary: Record<AIMonitorComponentName, AIMonitorComponentStatus>): number {
  return (['cc_switch', 'chatgpt_web_extension', 'browser_shortcut'] as AIMonitorComponentName[])
    .filter((name) => summary[name] === 'installed').length;
}

export default function MonitorSetupPage() {
  const [employeeId, setEmployeeId] = useState('');
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState<AIMonitorStatus | null>(null);
  const [liveExtension, setLiveExtension] = useState<ExtensionLiveStatus | null>(null);

  useEffect(() => {
    let active = true;
    setChecking(true);
    setError('');
    getAIMonitorStatus()
      .then((result) => {
        if (active) setStatus(result);
      })
      .catch((requestError: unknown) => {
        if (!active) return;
        setError(requestError instanceof Error ? requestError.message : '检测安装状态失败');
      })
      .finally(() => {
        if (active) {
          setChecking(false);
          setLoadingStatus(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    function askExtension() {
      window.postMessage({ type: 'AI_MONITOR_SETUP_STATUS_REQUEST' }, window.location.origin);
    }
    function onMessage(event: MessageEvent<SetupMessage>) {
      if (event.source !== window) return;
      const data = event.data;
      if (!data || data.type !== 'AI_MONITOR_SETUP_STATUS') return;
      setLiveExtension({
        installed: data.installed === true,
        version: data.version,
        deviceId: data.deviceId,
        at: data.at,
      });
    }
    window.addEventListener('message', onMessage);
    askExtension();
    const timer = window.setInterval(askExtension, 3000);
    return () => {
      window.removeEventListener('message', onMessage);
      window.clearInterval(timer);
    };
  }, []);

  async function checkStatus(event?: FormEvent) {
    event?.preventDefault();
    if (checking) return;
    setChecking(true);
    setError('');
    try {
      const result = await getAIMonitorStatus(employeeId.trim() || undefined);
      setStatus(result);
    } catch (requestError: unknown) {
      setError(requestError instanceof Error ? requestError.message : '检测安装状态失败');
    } finally {
      setChecking(false);
    }
  }

  const summary = useMemo(() => effectiveSummary(status, liveExtension), [status, liveExtension]);
  const readyCount = installedCount(summary);

  return (
    <div className="flex h-screen min-w-0 flex-col">
      <header className="flex min-h-16 flex-col items-start gap-3 border-b border-gray-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between md:px-6">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-gray-950">AI Monitor 安装检测</h1>
          <p className="text-xs text-gray-500">员工登录智慧大脑后下载统一安装包，安装完成再回到这里检测。</p>
        </div>
        <a
          href={DOWNLOAD_URL}
          className="inline-flex w-full shrink-0 items-center justify-center gap-1.5 rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 sm:w-auto"
        >
          <Download size={17} aria-hidden="true" />
          下载安装包
        </a>
      </header>

      <div className="flex-1 overflow-y-auto">
        <form
          onSubmit={checkStatus}
          className="border-b border-gray-200 bg-white px-4 py-4 md:px-6"
        >
          <div className="grid items-end gap-3 md:grid-cols-[minmax(220px,0.8fr)_auto_1fr]">
            <Field label="员工 ID（管理员可填）" htmlFor="monitor-employee">
              <Input
                id="monitor-employee"
                value={employeeId}
                onChange={(event) => setEmployeeId(event.target.value)}
                placeholder="留空检测当前登录账号"
                maxLength={200}
              />
            </Field>
            <Button
              type="submit"
              className="h-[38px] whitespace-nowrap"
              disabled={checking}
            >
              {checking ? (
                <>
                  <LoadingDots /> 检测中
                </>
              ) : (
                <>
                  <RefreshCw size={17} aria-hidden="true" />
                  重新检测
                </>
              )}
            </Button>
            <div className="text-xs leading-5 text-gray-500">
              当前页按成员整体统计 AI Monitor 状态，不再要求选择项目。
            </div>
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

        {loadingStatus && (
          <div className="flex items-center justify-center gap-3 py-20 text-sm text-gray-500">
            <LoadingDots />
            正在加载成员 AI Monitor 状态
          </div>
        )}

        {!loadingStatus && (
          <div className="space-y-5 px-4 py-5 md:px-6">
            <section className="rounded-md border border-gray-200 bg-white p-4">
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-medium text-gray-950">
                    <MonitorCheck size={18} className="text-brand-600" aria-hidden="true" />
                    成员整体状态
                  </div>
                  <p className="mt-1 text-sm text-gray-600">
                    {status
                      ? `${status.employee_name || status.employee_id} 的整体安装状态，最近登记设备 ${status.devices.length} 台。`
                      : '安装后回到本页点击重新检测，系统会读取服务器登记状态。'}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700">
                  <ShieldCheck size={17} className="text-emerald-600" aria-hidden="true" />
                  已就绪 {readyCount}/3
                </div>
              </div>
            </section>

            <section className="grid gap-3 lg:grid-cols-2">
              {(Object.keys(componentLabels) as AIMonitorComponentName[]).map((name) => {
                const component = status?.devices
                  .flatMap((device) => Object.entries(device.components))
                  .find(([key]) => key === name)?.[1];
                const currentStatus = summary[name];
                const version =
                  name === 'chatgpt_web_extension' && liveExtension?.version
                    ? liveExtension.version
                    : component?.version;
                const seenAt =
                  name === 'chatgpt_web_extension' && liveExtension?.at
                    ? liveExtension.at
                    : component?.last_seen_at;
                return (
                  <article
                    key={name}
                    className="rounded-md border border-gray-200 bg-white p-4"
                  >
                    <div className="flex items-start gap-3">
                      <StatusIcon status={currentStatus} />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h2 className="text-sm font-semibold text-gray-950">
                            {componentLabels[name]}
                          </h2>
                          <span
                            className={`rounded-md border px-2 py-0.5 text-xs ${statusClass(currentStatus)}`}
                          >
                            {statusText[currentStatus]}
                          </span>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-gray-600">
                          {componentDescriptions[name]}
                        </p>
                        <dl className="mt-3 grid gap-2 text-xs text-gray-500 sm:grid-cols-2">
                          <Info label="版本" value={version || '-'} />
                          <Info label="最近检测" value={formatTime(seenAt)} />
                        </dl>
                      </div>
                    </div>
                  </article>
                );
              })}
            </section>

            <section className="rounded-md border border-gray-200 bg-white p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-gray-950">
                <Activity size={18} className="text-brand-600" aria-hidden="true" />
                设备记录
              </div>
              {status?.devices.length ? (
                <div className="mt-3 overflow-x-auto">
                  <table className="min-w-full text-left text-sm">
                    <thead className="border-b border-gray-200 text-xs text-gray-500">
                      <tr>
                        <th className="whitespace-nowrap py-2 pr-4 font-medium">设备</th>
                        <th className="whitespace-nowrap py-2 pr-4 font-medium">安装包</th>
                        <th className="whitespace-nowrap py-2 pr-4 font-medium">系统</th>
                        <th className="whitespace-nowrap py-2 pr-4 font-medium">最近上报</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {status.devices.map((device) => (
                        <tr key={device.device_id}>
                          <td className="max-w-[260px] break-words py-2 pr-4 text-gray-900">
                            {device.device_name || device.device_id}
                          </td>
                          <td className="py-2 pr-4 text-gray-600">{device.installer_version || '-'}</td>
                          <td className="max-w-[260px] break-words py-2 pr-4 text-gray-600">{device.os || '-'}</td>
                          <td className="whitespace-nowrap py-2 pr-4 text-gray-600">
                            {formatTime(device.last_seen_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="mt-3 text-sm text-gray-500">
                  暂无设备登记。员工下载并运行安装包后，这里会显示 CC Switch 和网页监控安装状态。
                </p>
              )}
            </section>

            <section className="rounded-md border border-gray-200 bg-white p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="min-w-0">
                  <h2 className="text-sm font-semibold text-gray-950">安装入口</h2>
                  <p className="mt-1 text-sm text-gray-600">
                    普通浏览器检测不到插件时，请安装后刷新本页，或用桌面上的 ChatGPT Monitored 快捷方式打开。
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <a
                    href={DOWNLOAD_URL}
                    className="inline-flex items-center justify-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                  >
                    <Download size={17} aria-hidden="true" />
                    下载安装包
                  </a>
                  <a
                    href="/workday"
                    className="inline-flex items-center justify-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                  >
                    <ExternalLink size={17} aria-hidden="true" />
                    打开 AI 工作日
                  </a>
                </div>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <label className="block text-sm" htmlFor={htmlFor}>
      <span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>
      {children}
    </label>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-gray-400">{label}</dt>
      <dd className="mt-0.5 break-words text-gray-700">{value}</dd>
    </div>
  );
}
