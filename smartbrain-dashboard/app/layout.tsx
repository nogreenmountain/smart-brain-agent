import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '智慧大脑',
  description: '局域网知识库与智能问答',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen">
        {children}
      </body>
    </html>
  );
}