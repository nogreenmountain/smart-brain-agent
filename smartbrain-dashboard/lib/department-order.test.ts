import { describe, expect, it } from 'vitest';

import { moveDepartmentWithinSiblings } from './department-order';

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
