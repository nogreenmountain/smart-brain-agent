import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MemberWikiPage from './page';

const mocks = vi.hoisted(() => ({
  getOptions: vi.fn(),
  getOverview: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  getMemberWikiOptions: mocks.getOptions,
  getMemberWikiOverview: mocks.getOverview,
}));

describe('MemberWikiPage', () => {
  beforeEach(() => {
    mocks.getOptions.mockResolvedValue({
      mode: 'admin',
      current_member: { user_id: 'admin', employee_id: 'hanshangbo', name: '韩尚博', email: 'hanshangbo@local.dev' },
      members: [
        { user_id: 'u1', employee_id: 'test1', name: '张三', email: 'test1@local.dev' },
        { user_id: 'admin', employee_id: 'hanshangbo', name: '韩尚博', email: 'hanshangbo@local.dev' },
      ],
    });
    mocks.getOverview.mockResolvedValue({
      mode: 'admin',
      member: { user_id: 'admin', employee_id: 'hanshangbo', name: '韩尚博', email: 'hanshangbo@local.dev' },
      timezone: 'Asia/Shanghai',
      summary: { experience_count: 1, success_count: 1, failure_count: 0, latest_observed: '2026-08-04' },
      experiences: [{
        id: '00000000-0000-0000-0000-000000000001', employee_id: 'test1', employee_name: '张三',
        experience_key: 'deploy-dashboard', title: '部署 Dashboard', task_type: 'deployment', outcome: 'success',
        summary: '重建镜像并完成健康检查。', markdown_content: '# 部署 Dashboard\n\n## 实际步骤\n1. 重建镜像',
        tags: ['deployment'], tools: ['Docker'], confidence: 0.93, first_observed: '2026-08-03',
        last_observed: '2026-08-04', observation_count: 2, current_version: 2,
        updated_at: '2026-08-04T13:00:00+00:00', lexical_score: 0.8, vector_score: null,
      }],
      latest_run: { id: 'run-1', status: 'completed', cutoff_at: '2026-08-04T13:00:00+00:00', updated_member_count: 1, session_count: 2, experience_count: 1, completed_at: '2026-08-04T13:02:00+00:00' },
    });
  });

  it('shows the daily update policy, admin member selector and reusable Markdown experience', async () => {
    render(<MemberWikiPage />);

    expect(screen.getByRole('heading', { name: '成员 Wiki' })).toBeInTheDocument();
    expect(screen.getByText(/每天 21:00/)).toBeInTheDocument();
    await waitFor(() => expect(mocks.getOverview).toHaveBeenCalledWith(expect.objectContaining({ employeeId: 'hanshangbo' })));
    expect(screen.getByLabelText('选择成员')).toBeInTheDocument();
    expect(await screen.findByText('部署 Dashboard')).toBeInTheDocument();
    expect(screen.getByText(/重建镜像并完成健康检查/)).toBeInTheDocument();
  });
});
