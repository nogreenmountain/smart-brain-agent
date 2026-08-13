'use client';

import { useEffect, useMemo, useState } from 'react';

import type { Department, Project } from '@/lib/api';

import { Select } from './Select';

interface ProjectHierarchySelectorProps {
  departments: Department[];
  projects: Project[];
  projectId: string;
  onProjectChange: (projectId: string) => void | Promise<void>;
  loading?: boolean;
  showEnvironment?: boolean;
  stacked?: boolean;
  className?: string;
}

function byOrder(a: Department, b: Department): number {
  return a.sort_order - b.sort_order || a.name.localeCompare(b.name, 'zh-CN');
}

export function ProjectHierarchySelector({
  departments,
  projects,
  projectId,
  onProjectChange,
  loading = false,
  showEnvironment = false,
  stacked = false,
  className = '',
}: ProjectHierarchySelectorProps) {
  const topLevels = useMemo(
    () => departments.filter((department) => !department.parent_id).sort(byOrder),
    [departments],
  );
  const selectedProject = projects.find((project) => project.id === projectId);
  const selectedDepartment = departments.find(
    (department) => department.id === selectedProject?.department_id,
  );
  const selectedFirstLevelId = selectedDepartment?.parent_id || selectedDepartment?.id || '';
  const selectedSecondLevelId = selectedDepartment?.parent_id ? selectedDepartment.id : '';
  const [firstLevelId, setFirstLevelId] = useState(selectedFirstLevelId);
  const [secondLevelId, setSecondLevelId] = useState(selectedSecondLevelId);

  useEffect(() => {
    if (selectedFirstLevelId) {
      setFirstLevelId(selectedFirstLevelId);
      setSecondLevelId(selectedSecondLevelId);
      return;
    }
    if (!topLevels.some((department) => department.id === firstLevelId)) {
      setFirstLevelId(topLevels[0]?.id || '');
      setSecondLevelId('');
    }
  }, [firstLevelId, selectedFirstLevelId, selectedSecondLevelId, topLevels]);

  const secondLevels = useMemo(
    () => departments.filter((department) => department.parent_id === firstLevelId).sort(byOrder),
    [departments, firstLevelId],
  );
  const effectiveSecondLevelId = secondLevels.some((department) => department.id === secondLevelId)
    ? secondLevelId
    : secondLevels[0]?.id || '';
  const projectDepartmentId = secondLevels.length > 0 ? effectiveSecondLevelId : firstLevelId;
  const filteredProjects = projects.filter(
    (project) => (project.department_id || 'research') === projectDepartmentId,
  );

  function firstProjectInDepartment(departmentId: string): string {
    return projects.find((project) => (project.department_id || 'research') === departmentId)?.id || '';
  }

  function handleFirstLevelChange(value: string) {
    setFirstLevelId(value);
    const children = departments.filter((department) => department.parent_id === value).sort(byOrder);
    const childWithProject = children.find((child) => Boolean(firstProjectInDepartment(child.id)));
    const nextDepartmentId = childWithProject?.id || children[0]?.id || value;
    setSecondLevelId(children.length > 0 ? nextDepartmentId : '');
    void onProjectChange(firstProjectInDepartment(nextDepartmentId));
  }

  function handleSecondLevelChange(value: string) {
    setSecondLevelId(value);
    void onProjectChange(firstProjectInDepartment(value));
  }

  return (
    <div className={`grid grid-cols-1 gap-3 ${stacked ? '' : 'md:grid-cols-3'} ${className}`}>
      <label className="block">
        <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">第一分级</span>
        <Select
          value={firstLevelId}
          onChange={handleFirstLevelChange}
          placeholder={loading ? '加载分类中' : '选择第一分级'}
          disabled={loading || topLevels.length === 0}
          options={topLevels.map((department) => ({ value: department.id, label: department.name }))}
        />
      </label>

      {secondLevels.length > 0 && (
        <label className="block">
          <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">第二分级</span>
          <Select
            value={effectiveSecondLevelId}
            onChange={handleSecondLevelChange}
            placeholder="选择第二分级"
            disabled={loading}
            options={secondLevels.map((department) => ({ value: department.id, label: department.name }))}
          />
        </label>
      )}

      <label className="block">
        <span className="mb-1 block text-xs font-semibold text-[#6e7d97]">选择项目</span>
        <Select
          value={projectId}
          onChange={(value) => void onProjectChange(value)}
          placeholder={loading ? '加载项目中' : '当前分类暂无项目'}
          disabled={loading || filteredProjects.length === 0}
          options={filteredProjects.map((project) => ({
            value: project.id,
            label: showEnvironment ? `${project.name} (${project.environment})` : project.name,
          }))}
        />
      </label>
    </div>
  );
}
