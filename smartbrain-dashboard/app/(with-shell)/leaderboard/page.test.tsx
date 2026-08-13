import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import LeaderboardPage from './legacy-page';

const mocks = vi.hoisted(() => ({
  getAIUsageLeaderboard: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    getAIUsageLeaderboard: mocks.getAIUsageLeaderboard,
  };
});

const result = {
  start_date: '2026-07-12',
  end_date: '2026-08-10',
  period_days: 30,
  timezone: 'Asia/Shanghai' as const,
  total_tokens: 1_900_000_000,
  request_count: 12_500,
  active_users: 3,
  active_days: 30,
  average_tokens_per_user: 633_333_333.33,
  official_cc_switch_users: 2,
  privacy_notice: '仅展示聚合统计，不包含对话、Prompt、回复或个人工作日志。',
  members: [
    {
      rank: 1,
      employee_id: 'alice',
      employee_name: '爱丽丝',
      account: 'alice',
      total_tokens: 1_000_000_000,
      request_count: 6000,
      active_days: 28,
      average_tokens_per_day: 35_714_285.71,
      average_tokens_per_request: 166_666.67,
      share_percent: 52.63,
      input_tokens: 200_000_000,
      output_tokens: 150_000_000,
      cache_read_tokens: 600_000_000,
      cache_creation_tokens: 50_000_000,
      error_count: 2,
      total_cost: 100,
      official_cc_switch: true,
    },
    {
      rank: 2,
      employee_id: 'bob',
      employee_name: 'Bob',
      account: 'bob',
      total_tokens: 600_000_000,
      request_count: 4000,
      active_days: 25,
      average_tokens_per_day: 24_000_000,
      average_tokens_per_request: 150_000,
      share_percent: 31.58,
      input_tokens: 280_000_000,
      output_tokens: 220_000_000,
      cache_read_tokens: 100_000_000,
      cache_creation_tokens: 0,
      error_count: 1,
      total_cost: 80,
      official_cc_switch: false,
    },
    {
      rank: 3,
      employee_id: 'carol',
      employee_name: 'Carol',
      account: 'carol',
      total_tokens: 300_000_000,
      request_count: 2500,
      active_days: 20,
      average_tokens_per_day: 15_000_000,
      average_tokens_per_request: 120_000,
      share_percent: 15.79,
      input_tokens: 150_000_000,
      output_tokens: 150_000_000,
      cache_read_tokens: 0,
      cache_creation_tokens: 0,
      error_count: 0,
      total_cost: 30,
      official_cc_switch: true,
    },
  ],
  daily_usage: [
    { date: '2026-08-09', total_tokens: 800_000_000, request_count: 5000, active_users: 3 },
    { date: '2026-08-10', total_tokens: 1_100_000_000, request_count: 7500, active_users: 3 },
  ],
  source_usage: [
    { key: 'cc_switch', label: 'CC Switch', total_tokens: 1_800_000_000, request_count: 12_000, percentage: 94.74 },
    { key: 'chatgpt_web', label: 'ChatGPT Web', total_tokens: 100_000_000, request_count: 500, percentage: 5.26 },
  ],
  app_usage: [
    { key: 'codex', label: 'Codex', total_tokens: 1_100_000_000, request_count: 7000, percentage: 57.89 },
    { key: 'claude', label: 'Claude', total_tokens: 800_000_000, request_count: 5500, percentage: 42.11 },
  ],
  token_usage: [
    { key: 'cache_read', label: '缓存读取', total_tokens: 700_000_000, request_count: 0, percentage: 36.84 },
    { key: 'input', label: '新鲜输入', total_tokens: 630_000_000, request_count: 0, percentage: 33.16 },
    { key: 'output', label: '模型输出', total_tokens: 520_000_000, request_count: 0, percentage: 27.37 },
    { key: 'cache_creation', label: '缓存写入', total_tokens: 50_000_000, request_count: 0, percentage: 2.63 },
  ],
  model_usage: [
    { key: 'gpt-5', label: 'gpt-5', total_tokens: 1_100_000_000, request_count: 7000, percentage: 57.89 },
    { key: 'claude-sonnet', label: 'claude-sonnet', total_tokens: 800_000_000, request_count: 5500, percentage: 42.11 },
  ],
};

describe('LeaderboardPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date('2026-08-10T12:00:00+08:00'));
    mocks.getAIUsageLeaderboard.mockReset();
    mocks.getAIUsageLeaderboard.mockResolvedValue(result);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows an all-user token leaderboard with multiple visual statistics', async () => {
    render(<LeaderboardPage />);

    expect(await screen.findByRole('heading', { name: 'AI Token 排行榜' })).toBeInTheDocument();
    expect(screen.getAllByText('爱丽丝').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Bob').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Carol').length).toBeGreaterThan(0);
    expect(screen.getByRole('img', { name: '团队 Token 趋势' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'AI 来源构成' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '应用类型构成' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Token 构成' })).toBeInTheDocument();
    expect(
      screen.getByText((content) => content.includes(result.privacy_notice)),
    ).toBeInTheDocument();
    expect(mocks.getAIUsageLeaderboard).toHaveBeenCalledWith({
      startDate: '2026-07-12',
      endDate: '2026-08-10',
    });
  });

  it('reloads the leaderboard with a quick date range', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<LeaderboardPage />);
    await screen.findAllByText('爱丽丝');

    await user.click(screen.getByRole('button', { name: '最近 7 天' }));

    await waitFor(() => {
      expect(mocks.getAIUsageLeaderboard).toHaveBeenLastCalledWith({
        startDate: '2026-08-04',
        endDate: '2026-08-10',
      });
    });
  });
});
