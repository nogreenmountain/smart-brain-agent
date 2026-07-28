import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import WorkdayPage from './page';

const mocks = vi.hoisted(() => ({
  getWorkdaySummary: vi.fn(),
  listProjects: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    getWorkdaySummary: mocks.getWorkdaySummary,
    listProjects: mocks.listProjects,
  };
});

const summary = {
  status: 'ok' as const,
  project_id: 'project-1',
  employee: { id: 'employee-001', name: 'Alice' },
  date: '2026-07-20',
  timezone: 'Asia/Shanghai' as const,
  overview: {
    active_start: '2026-07-20T01:00:00Z',
    active_end: '2026-07-20T01:10:00Z',
    active_time_range_seconds: 600,
    trace_count: 2,
    span_count: 6,
    task_count: 1,
    llm_call_count: 2,
    tool_call_count: 3,
    error_count: 1,
    total_tokens: 1800,
    total_cost: 0.42,
    avg_llm_latency_ms: 1200,
    p95_llm_latency_ms: 1800,
  },
  narrative_summary: 'Alice 完成了日报生成任务。',
  tasks: [
    {
      task_id: 'task-1',
      title: '生成日报',
      duration_seconds: 590,
      trace_count: 2,
      span_count: 6,
      llm_call_count: 2,
      tool_call_count: 3,
      error_count: 1,
      total_tokens: 1800,
      total_cost: 0.42,
      avg_llm_latency_ms: 1200,
    },
  ],
  findings: [
    {
      finding_type: 'error' as const,
      severity: 'high' as const,
      title: '工具重复失败：shell',
      description: '同一工具失败达到阈值。',
      evidence: { failure_count: 2 },
      trace_ids: ['trace-1'],
      task_id: 'task-1',
      threshold: 2,
      actual_value: 2,
    },
  ],
  important_traces: [
    {
      trace_id: 'trace-1',
      task_id: 'task-1',
      start_time: '2026-07-20T01:00:00Z',
      end_time: '2026-07-20T01:10:00Z',
      duration_seconds: 600,
      span_count: 4,
      llm_call_count: 1,
      tool_call_count: 2,
      error_count: 1,
      total_tokens: 900,
      total_cost: 0.3,
      reasons: ['error_finding', 'high_tool_usage'],
      replay_url: '/traces?trace_id=trace-1',
    },
  ],
  distillation_candidates: [
    {
      candidate_id: 'candidate-1',
      status: 'pending' as const,
      title: '待复核：工具重复失败',
      reason: '可沉淀工具失败排查经验。',
      task_id: 'task-1',
      trace_ids: ['trace-1'],
      signals: ['error', 'high'],
    },
  ],
  raw_metrics: {
    prompt_tokens: 1000,
    completion_tokens: 700,
    reasoning_tokens: 100,
    cache_read_input_tokens: 50,
    total_tokens: 1800,
    model_usage: [
      { name: 'MiniMax-M3', call_count: 2, total_tokens: 1800, total_cost: 0.42 },
    ],
    tool_usage: [{ name: 'shell', call_count: 2, error_count: 1 }],
  },
  warnings: ['1 个 Span 未标记任务，已归入 unassigned'],
};

describe('WorkdayPage', () => {
  beforeEach(() => {
    mocks.listProjects.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: 'Default Project',
        environment: 'development',
      },
    ]);
    mocks.getWorkdaySummary.mockResolvedValue(summary);
  });

  it('generates and renders the complete structured workday report', async () => {
    const user = userEvent.setup();
    render(<WorkdayPage />);

    await screen.findByRole('option', { name: 'Default Project (development)' });
    await user.type(screen.getByLabelText('员工 ID'), 'employee-001');
    fireEvent.change(screen.getByLabelText('工作日期'), {
      target: { value: '2026-07-20' },
    });
    await user.click(screen.getByRole('button', { name: '生成日报' }));

    await waitFor(() => {
      expect(mocks.getWorkdaySummary).toHaveBeenCalledWith('project-1', {
        employeeId: 'employee-001',
        date: '2026-07-20',
        includeTraces: true,
        includeReplayRefs: true,
        includeRawMetrics: true,
      });
    });

    expect(await screen.findByText('Alice 的 AI 工作日')).toBeInTheDocument();
    expect(screen.getByText('Alice 完成了日报生成任务。')).toBeInTheDocument();
    expect(screen.getAllByText('生成日报')).toHaveLength(2);
    expect(screen.getByText('工具重复失败：shell')).toBeInTheDocument();
    expect(screen.getByText('trace-1')).toBeInTheDocument();
    expect(screen.getByText('待复核：工具重复失败')).toBeInTheDocument();
    expect(screen.getByText('MiniMax-M3')).toBeInTheDocument();
    expect(screen.getByText('1 个 Span 未标记任务，已归入 unassigned')).toBeInTheDocument();

    const replay = screen.getByRole('link', { name: '打开 Trace' });
    expect(replay).toHaveAttribute(
      'href',
      'http://localhost:3001/traces?trace_id=trace-1',
    );
  });

  it('passes disabled include flags and keeps the core overview visible', async () => {
    const user = userEvent.setup();
    render(<WorkdayPage />);

    await screen.findByRole('option', { name: 'Default Project (development)' });
    await user.type(screen.getByLabelText('员工 ID'), 'employee-001');
    fireEvent.change(screen.getByLabelText('工作日期'), {
      target: { value: '2026-07-20' },
    });
    await user.click(screen.getByLabelText('关键 Trace'));
    await user.click(screen.getByLabelText('详细指标'));
    await user.click(screen.getByRole('button', { name: '生成日报' }));

    await waitFor(() => {
      expect(mocks.getWorkdaySummary).toHaveBeenCalledWith(
        'project-1',
        expect.objectContaining({
          includeTraces: false,
          includeReplayRefs: false,
          includeRawMetrics: false,
        }),
      );
    });
    expect(await screen.findByText('Alice 的 AI 工作日')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '关键 Trace' })).not.toBeInTheDocument();
    expect(screen.queryByText('MiniMax-M3')).not.toBeInTheDocument();
  });

  it('renders no-data and request-error states', async () => {
    const user = userEvent.setup();
    mocks.getWorkdaySummary.mockResolvedValueOnce({
      ...summary,
      status: 'no_data',
      narrative_summary: '',
      tasks: [],
      findings: [],
      important_traces: [],
      distillation_candidates: [],
      raw_metrics: null,
      warnings: [],
    });
    const { unmount } = render(<WorkdayPage />);

    await screen.findByRole('option', { name: 'Default Project (development)' });
    await user.type(screen.getByLabelText('员工 ID'), 'employee-001');
    fireEvent.change(screen.getByLabelText('工作日期'), {
      target: { value: '2026-07-20' },
    });
    await user.click(screen.getByRole('button', { name: '生成日报' }));
    expect(await screen.findByText('当天没有匹配的工作数据')).toBeInTheDocument();

    unmount();
    mocks.getWorkdaySummary.mockRejectedValueOnce(new Error('日报服务暂不可用'));
    render(<WorkdayPage />);
    await screen.findByRole('option', { name: 'Default Project (development)' });
    await user.type(screen.getByLabelText('员工 ID'), 'employee-001');
    fireEvent.change(screen.getByLabelText('工作日期'), {
      target: { value: '2026-07-20' },
    });
    await user.click(screen.getByRole('button', { name: '生成日报' }));
    expect(await screen.findByText('日报服务暂不可用')).toBeInTheDocument();
  });
});
