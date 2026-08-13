import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import WorkdayPage from './legacy-page';

const mocks = vi.hoisted(() => ({
  getAIUsageOptions: vi.fn(),
  getAIUsageRecords: vi.fn(),
  getCCSwitchUsageSyncStatus: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    getAIUsageOptions: mocks.getAIUsageOptions,
    getAIUsageRecords: mocks.getAIUsageRecords,
    getCCSwitchUsageSyncStatus: mocks.getCCSwitchUsageSyncStatus,
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

const usageResult = {
  mode: 'self' as const,
  employee,
  projects: [],
  timezone: 'Asia/Shanghai' as const,
  summary: {
    start_date: '2026-07-23',
    end_date: '2026-07-29',
    period_days: 7,
    active_days: 2,
    record_count: 3,
    total_tokens: 12600,
    prompt_tokens: 7200,
    completion_tokens: 5400,
    average_tokens_per_day: 1800,
    error_count: 1,
    total_cost: 0.18,
    daily_usage: [
      { date: '2026-07-28', record_count: 1, total_tokens: 3600, prompt_tokens: 2100, completion_tokens: 1500, error_count: 0 },
      { date: '2026-07-29', record_count: 2, total_tokens: 9000, prompt_tokens: 5100, completion_tokens: 3900, error_count: 1 },
    ],
    hourly_usage: Array.from({ length: 24 }, (_, hour) => ({
      hour,
      record_count: hour === 10 ? 3 : 0,
      total_tokens: hour === 10 ? 12600 : 0,
    })),
    source_usage: [
      { source: 'chatgpt_web', record_count: 2, total_tokens: 9600 },
      { source: 'cc_switch', record_count: 1, total_tokens: 3000 },
    ],
  },
  records: [
    {
      id: 'chat-1',
      record_type: 'chat' as const,
      project_id: 'compat-project',
      project_name: '兼容项目',
      employee_id: employee.id,
      employee_name: employee.name,
      source: 'chatgpt_web',
      title: '登录模块联调',
      started_at: '2026-07-29T02:00:00Z',
      ended_at: '2026-07-29T02:05:00Z',
      task_id: 'task-auth',
      task_title: '登录模块',
      model: 'gpt-4.1',
      status: 'ok',
      duration_ms: 300000,
      prompt_tokens: 500,
      completion_tokens: 400,
      total_tokens: 900,
      cost: 0.01,
      error_count: 0,
      trace_id: null,
      message_count: 2,
      messages: [
        { role: 'user', content: '为什么登录返回 401？', token_count: 10, created_at: '2026-07-29T02:00:00Z' },
        { role: 'assistant', content: '检查令牌是否过期。', token_count: 12, created_at: '2026-07-29T02:01:00Z' },
      ],
    },
  ],
  has_more: false,
  warnings: [],
};

describe('WorkdayPage', () => {
  beforeEach(() => {
    mocks.getAIUsageOptions.mockResolvedValue(selfOptions);
    mocks.getAIUsageRecords.mockResolvedValue(usageResult);
    mocks.getCCSwitchUsageSyncStatus.mockResolvedValue({
      status: 'never',
      employee_id: employee.id,
      employee_name: employee.name,
    });
  });

  it('shows AI work records without embedding the daily work-log panel', async () => {
    render(<WorkdayPage />);

    expect(await screen.findByText('我的 AI 工作记录')).toBeInTheDocument();
    expect(screen.queryByText('每日 AI 工作日志')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('日报日期')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '同步本机 CC Switch' })).toBeInTheDocument();
  });

  it('gives daily token columns a full-height plotting area', async () => {
    render(<WorkdayPage />);

    const chart = await screen.findByRole('img', { name: '每日 Token 趋势' });
    const firstDay = chart.querySelector('[title^="2026-07-28"]');

    expect(firstDay).toHaveClass('h-full');
  });

  it('lets administrators select an employee and view team AI work records', async () => {
    const adminEmployee = { id: 'hanshangbo', name: '韩尚博', email: 'hanshangbo@local.dev', project_ids: [] };
    const adminOptions = {
      ...selfOptions,
      mode: 'admin' as const,
      current_employee: adminEmployee,
      employees: [employee, adminEmployee],
    };
    mocks.getAIUsageOptions.mockResolvedValueOnce(adminOptions);
    mocks.getAIUsageRecords.mockResolvedValueOnce({ ...usageResult, mode: 'admin' });

    render(<WorkdayPage />);

    expect(await screen.findByText('团队 AI 工作记录')).toBeInTheDocument();
    expect(screen.getByLabelText('员工')).toHaveValue('hanshangbo');
    expect(screen.queryByText('每日 AI 工作日志')).not.toBeInTheDocument();
  });

  it('lets regular users select another employee but only shows token statistics', async () => {
    const user = userEvent.setup();
    const otherEmployee = { id: 'test2', name: 'Test 2', email: 'test2@local.dev', project_ids: [] };
    mocks.getAIUsageOptions.mockResolvedValueOnce({
      ...selfOptions,
      mode: 'statistics' as const,
      employees: [employee, otherEmployee],
    });
    mocks.getAIUsageRecords.mockResolvedValueOnce({
      ...usageResult,
      mode: 'statistics' as const,
      employee: otherEmployee,
      records: [],
      detail_visible: false,
      warnings: ['Token statistics only'],
    });

    render(<WorkdayPage />);

    expect(await screen.findByText('AI Token 使用统计')).toBeInTheDocument();
    expect(screen.getByLabelText('员工')).toHaveValue('tangweixiang');
    expect(screen.getByText('12,600')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '同步本机 CC Switch' })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('员工'), 'test2');

    expect(screen.queryByRole('button', { name: '同步本机 CC Switch' })).not.toBeInTheDocument();
  });
});
