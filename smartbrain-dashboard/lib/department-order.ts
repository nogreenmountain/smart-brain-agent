import type { KeyboardCoordinateGetter } from '@dnd-kit/core';

export interface SortableDepartment {
  id: string;
  sort_order: number;
}

export function sameSortableContainerKeyboardCoordinates(
  baseGetter: KeyboardCoordinateGetter,
): KeyboardCoordinateGetter {
  return (event, args) => {
    const containers = args.context.droppableContainers;
    const activeContainer = containers.get(args.active);
    const sortableContainerId = activeContainer?.data.current?.sortable?.containerId;
    if (!sortableContainerId) return baseGetter(event, args);

    const siblings = containers.getEnabled().filter(
      (container) => container.data.current?.sortable?.containerId === sortableContainerId,
    );
    const siblingContainers = Object.create(containers) as typeof containers;
    Object.defineProperties(siblingContainers, {
      get: { value: containers.get.bind(containers) },
      getEnabled: { value: () => siblings },
    });

    return baseGetter(event, {
      ...args,
      context: {
        ...args.context,
        droppableContainers: siblingContainers,
      },
    });
  };
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
