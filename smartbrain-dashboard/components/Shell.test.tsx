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

  it('consolidates AI and material navigation into one workspace each', async () => {
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

    const link = screen.getByRole('button', { name: 'AI 工作台' });
    expect(link).toHaveClass('bg-brand-500/10');
    expect(link.querySelector('svg')).not.toBeNull();
    expect(screen.queryByRole('button', { name: 'AI 工作日志' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'AI 排行榜' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'AI Monitor' })).not.toBeInTheDocument();
    const smartWikiLink = screen.getByRole('button', { name: '智慧 Wiki' });
    expect(screen.queryByRole('button', { name: '项目 Wiki' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '成员 Wiki' })).not.toBeInTheDocument();
    const uploadsLink = screen.getByRole('button', { name: '上传资料' });
    expect(screen.getByRole('button', { name: '成员信息' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '项目管理' })).not.toBeInTheDocument();

    await user.click(link);
    expect(mocks.push).toHaveBeenCalledWith('/workday');

    await user.click(smartWikiLink);
    expect(mocks.push).toHaveBeenCalledWith('/wiki');

    await user.click(uploadsLink);
    expect(mocks.push).toHaveBeenCalledWith('/uploads');
  });

  it('opens the member-management navigation for project members', async () => {
    const user = userEvent.setup();
    render(
      <Shell
        me={{
          user_id: 'admin-1',
          email: 'hanshangbo@local.dev',
          full_name: null,
          can_manage_projects: true,
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
    expect(screen.queryByRole('button', { name: '团队管理' })).not.toBeInTheDocument();
  });

  it('shows team management only to SmartBrain system administrators', async () => {
    const user = userEvent.setup();
    render(
      <Shell
        me={{
          user_id: 'system-admin-1',
          email: 'hanshangbo@local.dev',
          full_name: null,
          is_system_admin: true,
          can_manage_projects: true,
          memberships: [],
        }}
      >
        <div>content</div>
      </Shell>,
    );

    const link = screen.getByRole('button', { name: '团队管理' });
    await user.click(link);
    expect(mocks.push).toHaveBeenCalledWith('/team');
  });

  it('opens the personal center and shows the configured nickname', async () => {
    const user = userEvent.setup();
    render(
      <Shell
        me={{
          user_id: 'user-1',
          email: 'test1@local.dev',
          full_name: 'test1',
          nickname: '研发小王',
          display_name: '研发小王',
          memberships: [],
        }}
      >
        <div>content</div>
      </Shell>,
    );

    expect(screen.getByText('研发小王')).toBeInTheDocument();
    const profileLink = screen.getByRole('button', { name: '个人中心' });
    await user.click(profileLink);
    expect(mocks.push).toHaveBeenCalledWith('/profile');
  });
});
