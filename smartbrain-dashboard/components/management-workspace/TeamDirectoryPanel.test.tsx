import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TeamDirectoryPanel } from './TeamDirectoryPanel';

const mocks = vi.hoisted(() => ({
  createTeamMember: vi.fn(),
  listTeamMembers: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    createTeamMember: mocks.createTeamMember,
    listTeamMembers: mocks.listTeamMembers,
  };
});

describe('TeamDirectoryPanel', () => {
  beforeEach(() => {
    mocks.createTeamMember.mockReset();
    mocks.listTeamMembers.mockReset();
    mocks.listTeamMembers.mockResolvedValue([]);
  });

  it('rejects invalid login usernames before submitting the create request', async () => {
    const user = userEvent.setup();
    render(
      <TeamDirectoryPanel
        currentUser={{
          user_id: 'admin-1',
          email: 'admin@local.dev',
          full_name: 'Admin',
          is_system_admin: true,
          memberships: [],
        }}
      />,
    );

    await user.type(screen.getByLabelText('登录账号'), '张三');
    await user.type(screen.getByLabelText('初始密码'), 'secret123');

    expect(screen.getByText('登录账号需为 2–63 位小写英文、数字、点、下划线或连字符，并以英文或数字开头。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '创建团队成员' })).toBeDisabled();
    expect(mocks.createTeamMember).not.toHaveBeenCalled();
  });

  it('directs project membership work to project management', async () => {
    render(
      <TeamDirectoryPanel
        currentUser={{
          user_id: 'admin-1',
          email: 'admin@local.dev',
          full_name: 'Admin',
          is_system_admin: true,
          memberships: [],
        }}
      />,
    );

    expect(await screen.findByText('账号级操作统一在此完成；项目归属请前往项目管理。')).toBeInTheDocument();
    expect(screen.queryByText('账号级操作统一在此完成；项目归属请前往成员管理。')).not.toBeInTheDocument();
  });
});
