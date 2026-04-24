import { useMemo, useState } from 'react';
import type { AvatarCategory } from '../types';
import { AVATARS, CATEGORY_LABEL } from '../data/avatars';

type Filter = 'all' | AvatarCategory;

interface Props {
  selected: string;
  onSelect: (key: string) => void;
}

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'w', label: CATEGORY_LABEL.w },
  { id: 'm', label: CATEGORY_LABEL.m },
  { id: 'a', label: CATEGORY_LABEL.a },
];

export function AvatarPicker({ selected, onSelect }: Props) {
  const [filter, setFilter] = useState<Filter>('all');

  const filtered = useMemo(
    () =>
      Object.entries(AVATARS).filter(([, a]) =>
        filter === 'all' ? true : a.category === filter,
      ),
    [filter],
  );

  return (
    <div className="avatar-rail">
      <div className="rail-header">
        <h3>Avatar</h3>
        <span className="rail-count">{filtered.length}</span>
      </div>

      <div className="filter-chips">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`chip${filter === f.id ? ' active' : ''}`}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="rail-list">
        {filtered.map(([key, a]) => (
          <button
            key={key}
            type="button"
            className={`rail-card${key === selected ? ' active' : ''}`}
            onClick={() => onSelect(key)}
          >
            <div className={`rail-card-badge cat-${a.category}`}>
              {a.category.toUpperCase()}
            </div>
            <div className="rail-card-text">
              <div className="rail-card-name">{a.label}</div>
              <div className="rail-card-tag">
                {CATEGORY_LABEL[a.category].toLowerCase()}
                {a.language ? ` · ${a.language}` : ''}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
