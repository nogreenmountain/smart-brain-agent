import * as React from 'react';

export function Card({ className = '', children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={`rounded-lg border border-[#d7e0ec] bg-white shadow-[0_10px_24px_rgba(15,35,66,0.04)] ${className}`}>
      {children}
    </div>
  );
}

export function CardHeader({ className = '', children }: { className?: string; children: React.ReactNode }) {
  return <div className={`border-b border-[#e5ebf3] px-5 py-4 ${className}`}>{children}</div>;
}

export function CardTitle({ className = '', children }: { className?: string; children: React.ReactNode }) {
  return <h3 className={`text-base font-semibold text-[#10213e] ${className}`}>{children}</h3>;
}

export function CardContent({ className = '', children }: { className?: string; children: React.ReactNode }) {
  return <div className={`px-5 py-4 ${className}`}>{children}</div>;
}
