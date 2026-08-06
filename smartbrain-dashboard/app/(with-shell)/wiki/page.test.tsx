import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ProjectWikiPage from './page';

const mocks = vi.hoisted(() => ({
  answerQuestion: vi.fn(),
  createProjectWikiMcpToken: vi.fn(),
  downloadCodexInstaller: vi.fn(),
  getProjectWikiOverview: vi.fn(),
  listProjectWikiMcpTokens: vi.fn(),
  listProjectCatalog: vi.fn(),
  revokeProjectWikiMcpToken: vi.fn(),
  reviewProjectWikiChange: vi.fn(),
}));

vi.mock('@/utils/codex-plugin-installer', () => ({
  CODEX_PLUGIN_BUNDLE_PATH: '/downloads/smartbrain-company-memory-codex.zip',
  downloadCodexInstaller: mocks.downloadCodexInstaller,
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    answerQuestion: mocks.answerQuestion,
    createProjectWikiMcpToken: mocks.createProjectWikiMcpToken,
    getProjectWikiOverview: mocks.getProjectWikiOverview,
    listProjectWikiMcpTokens: mocks.listProjectWikiMcpTokens,
    listProjectCatalog: mocks.listProjectCatalog,
    revokeProjectWikiMcpToken: mocks.revokeProjectWikiMcpToken,
    reviewProjectWikiChange: mocks.reviewProjectWikiChange,
  };
});

const overview = {
  project: { id: 'project-1', name: '智慧大脑', department_id: 'research' },
  permissions: { can_review: true, can_compile: true },
  summary: {
    page_count: 2,
    pending_review_count: 1,
    source_count: 8,
    link_count: 1,
  },
  pages: [
    {
      id: 'page-1',
      page_key: 'procedure-1',
      title: 'AI Monitor 后台同步',
      page_type: 'procedure',
      summary: '通过 wscript 隐藏启动同步脚本。',
      markdown_content: '# AI Monitor 后台同步\n\n通过 [[wscript]] 隐藏启动同步脚本。',
      usefulness: 0.95,
      confidence: 0.96,
      current_version: 2,
      uploaded_by: { user_id: 'user-1', name: '唐伟翔', email: 'tangweixiang@local.dev' },
      sources: [{ source_type: 'chat', source_id: 'session-1', locator: null }],
      links: [{ to_title: 'wscript', relation: 'related' }],
      created_at: '2026-07-29T01:00:00Z',
      updated_at: '2026-07-30T01:00:00Z',
    },
    {
      id: 'page-2',
      page_key: 'concept-2',
      title: 'wscript',
      page_type: 'concept',
      summary: 'Windows Script Host 命令行入口。',
      markdown_content: '# wscript\n\nWindows Script Host 命令行入口。',
      usefulness: 0.9,
      confidence: 0.91,
      current_version: 1,
      sources: [{ source_type: 'document', source_id: 'doc-1', locator: null }],
      links: [],
      created_at: '2026-07-29T01:00:00Z',
      updated_at: '2026-07-29T01:00:00Z',
    },
  ],
  pending_changes: [
    {
      id: 'change-1',
      title: '安装权限口径',
      page_type: 'decision',
      reason_code: 'governed_page_type',
      status: 'pending_review',
      summary: '安装不再要求默认项目成员。',
      proposed_markdown: '# 安装权限口径\n\n安装不再要求默认项目成员。',
      usefulness: 0.98,
      confidence: 0.99,
      contradiction: false,
      source_ids: ['chat:session-2'],
      link_titles: ['AI Monitor'],
      uploaded_by: { user_id: 'user-1', name: '唐伟翔', email: 'tangweixiang@local.dev' },
      created_at: '2026-07-30T01:00:00Z',
    },
  ],
  latest_run: {
    id: 'run-1',
    status: 'completed',
    trigger_type: 'scheduled',
    model: 'MiniMax-M3',
    source_count: 4,
    candidate_count: 3,
    auto_applied_count: 1,
    pending_review_count: 1,
    discarded_count: 1,
    error_message: null,
    started_at: '2026-07-30T00:00:00Z',
    completed_at: '2026-07-30T00:01:00Z',
  },
};

