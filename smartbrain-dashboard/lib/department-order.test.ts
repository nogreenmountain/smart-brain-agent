import { describe, expect, it } from 'vitest';

import type { KeyboardCoordinateGetter } from '@dnd-kit/core';

import {
  moveDepartmentWithinSiblings,
  sameSortableContainerKeyboardCoordinates,
} from './department-order';

describe('moveDepartmentWithinSiblings', () => {
  it('moves an item and rewrites continuous display order', () => {
    const result = moveDepartmentWithinSiblings(
      [
        { id: 'direct', sort_order: 1 },
        { id: 'market', sort_order: 2 },
        { id: 'business', sort_order: 3 },
      ],
      'business',
      'direct',
    );

    expect(result).toEqual([
      { id: 'business', sort_order: 1 },
      { id: 'direct', sort_order: 2 },
      { id: 'market', sort_order: 3 },
    ]);
  });

  it('leaves the sibling list unchanged when the drop target is outside it', () => {
    const siblings = [
      { id: 'direct', sort_order: 1 },
      { id: 'market', sort_order: 2 },
    ];

    expect(moveDepartmentWithinSiblings(siblings, 'market', 'science')).toEqual(siblings);
  });
});

describe('sameSortableContainerKeyboardCoordinates', () => {
  it('hides nested sortable containers from keyboard navigation', () => {
    const rootA = {
      id: 'root-a',
      disabled: false,
      data: { current: { sortable: { containerId: 'roots' } } },
    };
    const rootB = {
      id: 'root-b',
      disabled: false,
      data: { current: { sortable: { containerId: 'roots' } } },
    };
    const directChild = {
      id: 'direct-a',
      disabled: false,
      data: { current: { sortable: { containerId: 'children-root-a' } } },
    };
    const containers = new Map([
      [rootA.id, rootA],
      [directChild.id, directChild],
      [rootB.id, rootB],
    ]) as unknown as Parameters<KeyboardCoordinateGetter>[1]['context']['droppableContainers'];
    Object.assign(containers, {
      getEnabled: () => [rootA, directChild, rootB],
    });
    const observedIds: string[][] = [];
    const baseGetter: KeyboardCoordinateGetter = (_event, args) => {
      observedIds.push(args.context.droppableContainers.getEnabled().map((item) => String(item.id)));
      expect(args.context.droppableContainers.get('root-b')).toBe(rootB);
      return { x: 10, y: 20 };
    };

    const coordinates = sameSortableContainerKeyboardCoordinates(baseGetter)(
      { code: 'ArrowDown' } as KeyboardEvent,
      {
        active: rootA.id,
        currentCoordinates: { x: 0, y: 0 },
        context: {
          droppableContainers: containers,
        } as Parameters<KeyboardCoordinateGetter>[1]['context'],
      },
    );

    expect(coordinates).toEqual({ x: 10, y: 20 });
    expect(observedIds).toEqual([['root-a', 'root-b']]);
  });
});
