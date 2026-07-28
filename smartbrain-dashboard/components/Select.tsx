'use client';

import * as React from 'react';

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  onChange: (v: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

export function Select({ value, onChange, options, placeholder, disabled, className = '' }: SelectProps) {
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className={`w-full h-10 px-3 text-sm border border-[#d7e0ec] rounded-lg bg-white text-[#10213e] focus:outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-500/20 disabled:bg-[#f7f9fc] disabled:text-[#8b99ae] ${className}`}
    >
      {placeholder && (
        <option value="" disabled>
          {placeholder}
        </option>
      )}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
