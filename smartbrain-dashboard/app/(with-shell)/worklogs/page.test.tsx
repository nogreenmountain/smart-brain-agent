import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import WorklogsPage from './page';

const mocks = vi.hoisted(() => ({
  getAIDailyWorkLogs: vi.fn(),
  getAIUsageOptions: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    getAIDailyWorkLogs: mocks.getAIDailyWorkLogs,
    getAIUsageOptions: mocks.getAIUsageOptions,
  };
});

const employee = {
  id: 'tangweixiang',
  name: '唐伟翔',
  email: 'tangweixiang@local.dev',
  project_ids: [],
};

const selfOptions = {
  mode: 'self' as const,
  current_employee: employee,
  departments: [],
  projects: [],
  employees: [],
};

const dailyLogs = {
  employee,
  timezone: 'Asia/Shanghai' as const,
  items: [{
    id: 'log-1',
    work_date: '2026-07-29',
    employee_id: employee.id,
    employee_name: employee.name,
    report_markdown: '## 完成登录模块修复',
    work_items: [{
      title: '完成登录模块修复',
      problem: '登录返回 401',
      actions: ['修改 auth.py'],
      result: '登录恢复正常',
      artifacts: ['auth.py'],
      validation: ['12 tests passed'],
    }],
    source_count: 1,
    model: 'claude-sonnet-4-6-20250514',
    generated_at: '2026-07-29T12:00:00Z',
  }],
};

describe('WorklogsPage', () => {
  beforeEach(() => {
    mocks.getAIUsageOptions.mockResolvedValue(selfOptions);
    mocks.getAIDailyWorkLogs.mockResolvedValue(dailyLogs);
  });

  it('queries one date and keeps work-log details collapsed by default', async () => {
    const user = userEvent.setup();
    render(<WorklogsPage />);

    expect(await screen.findByText('我的 AI 工作日志')).toBeInTheDocument();
    expect(screen.queryByText('完成登录模块修复')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '展开 2026-07-29 工作日志' }));
    expect(screen.getByText('完成登录模块修复')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '收起 2026-07-29 工作日志' }));
    expect(screen.queryByText('完成登录模块修复')).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('日志日期'), { target: { value: '2026-07-20' } });
    await user.click(screen.getByRole('button', { name: '查询日志' }));
    await waitFor(() => expect(mocks.getAIDailyWorkLogs).toHaveBeenLastCalledWith({
      employeeId: undefined,
      startDate: '2026-07-20',
      endDate: '2026-07-20',
    }));
  });

  it('lets administrators query an employees work log', async () => {
    const adminEmployee = { id: 'hanshangbo', name: '韩尚博', email: 'hanshangbo@local.dev', project_ids: [] };
    mocks.getAIUsageOptions.mockResolvedValueOnce({
      ...selfOptions,
      mode: 'admin' as const,
      current_employee: adminEmployee,
      employees: [employee, adminEmployee],
    });

    render(<WorklogsPage />);

    expect(await screen.findByText('团队 AI 工作日志')).toBeInTheDocument();
    expect(screen.getByLabelText('员工')).toHaveValue('hanshangbo');
    await waitFor(() => expect(mocks.getAIDailyWorkLogs).toHaveBeenCalledWith({
      employeeId: 'hanshangbo',
      startDate: expect.any(String),
      endDate: expect.any(String),
    }));
  });

  it('keeps regular users on their own work log when statistics options include everyone', async () => {
    mocks.getAIUsageOptions.mockResolvedValueOnce({
      ...selfOptions,
      mode: 'statistics' as const,
      employees: [
        employee,
        { id: 'test2', name: 'Test 2', email: 'test2@local.dev', project_ids: [] },
      ],
    });

    render(<WorklogsPage />);

    expect(await screen.findByText('我的 AI 工作日志')).toBeInTheDocument();
    expect(screen.queryByLabelText('员工')).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.getAIDailyWorkLogs).toHaveBeenCalledWith({
      employeeId: undefined,
      startDate: expect.any(String),
      endDate: expect.any(String),
    }));
  });
});
