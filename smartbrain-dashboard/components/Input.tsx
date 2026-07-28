import * as React from 'react';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className = '', ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={`w-full h-10 px-3 text-sm border border-[#d7e0ec] rounded-lg bg-white text-[#10213e] placeholder:text-[#8b99ae] focus:outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-500/20 disabled:bg-[#f7f9fc] disabled:text-[#8b99ae] ${className}`}
        {...props}
      />
    );
  }
);
Input.displayName = 'Input';

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className = '', ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={`w-full px-3 py-2 text-sm border border-[#d7e0ec] rounded-lg bg-white text-[#10213e] placeholder:text-[#8b99ae] focus:outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-500/20 resize-y disabled:bg-[#f7f9fc] ${className}`}
        {...props}
      />
    );
  }
);
Textarea.displayName = 'Textarea';
