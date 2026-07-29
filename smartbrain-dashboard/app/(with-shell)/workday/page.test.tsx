import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import WorkdayPage from './page';

const mocks = vi.hoisted(() => ({
  createAIUsageReport: vi.fn(),
  getAIUsageOptions: vi.fn(),
  getAIUsageRecords: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    createAIUsageReport: mocks.createAIUsageReport,
    getAIUsageOptions: mocks.getAIUsageOptions,
    getAIUsageRecords: mocks.getAIUsageRecords,
  };
});

const selfOptions = {
  mode: 'self' as const,
  current_employee: {
    id: 'tangweixiang',
    name: '唐伟翔',
    email: 'tangweixiang@local.dev',
    project_ids: ['project-1'],
  },
  departments: [
    { id: 'research', name: '研发' },
    { id: 'marketing', name: '市场' },
    { id: 'business', name: '业务' },
  ],
  projects: [
    { id: 'project-1', name: '智慧大脑agent', department_id: 'research' },
  ],
  employees: [],
};

const usageResult = {
  mode: 'self' as const,
  employee: selfOptions.current_employee,
  projects: selfOptions.projects,
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
      project_id: 'project-1',
      project_name: '智慧大脑agent',
      employee_id: 'tangweixiang',
      employee_name: '唐伟翔',
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
    mocks.createAIUsageReport.mockResolvedValue({
      employee: selfOptions.current_employee,
      project: selfOptions.projects[0],
      summary: usageResult.summary,
      high_frequency_periods: ['10:00-11:00'],
      report: '## 完成了什么\n完成登录模块联调。\n\n## 实现了什么\n定位令牌问题。\n\n## 遇到了什么问题\n登录返回 401。\n\n## 解决了什么问题\n确认令牌过期。',
      model: 'MiniMax-M3',
      generated_at: '2026-07-29T04:00:00Z',
    });
  });

  it('shows ordinary users only their own usage and never exposes report controls', async () => {
    const user = userEvent.setup();
    render(<WorkdayPage />);

    expect(await screen.findByText('我的 AI 使用')).toBeInTheDocument();
    expect(await screen.findByText('12,600')).toBeInTheDocument();
    expect(screen.getByText('1,800')).toBeInTheDocument();
    expect(screen.getByText('登录模块联调')).toBeInTheDocument();
    expect(screen.queryByLabelText('部门')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('项目')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('员工')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '生成区间工作报告' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '登录模块联调' }));
    expect(screen.getByText('为什么登录返回 401？')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('开始日期'), { target: { value: '2026-07-20' } });
    await user.click(screen.getByRole('button', { name: '查询记录' }));
    await waitFor(() => expect(mocks.getAIUsageRecords).toHaveBeenLastCalledWith(
      expect.objectContaining({ startDate: '2026-07-20', employeeId: undefined, projectId: undefined }),
    ));
  });

  it('gives administrators cascading filters and generates a scoped report', async () => {
    const user = userEvent.setup();
    const adminOptions = {
      ...selfOptions,
      mode: 'admin' as const,
      current_employee: { ...selfOptions.current_employee, id: 'hanshangbo', name: '韩尚博', email: 'hanshangbo@local.dev' },
      employees: [
        { ...selfOptions.current_employee, project_ids: ['project-1'] },
      ],
    };
    mocks.getAIUsageOptions.mockResolvedValueOnce(adminOptions);
    mocks.getAIUsageRecords.mockResolvedValueOnce({ ...usageResult, mode: 'admin' });

    render(<WorkdayPage />);

    expect(await screen.findByText('团队 AI 使用')).toBeInTheDocument();
    expect(screen.getByLabelText('部门')).toHaveValue('research');
    expect(screen.getByLabelText('项目')).toHaveValue('project-1');
    expect(screen.getByLabelText('员工')).toHaveValue('tangweixiang');
    await screen.findByText('登录模块联调');

    await user.click(screen.getByRole('button', { name: '生成区间工作报告' }));
    await waitFor(() => expect(mocks.createAIUsageReport).toHaveBeenCalledWith({
      departmentId: 'research',
      projectId: 'project-1',
      employeeId: 'tangweixiang',
      startDate: expect.any(String),
      endDate: expect.any(String),
      source: undefined,
    }));
    expect(await screen.findByText('AI 使用工作报告')).toBeInTheDocument();
    expect(screen.getByText('完成登录模块联调。')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('开始日期'), {
      target: { value: '2026-07-20' },
    });
    expect(screen.queryByRole('button', { name: '生成区间工作报告' })).not.toBeInTheDocument();
    expect(screen.queryByText('AI 使用工作报告')).not.toBeInTheDocument();
  });
});
