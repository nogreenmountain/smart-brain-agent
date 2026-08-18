export interface SortableDepartment {
  id: string;
  sort_order: number;
}

export function moveDepartmentWithinSiblings<T extends SortableDepartment>(
  siblings: T[],
  activeId: string,
  overId: string,
): T[] {
  const oldIndex = siblings.findIndex((department) => department.id === activeId);
  const newIndex = siblings.findIndex((department) => department.id === overId);
  if (oldIndex < 0 || newIndex < 0 || oldIndex === newIndex) return siblings;

  const next = [...siblings];
  const [moved] = next.splice(oldIndex, 1);
  next.splice(newIndex, 0, moved);
  return next.map((department, index) => ({ ...department, sort_order: index + 1 }));
}
