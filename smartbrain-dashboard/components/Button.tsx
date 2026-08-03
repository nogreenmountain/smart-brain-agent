'use client';

import * as React from 'react';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const variantClass: Record<Variant, string> = {
  primary: 'bg-brand-500 text-white shadow-sm shadow-blue-950/10 hover:bg-brand-600 active:bg-brand-700 disabled:bg-[#bfcbdb] disabled:text-white',
  secondary: 'bg-white text-[#10213e] border border-[#d7e0ec] hover:bg-[#f7f9fc] disabled:bg-[#f7f9fc] disabled:text-[#8b99ae]',
  ghost: 'bg-transparent text-[#253655] hover:bg-[#f7f9fc]',
  danger: 'bg-[#df5a67] text-white hover:bg-[#c94d5a] disabled:bg-[#e8a6ae]',
};

const sizeClass: Record<Size, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
  lg: 'h-11 px-5 text-base',
};

export function Button({
  variant = 'primary',
  size = 'md',
  className = '',
  ...props
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-all duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100 ${variantClass[variant]} ${sizeClass[size]} ${className}`}
      {...props}
    />
  );
}
