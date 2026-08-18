import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MonitorSetupPage from './legacy-page';

const mocks = vi.hoisted(() => ({
  getAIMonitorStatus: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    getAIMonitorStatus: mocks.getAIMonitorStatus,
  };
});

const status = {
  project_id: null,
  project_ids: ['project-1', 'project-2'],
  employee_id: 'test1',
  employee_name: 'test1',
  summary: {
    cc_switch: 'installed',
    chatgpt_web_extension: 'missing',
    browser_shortcut: 'installed',
    chatgpt_desktop: 'unsupported',
  },
  devices: [
    {
      device_id: 'device-1',
      device_name: '研发电脑 01',
      employee_id: 'test1',
      employee_name: 'test1',
      installer_version: '2026-07-27',
      os: 'Windows',
      components: {
        cc_switch: {
          name: 'cc_switch',
          status: 'installed',
          version: '2026-07-27',
          last_seen_at: '2026-07-27T01:00:00Z',
          details: {},
        },
        browser_shortcut: {
          name: 'browser_shortcut',
          status: 'installed',
          version: '2026-07-27',
          last_seen_at: '2026-07-27T01:00:00Z',
          details: {},
        },
      },
      last_seen_at: '2026-07-27T01:00:00Z',
      created_at: '2026-07-27T01:00:00Z',
      updated_at: '2026-07-27T01:00:00Z',
    },
  ],
};

function dispatchExtensionStatus() {
  const event = new MessageEvent('message', {
    data: {
      type: 'AI_MONITOR_SETUP_STATUS',
      installed: true,
      version: '0.1.0',
      deviceId: 'device-1',
      at: '2026-07-27T01:02:00Z',
    },
  });
  Object.defineProperty(event, 'source', { value: window });
  window.dispatchEvent(event);
}

describe('MonitorSetupPage', () => {
  beforeEach(() => {
    mocks.getAIMonitorStatus.mockReset();
    mocks.getAIMonitorStatus.mockResolvedValue(status);
    window.localStorage.clear();
  });

  it('loads employee overall status and renders installer download', async () => {
    render(<MonitorSetupPage />);

    await screen.findByRole('heading', { name: 'AI Monitor 安装检测' });
    expect(await screen.findByText('研发电脑 01')).toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.getAIMonitorStatus).toHaveBeenCalledWith();
    });
    expect(screen.queryByLabelText('项目')).not.toBeInTheDocument();

    const links = screen.getAllByRole('link', { name: '下载一键安装器' });
    expect(links[0]).toHaveAttribute(
      'href',
      '/downloads/SmartBrain-AIMonitor-Setup-latest.exe',
    );
    expect(screen.getByText('CC Switch / Claude / Codex')).toBeInTheDocument();
    expect(screen.getByText('ChatGPT 桌面端个人账号')).toBeInTheDocument();
    expect(screen.getByText('已就绪 2/3')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '下载临时 Token Monitor' })).not.toBeInTheDocument();
  });

  it('uses the parent workspace height when embedded so the installer entry is not clipped', async () => {
    const { container } = render(<MonitorSetupPage embedded />);

    await screen.findByText('研发电脑 01');
    const shell = container.firstElementChild;
    expect(shell).toHaveClass('h-full', 'min-h-0');
    expect(shell).not.toHaveClass('h-screen');
  });

  it('lets admins query another employee id', async () => {
    const user = userEvent.setup();
    render(<MonitorSetupPage />);

    await screen.findByText('研发电脑 01');
    await user.type(screen.getByLabelText('员工 ID（管理员可填）'), 'test12');
    await user.click(screen.getByRole('button', { name: '重新检测' }));

    await waitFor(() => {
      expect(mocks.getAIMonitorStatus).toHaveBeenLastCalledWith('test12');
    });
  });

  it('uses the live browser extension ping for setup detection', async () => {
    render(<MonitorSetupPage />);

    await screen.findByText('研发电脑 01');
    dispatchExtensionStatus();

    expect(await screen.findByText('已就绪 3/3')).toBeInTheDocument();
    expect(screen.getByText('0.1.0')).toBeInTheDocument();
  });

});
