import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ProfilePage from './page';

const mocks = vi.hoisted(() => ({
  changeMyPassword: vi.fn(),
  getMe: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  listProjects: vi.fn(),
  updateMyProfile: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    changeMyPassword: mocks.changeMyPassword,
    getMe: mocks.getMe,
    listProjectMemoryDepartments: mocks.listProjectMemoryDepartments,
    listProjects: mocks.listProjects,
    updateMyProfile: mocks.updateMyProfile,
  };
});

describe('ProfilePage', () => {
  beforeEach(() => {
    mocks.changeMyPassword.mockReset();
    mocks.getMe.mockReset();
    mocks.listProjectMemoryDepartments.mockReset();
    mocks.listProjects.mockReset();
    mocks.updateMyProfile.mockReset();
    mocks.getMe.mockResolvedValue({
      user_id: 'user-1',
      email: 'test1@local.dev',
      full_name: 'test1',
      nickname: null,
      display_name: 'test1@local.dev',
      ai_detail_visible_to_admin: false,
      can_manage_projects: true,
      memberships: [],
    });
    mocks.updateMyProfile.mockResolvedValue({
      user_id: 'user-1',
      email: 'test1@local.dev',
      full_name: 'test1',
      nickname: '研发小王',
      display_name: '研发小王',
      ai_detail_visible_to_admin: true,
      memberships: [],
    });
    mocks.changeMyPassword.mockResolvedValue({ status: 'updated' });
    mocks.listProjectMemoryDepartments.mockResolvedValue([]);
    mocks.listProjects.mockResolvedValue([]);
  });

  it('shows the email as the default member display name and saves a nickname', async () => {
    const user = userEvent.setup();
    render(<ProfilePage />);

    expect(await screen.findByRole('heading', { name: '个人中心' })).toBeInTheDocument();
    expect(screen.getByText('未设置昵称时，成员信息显示 test1@local.dev')).toBeInTheDocument();

    await user.type(screen.getByLabelText('昵称'), '研发小王');
    await user.click(screen.getByRole('checkbox', { name: '允许管理员查看详细 AI 工作记录' }));
    await user.click(screen.getByRole('button', { name: '保存个人设置' }));

    await waitFor(() => expect(mocks.updateMyProfile).toHaveBeenCalledWith('研发小王', true));
    expect(await screen.findByText('个人设置已保存')).toBeInTheDocument();
  });

  it('validates confirmation and changes the current user password', async () => {
    const user = userEvent.setup();
    render(<ProfilePage />);
    await screen.findByRole('heading', { name: '个人中心' });

    await user.type(screen.getByLabelText('当前密码'), '123456');
    await user.type(screen.getByLabelText('新密码'), '654321');
    await user.type(screen.getByLabelText('确认新密码'), '654322');
    await user.click(screen.getByRole('button', { name: '修改密码' }));

    expect(await screen.findByText('两次输入的新密码不一致')).toBeInTheDocument();
    expect(mocks.changeMyPassword).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText('确认新密码'));
    await user.type(screen.getByLabelText('确认新密码'), '654321');
    await user.click(screen.getByRole('button', { name: '修改密码' }));

    await waitFor(() => expect(mocks.changeMyPassword).toHaveBeenCalledWith('123456', '654321'));
    expect(await screen.findByText('密码已修改')).toBeInTheDocument();
  });

  it('shows directly joined projects and a read-only three-item PROJECT PROFILE for ordinary members', async () => {
    const user = userEvent.setup();
    mocks.getMe.mockResolvedValue({
      user_id: 'user-1', email: 'test1@local.dev', full_name: 'test1', nickname: null,
      display_name: 'test1@local.dev', ai_detail_visible_to_admin: false,
      can_manage_projects: false, memberships: [],
    });
    mocks.listProjectMemoryDepartments.mockResolvedValue([
      { id: 'research', name: '研发支撑', sort_order: 1, parent_id: null, allows_projects: false, level: 1 },
      { id: 'research-direct', name: '直属项目', sort_order: 0, parent_id: 'research', parent_name: '研发支撑', allows_projects: true, level: 2 },
    ]);
    mocks.listProjects.mockResolvedValue([
      { id: 'p1', org_id: 'o1', name: '项目一', environment: 'development', department_id: 'research-direct', role: 'owner', created_at: '2026-01-01T00:00:00Z', completed_at: null },
      { id: 'p2', org_id: 'o1', name: '项目二', environment: 'development', department_id: 'research-direct', role: 'admin', created_at: '2026-02-01T00:00:00Z', completed_at: '2026-08-01T00:00:00Z' },
      { id: 'p3', org_id: 'o1', name: '项目三', environment: 'development', department_id: 'research-direct', role: 'developer', created_at: '2026-03-01T00:00:00Z', completed_at: null },
      { id: 'p4', org_id: 'o1', name: '项目四', environment: 'development', department_id: 'research-direct', role: 'developer', created_at: '2026-04-01T00:00:00Z', completed_at: null },
    ]);

    render(<ProfilePage />);

    expect(await screen.findByRole('heading', { name: '我的参与项目' })).toBeInTheDocument();
    expect(mocks.listProjects).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /项目一/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /项目二/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /项目三/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /项目四/ })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'PROJECT PROFILE' })).toBeInTheDocument();
    expect(screen.getAllByText('研发支撑 / 直属项目').length).toBeGreaterThan(0);
    expect(screen.getAllByText('总负责人').length).toBeGreaterThan(0);
    expect(screen.getAllByText('进行中').length).toBeGreaterThan(0);
    expect(screen.queryByText('申请新增项目')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /编辑|上传|移交|删除/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /项目二/ }));
    expect(screen.getAllByText('项目负责人').length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: /项目三/ }));
    expect(screen.getAllByText('项目成员').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: '下一组项目' }));
    expect(await screen.findByRole('button', { name: /项目四/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /项目四/ }));
    expect(screen.getByRole('heading', { name: '项目四' })).toBeInTheDocument();
  });
});
