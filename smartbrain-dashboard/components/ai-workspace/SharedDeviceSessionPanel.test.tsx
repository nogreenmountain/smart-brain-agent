import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SharedDeviceSessionPanel } from './SharedDeviceSessionPanel';

const mocks = vi.hoisted(() => ({
  createTemporaryMonitorProbe: vi.fn(),
  getTemporaryMonitorProbe: vi.fn(),
  getCurrentSharedCCSwitchSession: vi.fn(),
  getSharedCCSwitchSession: vi.fn(),
  listProjects: vi.fn(),
  startSharedCCSwitchSession: vi.fn(),
  stopSharedCCSwitchSession: vi.fn(),
  updateSharedCCSwitchSessionSchedule: vi.fn(),
  logout: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return { ...actual, ...mocks };
});

const status = {
  project_id: null,
  project_ids: [],
  employee_id: 'test1',
  employee_name: '测试成员',
  summary: {
    cc_switch: 'installed' as const,
    chatgpt_web_extension: 'missing' as const,
    browser_shortcut: 'installed' as const,
    chatgpt_desktop: 'unsupported' as const,
  },
  devices: [],
};

describe('SharedDeviceSessionPanel', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
    mocks.createTemporaryMonitorProbe.mockResolvedValue({
      id: 'probe-1',
      status: 'pending',
      probe_token: 'probe-token',
      expires_at: '2026-08-13T06:05:00Z',
    });
    mocks.getTemporaryMonitorProbe.mockResolvedValue({
      id: 'probe-1',
      status: 'detected',
      expires_at: '2026-08-13T06:05:00Z',
      detected_at: '2026-08-13T06:00:02Z',
      device_id: 'temp-device-1',
      installer_version: '2026.08.13.3',
    });
    mocks.getCurrentSharedCCSwitchSession.mockResolvedValue(null);
    mocks.listProjects.mockResolvedValue([
      { id: 'project-1', org_id: 'org-1', name: '不应读取的项目', environment: 'production' },
    ]);
    window.localStorage.clear();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  it('requires a successful installation probe before starting a member-level session', async () => {
    const user = userEvent.setup();
    mocks.startSharedCCSwitchSession.mockResolvedValue({
      id: 'session-1',
      project_id: null,
      target_employee_id: 'test1',
      target_employee_name: '测试成员',
      stop_mode: 'default_19',
      status: 'starting',
      requested_at: '2026-08-13T06:00:00Z',
      scheduled_stop_at: '2026-08-13T11:00:00Z',
      request_count: 0,
      total_tokens: 0,
      activation_token: 'activation-token',
    });

    render(<SharedDeviceSessionPanel status={status} />);

    expect(await screen.findByText('当前登录成员：测试成员')).toBeInTheDocument();
    expect(screen.queryByText('归属项目')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '下载临时 Token Monitor' })).toHaveAttribute(
      'href',
      '/downloads/SmartBrain-Temporary-Token-Monitor-Setup-latest.exe',
    );
    const startButton = screen.getByRole('button', { name: '开始记录' });
    expect(startButton).toBeDisabled();

    await user.click(screen.getByRole('button', { name: '检测临时 Token Monitor' }));
    await waitFor(() => {
      expect(mocks.createTemporaryMonitorProbe).toHaveBeenCalledTimes(1);
    });
    const clickMock = vi.mocked(HTMLAnchorElement.prototype.click);
    expect(clickMock).toHaveBeenCalled();
    const launched = clickMock.mock.contexts[0] as HTMLAnchorElement;
    expect(launched.href).toContain('smartbrain-temp-token://session?action=status');
    expect(launched.href).toContain('probe_id=probe-1');
    await waitFor(() => {
      expect(mocks.getTemporaryMonitorProbe).toHaveBeenCalledWith('probe-1');
    }, { timeout: 2500 });
    expect(await screen.findByText('已检测到临时 Token Monitor')).toBeInTheDocument();
    expect(startButton).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '开始记录' }));

    await waitFor(() => {
      expect(mocks.startSharedCCSwitchSession).toHaveBeenCalledWith({
        installationProbeId: 'probe-1',
        stopMode: 'default_19',
        scheduledStopAt: undefined,
      });
    });
    expect(mocks.listProjects).not.toHaveBeenCalled();
  });

  it('keeps start disabled when the installed monitor does not confirm the probe', async () => {
    const user = userEvent.setup();
    mocks.getTemporaryMonitorProbe.mockResolvedValue({
      id: 'probe-1',
      status: 'pending',
      expires_at: '2026-08-13T06:05:00Z',
    });

    render(<SharedDeviceSessionPanel status={status} />);
    await user.click(await screen.findByRole('button', { name: '检测临时 Token Monitor' }));

    expect(screen.getByRole('button', { name: '开始记录' })).toBeDisabled();
    expect(mocks.startSharedCCSwitchSession).not.toHaveBeenCalled();
  });

  it('stops an unanswered installation probe and explains how to retry', async () => {
    vi.useFakeTimers();
    mocks.getTemporaryMonitorProbe.mockResolvedValue({
      id: 'probe-1',
      status: 'pending',
      expires_at: '2026-08-13T06:05:00Z',
    });

    try {
      render(<SharedDeviceSessionPanel status={status} />);
      fireEvent.click(screen.getByRole('button', { name: '检测临时 Token Monitor' }));
      await act(async () => {
        await Promise.resolve();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });

      expect(screen.getByRole('alert')).toHaveTextContent(
        '未收到临时 Token Monitor 的确认，请确认浏览器已允许打开本机应用，然后重新检测。',
      );
      expect(screen.getByRole('button', { name: '检测临时 Token Monitor' })).toBeEnabled();
      const completedPolls = mocks.getTemporaryMonitorProbe.mock.calls.length;

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3_000);
      });
      expect(mocks.getTemporaryMonitorProbe).toHaveBeenCalledTimes(completedPolls);
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows incremental synchronization health for an active session', async () => {
    mocks.getCurrentSharedCCSwitchSession.mockResolvedValue({
      id: 'session-1',
      project_id: null,
      target_employee_id: 'test1',
      target_employee_name: '测试成员',
      stop_mode: 'manual_only',
      status: 'active',
      requested_at: '2026-08-13T06:00:00Z',
      started_at: '2026-08-13T06:00:00Z',
      scheduled_stop_at: '2026-08-14T06:00:00Z',
      request_count: 12,
      total_tokens: 3456,
      last_synced_at: '2026-08-13T06:04:00Z',
    });

    render(<SharedDeviceSessionPanel status={status} />);

    expect(await screen.findByText('3,456')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('每 2 分钟自动同步')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '停止记录并完成最后同步' })).toBeInTheDocument();
    expect(screen.queryByText('项目')).not.toBeInTheDocument();
  });
});
