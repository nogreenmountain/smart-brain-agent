import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import KnowledgePage from './page';

const mocks = vi.hoisted(() => ({
  deleteKnowledgeAsset: vi.fn(),
  moveKnowledgeAsset: vi.fn(),
  previewKnowledgeAsset: vi.fn(),
  renameKnowledgeAsset: vi.fn(),
  listKnowledgeLedger: vi.fn(),
  listProjectMemoryDepartments: vi.fn(),
  listProjectCatalog: vi.fn(),
  push: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mocks.push,
  }),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    deleteKnowledgeAsset: mocks.deleteKnowledgeAsset,
    moveKnowledgeAsset: mocks.moveKnowledgeAsset,
    previewKnowledgeAsset: mocks.previewKnowledgeAsset,
    renameKnowledgeAsset: mocks.renameKnowledgeAsset,
    listKnowledgeLedger: mocks.listKnowledgeLedger,
    listProjectMemoryDepartments: mocks.listProjectMemoryDepartments,
    listProjectCatalog: mocks.listProjectCatalog,
  };
});

describe('KnowledgePage', () => {
  beforeEach(() => {
    mocks.deleteKnowledgeAsset.mockReset();
    mocks.moveKnowledgeAsset.mockReset();
    mocks.previewKnowledgeAsset.mockReset();
    mocks.renameKnowledgeAsset.mockReset();
    mocks.listKnowledgeLedger.mockReset();
    mocks.listProjectMemoryDepartments.mockReset();
    mocks.listProjectCatalog.mockReset();
    mocks.push.mockReset();
    mocks.deleteKnowledgeAsset.mockResolvedValue(undefined);
    mocks.moveKnowledgeAsset.mockResolvedValue(undefined);
    mocks.renameKnowledgeAsset.mockResolvedValue(undefined);
    mocks.previewKnowledgeAsset.mockResolvedValue({
      asset_id: 'doc-2', asset_type: 'project_material', project_id: 'project-1',
      name: 'README.md', format: 'md', content: '# README',
    });
    mocks.listProjectMemoryDepartments.mockResolvedValue([
      { id: 'research', name: '研发', sort_order: 1 },
      { id: 'marketing', name: '市场', sort_order: 2 },
      { id: 'business', name: '业务', sort_order: 3 },
    ]);
    mocks.listProjectCatalog.mockResolvedValue([
      {
        id: 'project-1',
        org_id: 'org-1',
        name: '智慧大脑',
        environment: 'development',
        department_id: 'research',
        role: 'developer',
      },
      {
        id: 'project-2',
        org_id: 'org-1',
        name: '市场素材库',
        environment: 'development',
        department_id: 'marketing',
        role: 'owner',
      },
    ]);
    mocks.listKnowledgeLedger.mockResolvedValue({
      category: 'project_material',
      project: {
        id: 'project-1',
        name: '智慧大脑',
        environment: 'development',
        department_id: 'research',
        created_at: '2026-07-28T01:00:00Z',
        completed_at: null,
      },
      permissions: { can_review: false, can_manage: false, can_delete: false },
      leaders: [
        { user_id: 'leader-1', email: 'hanshangbo@local.dev', role: 'owner' },
      ],
      uploaders: [
        { user_id: 'user-1', email: 'test1@local.dev' },
        { user_id: 'user-2', email: 'test2@local.dev' },
      ],
      summary: {
        raw_document_count: 2,
        approved_count: 1,
        pending_count: 1,
        rejected_count: 0,
        unreviewed_count: 0,
        latest_uploaded_at: '2026-07-28T02:00:00Z',
        latest_reviewed_at: '2026-07-28T03:00:00Z',
      },
      documents: [
        {
          asset_id: 'doc-2',
          asset_type: 'project_material',
          document_id: 'doc-2',
          filename: 'README.md',
          display_name: 'README.md',
          format: 'md',
          size_bytes: 120,
          status: 'ready',
          chunk_count: 2,
          error_message: null,
          uploaded_by: { user_id: 'user-1', email: 'test1@local.dev' },
          uploaded_at: '2026-07-28T02:00:00Z',
          approval_status: 'approved',
          reviewed_by: { user_id: 'leader-1', email: 'hanshangbo@local.dev' },
          reviewed_at: '2026-07-28T03:00:00Z',
          review_comment: '通过',
          draft_id: 'draft-1',
          approved_memory_document_id: 'memory-doc-1',
        },
        {
          asset_id: 'doc-3',
          asset_type: 'project_material',
          document_id: 'doc-3',
          filename: '方案.pptx',
          display_name: '方案.pptx',
          format: 'pptx',
          size_bytes: 4096,
          status: 'ready',
          chunk_count: 1,
          error_message: null,
          uploaded_by: { user_id: 'user-2', email: 'test2@local.dev' },
          uploaded_at: '2026-07-28T02:10:00Z',
          approval_status: 'pending_review',
          reviewed_by: null,
          reviewed_at: null,
          review_comment: null,
          draft_id: 'draft-2',
          approved_memory_document_id: null,
        },
      ],
    });
  });

  it('renders a read-only project material ledger filtered by department project uploader and status', async () => {
    const user = userEvent.setup();
    render(<KnowledgePage />);

    expect(await screen.findByRole('heading', { name: '知识库' })).toBeInTheDocument();
    expect(await screen.findByRole('option', { name: '研发' })).toBeInTheDocument();
    expect(await screen.findByRole('option', { name: '智慧大脑 (development)' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '市场素材库 (development)' })).not.toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getAllByText('hanshangbo@local.dev').length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText('test1@local.dev').length).toBeGreaterThan(0);
    expect(screen.getAllByText('test2@local.dev').length).toBeGreaterThan(0);
    expect(screen.getByText('README.md')).toBeInTheDocument();
    expect(screen.getByText('方案.pptx')).toBeInTheDocument();
    expect(screen.getAllByText('已审批入库').length).toBeGreaterThan(0);
    expect(screen.getAllByText('待审批').length).toBeGreaterThan(0);
    expect(screen.queryByRole('heading', { name: '上传项目原始资料' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '检索知识库' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '确定上传资料' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '检索' })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('上传成员'), 'user-2');
    await user.selectOptions(screen.getByLabelText('审批状态'), 'pending_review');

    await waitFor(() => {
      expect(mocks.listKnowledgeLedger).toHaveBeenLastCalledWith({
        projectId: 'project-1',
        category: 'project_material',
        uploaderUserId: 'user-2',
        approvalStatus: 'pending_review',
      });
    });
  });

  it('selects knowledge projects through the complete first-level hierarchy', async () => {
    const user = userEvent.setup();
    mocks.listProjectMemoryDepartments.mockResolvedValue([
      { id: 'research', name: '研发支撑', sort_order: 1, parent_id: null, allows_projects: true, level: 1 },
      { id: 'industry', name: '产业侧', sort_order: 2, parent_id: null, allows_projects: false, level: 1 },
      { id: 'marketing', name: '市场', sort_order: 1, parent_id: 'industry', allows_projects: true, level: 2 },
    ]);

    render(<KnowledgePage />);

    await waitFor(() => {
      expect(screen.getByLabelText('第一分级')).toHaveValue('research');
    });
    expect(mocks.listProjectMemoryDepartments).toHaveBeenCalledWith(true);

    await user.selectOptions(screen.getByLabelText('第一分级'), 'industry');

    expect(await screen.findByLabelText('第二分级')).toHaveValue('marketing');
    await waitFor(() => {
      expect(mocks.listKnowledgeLedger).toHaveBeenLastCalledWith(
        expect.objectContaining({ projectId: 'project-2' }),
      );
    });
  });

  it('keeps project materials and project wiki source documents in separate categories', async () => {
    const user = userEvent.setup();
    render(<KnowledgePage />);

    await screen.findByRole('heading');
    await waitFor(() => {
      expect(mocks.listKnowledgeLedger).toHaveBeenCalledWith(
        expect.objectContaining({ category: 'project_material' }),
      );
    });

    await user.selectOptions(screen.getByLabelText('资料分类'), 'project_wiki_source');

    await waitFor(() => {
      expect(mocks.listKnowledgeLedger).toHaveBeenLastCalledWith(
        expect.objectContaining({ category: 'project_wiki_source' }),
      );
    });
    expect(screen.getByRole('option', { name: '项目原始资料' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '项目 Wiki 原始资料' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '会议记录' })).toBeInTheDocument();
  });

  it('lets overall leads delete saved documents after confirmation and refreshes the ledger', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    mocks.listKnowledgeLedger.mockResolvedValueOnce({
      category: 'project_material',
      project: {
        id: 'project-1',
        name: '鏅烘収澶ц剳',
        environment: 'development',
        department_id: 'research',
        created_at: '2026-07-28T01:00:00Z',
        completed_at: null,
      },
      permissions: { can_review: true, can_manage: true, can_delete: true },
      leaders: [
        { user_id: 'leader-1', email: 'hanshangbo@local.dev', role: 'owner' },
      ],
      uploaders: [
        { user_id: 'user-1', email: 'test1@local.dev' },
      ],
      summary: {
        raw_document_count: 1,
        approved_count: 1,
        pending_count: 0,
        rejected_count: 0,
        unreviewed_count: 0,
        latest_uploaded_at: '2026-07-28T02:00:00Z',
        latest_reviewed_at: '2026-07-28T03:00:00Z',
      },
      documents: [
        {
          asset_id: 'doc-2',
          asset_type: 'project_material',
          document_id: 'doc-2',
          filename: 'README.md',
          display_name: 'README.md',
          format: 'md',
          size_bytes: 120,
          status: 'ready',
          chunk_count: 2,
          error_message: null,
          uploaded_by: { user_id: 'user-1', email: 'test1@local.dev' },
          uploaded_at: '2026-07-28T02:00:00Z',
          approval_status: 'approved',
          reviewed_by: { user_id: 'leader-1', email: 'hanshangbo@local.dev' },
          reviewed_at: '2026-07-28T03:00:00Z',
          review_comment: '閫氳繃',
          draft_id: 'draft-1',
          approved_memory_document_id: 'memory-doc-1',
        },
      ],
    });

    render(<KnowledgePage />);

    await user.click(await screen.findByLabelText(/README.md/));

    expect(confirmSpy).toHaveBeenCalled();
    expect(mocks.deleteKnowledgeAsset).toHaveBeenCalledWith('project_material', 'doc-2');
    await waitFor(() => {
      expect(mocks.listKnowledgeLedger).toHaveBeenCalledTimes(2);
    });

    confirmSpy.mockRestore();
  });

  it('lets project leads review pending materials without showing delete actions', async () => {
    mocks.listKnowledgeLedger.mockResolvedValueOnce({
      ...(await mocks.listKnowledgeLedger()),
      permissions: { can_review: true, can_manage: true, can_delete: false },
    });

    render(<KnowledgePage />);

    expect((await screen.findAllByRole('button', { name: '去审批' })).length).toBeGreaterThan(0);
    expect(screen.queryByLabelText(/删除资料/)).not.toBeInTheDocument();
  });

  it('lets project leads preview rename and move knowledge assets while keeping delete owner-only', async () => {
    const user = userEvent.setup();
    const current = await mocks.listKnowledgeLedger();
    mocks.listKnowledgeLedger.mockResolvedValue({
      ...current,
      permissions: { can_review: true, can_manage: true, can_delete: false },
    });

    render(<KnowledgePage />);

    await user.click((await screen.findAllByRole('button', { name: '预览' }))[0]);
    expect(await screen.findByRole('dialog', { name: 'README.md' })).toHaveTextContent('# README');
    await user.click(screen.getByRole('button', { name: '关闭资料预览' }));

    await user.click(screen.getAllByRole('button', { name: '重命名' })[0]);
    const renameInput = screen.getByLabelText('新名称');
    await user.clear(renameInput);
    await user.type(renameInput, '项目说明');
    await user.click(screen.getByRole('button', { name: '确认' }));
    await waitFor(() => expect(mocks.renameKnowledgeAsset).toHaveBeenCalledWith(
      'project_material', 'doc-2', '项目说明',
    ));

    await user.click(screen.getAllByRole('button', { name: '迁移' })[0]);
    await user.selectOptions(screen.getByLabelText('目标项目'), 'project-2');
    await user.click(screen.getByRole('button', { name: '确认' }));
    await waitFor(() => expect(mocks.moveKnowledgeAsset).toHaveBeenCalledWith(
      'project_material', 'doc-2', 'project-2',
    ));
    expect(screen.queryByLabelText(/删除资料/)).not.toBeInTheDocument();
  });
});
