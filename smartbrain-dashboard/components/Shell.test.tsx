import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Shell } from './Shell';

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/workday',
  useRouter: () => ({
    push: mocks.push,
    refresh: mocks.refresh,
  }),
}));

vi.mock('@/lib/api', () => ({
  logout: vi.fn(),
}));

describe('Shell AI record navigation', () => {
  beforeEach(() => {
    mocks.push.mockReset();
    mocks.refresh.mockReset();
  });

  it('renames the workday entry and adds a separate work-log page', async () => {
    const user = userEvent.setup();
    render(
      <Shell
        me={{
          user_id: 'user-1',
          email: 'member@example.com',
          full_name: null,
          memberships: [],
        }}
      >
        <div>content</div>
      </Shell>,
    );

    const link = screen.getByRole('button', { name: 'AI 工作记录' });
    expect(link).toHaveClass('bg-brand-500/10');
    expect(link.querySelector('svg')).not.toBeNull();
    const worklogLink = screen.getByRole('button', { name: 'AI 工作日志' });
    expect(screen.getByRole('button', { name: '成员管理' })).toBeInTheDocument();

    await user.click(link);
    expect(mocks.push).toHaveBeenCalledWith('/workday');

    await user.click(worklogLink);
    expect(mocks.push).toHaveBeenCalledWith('/worklogs');
  });

  it('opens the member-management navigation for project members', async () => {
    const user = userEvent.setup();
    render(
      <Shell
        me={{
          user_id: 'admin-1',
          email: 'hanshangbo@local.dev',
          full_name: null,
          memberships: [{ org_id: 'org-1', org_name: '研发部', role: 'owner' }],
        }}
      >
        <div>content</div>
      </Shell>,
    );

    expect(screen.getByRole('button', { name: '项目管理' })).toBeInTheDocument();
    const link = screen.getByRole('button', { name: '成员管理' });
    await user.click(link);
    expect(mocks.push).toHaveBeenCalledWith('/members');
  });
});