describe('ProjectWikiPage', () => {
  beforeEach(() => {
    window.localStorage.clear();
    mocks.answerQuestion.mockReset();
    mocks.createProjectWikiMcpToken.mockReset();
    mocks.downloadCodexInstaller.mockReset();
    mocks.getProjectWikiOverview.mockReset();
    mocks.listProjectWikiMcpTokens.mockReset();
    mocks.listProjectCatalog.mockReset();
    mocks.revokeProjectWikiMcpToken.mockReset();
    mocks.reviewProjectWikiChange.mockReset();
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑',
        environment: 'development',
        department_id: 'research',
        role: 'owner',
      },
    ]);
    mocks.getProjectWikiOverview.mockResolvedValue(overview);
    mocks.listProjectWikiMcpTokens.mockResolvedValue([]);
    mocks.createProjectWikiMcpToken.mockResolvedValue({
      id: 'token-1',
      name: 'Codex',
      token: 'sbmcp_visible_once',
      scopes: ['wiki:read'],
      created_at: '2026-08-03T04:00:00Z',
      expires_at: '2026-11-01T04:00:00Z',
    });
    mocks.revokeProjectWikiMcpToken.mockResolvedValue(undefined);
    mocks.answerQuestion.mockResolvedValue({
      query: '如何启动后台同步？',
      synthesis: '使用 wscript 隐藏启动同步脚本，并检查后台任务状态。',
      source: 'llm',
      hits: [],
    });
    mocks.reviewProjectWikiChange.mockResolvedValue({
      id: 'change-1',
      status: 'applied',
      page_id: 'page-3',
    });
  });

  it('shows useful pages sources and the knowledge network', async () => {
    render(<ProjectWikiPage />);

    expect(await screen.findByRole('heading', { name: '项目 Wiki' })).toBeInTheDocument();
    expect(
      await screen.findByRole('heading', { name: 'AI Monitor 后台同步' }),
    ).toBeInTheDocument();
    expect(screen.getAllByText('通过 wscript 隐藏启动同步脚本。')).toHaveLength(2);
    expect(screen.getByLabelText('知识关系网络')).toBeInTheDocument();
    expect(screen.getByText('chat:session-1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '立即编译' })).not.toBeInTheDocument();
  });

  it('removes project Q&A and lets an administrator approve a useful update', async () => {
    const user = userEvent.setup();
    render(<ProjectWikiPage />);

    await screen.findByRole('heading', { name: 'AI Monitor 后台同步' });
    expect(screen.queryByText('询问这个项目')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '提问' })).not.toBeInTheDocument();
    expect(mocks.answerQuestion).not.toHaveBeenCalled();
    expect(screen.getAllByText('上传人：唐伟翔').length).toBeGreaterThan(0);

    await user.click(await screen.findByRole('button', { name: '批准 安装权限口径' }));
    await waitFor(() => {
      expect(mocks.reviewProjectWikiChange).toHaveBeenCalledWith(
        'change-1',
        'approve',
        '管理员确认进入项目 Wiki',
      );
    });
  });

  it('creates a Wiki MCP token and shows the secret once', async () => {
    const user = userEvent.setup();
    render(<ProjectWikiPage />);

    await user.click(await screen.findByRole('button', { name: '创建 MCP Token' }));

    await waitFor(() => {
      expect(mocks.createProjectWikiMcpToken).toHaveBeenCalledWith('Codex', ['wiki:read'], 90);
    });
    expect(screen.getByDisplayValue('sbmcp_visible_once')).toBeInTheDocument();
  });

  it('downloads a complete Codex plugin installer after creating a token', async () => {
    const user = userEvent.setup();
    render(<ProjectWikiPage />);

    const installButton = await screen.findByRole('button', { name: '安装到 Codex CLI' });
    expect(installButton).toBeDisabled();

    await user.click(screen.getByRole('button', { name: '创建 MCP Token' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '安装到 Codex CLI' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: '安装到 Codex CLI' }));

    expect(mocks.downloadCodexInstaller).toHaveBeenCalledWith({
      endpoint: 'http://localhost:8010/mcp',
      token: 'sbmcp_visible_once',
      bundleUrl: 'http://localhost:3000/downloads/smartbrain-company-memory-codex.zip',
    });
    expect(await screen.findByText('Codex 安装器已下载，请运行下载的 CMD 文件')).toBeInTheDocument();
  });

  it('explains the ChatGPT public HTTPS and OAuth requirements', async () => {
    const user = userEvent.setup();
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<ProjectWikiPage />);

    await user.click(await screen.findByRole('button', { name: '打开 ChatGPT 接入设置' }));
    expect(open).toHaveBeenCalledWith(
      'https://chatgpt.com/#settings/Connectors',
      '_blank',
      'noopener,noreferrer',
    );
    expect(screen.getByText(/当前局域网 HTTP 地址不能被 ChatGPT 云端访问/)).toBeInTheDocument();
    expect(screen.getByText(/公网 HTTPS 和 OAuth/)).toBeInTheDocument();
    open.mockRestore();
  });

  it('automatically shows the Wiki MCP setup guide with the complete Codex desktop flow', async () => {
    render(<ProjectWikiPage />);

    const dialog = await screen.findByRole('dialog', { name: '智慧大脑 MCP 使用指引' });
    expect(dialog).toHaveTextContent('先确认本机已安装 Codex CLI');
    expect(dialog).toHaveTextContent('是否允许提交待审批记忆');
    expect(dialog).toHaveTextContent('创建 Token');
    expect(dialog).toHaveTextContent('安装到 Codex CLI');
    expect(dialog).toHaveTextContent('重新启动 ChatGPT 桌面端');
    expect(dialog).toHaveTextContent('Codex 模式');
  });

  it('lets the user close the guide for this visit without suppressing future visits', async () => {
    const user = userEvent.setup();
    const first = render(<ProjectWikiPage />);

    await user.click(await screen.findByRole('button', { name: '关闭智慧大脑 MCP 使用指引' }));
    expect(screen.queryByRole('dialog', { name: '智慧大脑 MCP 使用指引' })).not.toBeInTheDocument();
    expect(window.localStorage.getItem('smartbrain:wiki-mcp-guide:dismissed')).toBeNull();

    first.unmount();
    render(<ProjectWikiPage />);
    expect(await screen.findByRole('dialog', { name: '智慧大脑 MCP 使用指引' })).toBeInTheDocument();
  });

  it('persists the do-not-show-again preference for the Wiki MCP guide', async () => {
    const user = userEvent.setup();
    const first = render(<ProjectWikiPage />);

    await user.click(await screen.findByRole('checkbox', { name: '下次不再提示' }));
    await user.click(screen.getByRole('button', { name: '我知道了' }));

    expect(window.localStorage.getItem('smartbrain:wiki-mcp-guide:dismissed')).toBe('1');
    first.unmount();
    render(<ProjectWikiPage />);
    await screen.findByRole('heading', { name: '项目 Wiki' });
    expect(screen.queryByRole('dialog', { name: '智慧大脑 MCP 使用指引' })).not.toBeInTheDocument();
  });
});
