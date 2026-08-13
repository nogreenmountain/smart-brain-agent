import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ProjectHierarchySelector } from './ProjectHierarchySelector';

const departments = [
  { id: 'research', name: '研发支撑', sort_order: 1, parent_id: null, allows_projects: true, level: 1 as const },
  { id: 'industry', name: '产业侧', sort_order: 2, parent_id: null, allows_projects: false, level: 1 as const },
  { id: 'marketing', name: '市场', sort_order: 1, parent_id: 'industry', allows_projects: true, level: 2 as const },
  { id: 'business', name: '业务', sort_order: 2, parent_id: 'industry', allows_projects: true, level: 2 as const },
];

const projects = [
  { id: 'project-research', org_id: 'org-1', name: '智慧大脑', environment: 'development', department_id: 'research' },
  { id: 'project-market', org_id: 'org-1', name: '客户交流', environment: 'production', department_id: 'marketing' },
  { id: 'project-business', org_id: 'org-1', name: '业务平台', environment: 'production', department_id: 'business' },
];

describe('ProjectHierarchySelector', () => {
  it('selects projects through first level and optional second level categories', async () => {
    const user = userEvent.setup();
    const onProjectChange = vi.fn();

    const { rerender } = render(
      <ProjectHierarchySelector
        departments={departments}
        projects={projects}
        projectId="project-research"
        onProjectChange={onProjectChange}
      />,
    );

    expect(screen.getByLabelText('第一分级')).toHaveValue('research');
    expect(screen.queryByLabelText('第二分级')).not.toBeInTheDocument();
    expect(screen.getByLabelText('选择项目')).toHaveValue('project-research');

    await user.selectOptions(screen.getByLabelText('第一分级'), 'industry');
    expect(onProjectChange).toHaveBeenLastCalledWith('project-market');

    rerender(
      <ProjectHierarchySelector
        departments={departments}
        projects={projects}
        projectId="project-market"
        onProjectChange={onProjectChange}
      />,
    );

    expect(screen.getByLabelText('第一分级')).toHaveValue('industry');
    expect(screen.getByLabelText('第二分级')).toHaveValue('marketing');
    expect(screen.getByLabelText('选择项目')).toHaveValue('project-market');

    await user.selectOptions(screen.getByLabelText('第二分级'), 'business');
    expect(onProjectChange).toHaveBeenLastCalledWith('project-business');
  });
});
