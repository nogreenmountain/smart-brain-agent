'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { BrainCircuit, LogIn } from 'lucide-react';
import { login, ApiError } from '@/lib/api';
import { Button } from '@/components/Button';
import { Input } from '@/components/Input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/Card';
import { LoadingDots } from '@/components/Feedback';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      router.replace('/chat');
    } catch (e: any) {
      if (e instanceof ApiError) {
        if (e.status === 401) setErr('邮箱或密码错误');
        else setErr(typeof e.message === 'string' ? e.message : '登录失败');
      } else {
        setErr(e?.message || '登录失败');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#eef3f9] p-4 text-[#10213e]">
      <Card className="w-full max-w-sm">
        <CardHeader className="border-b-0 pb-0 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg bg-brand-500/10 text-brand-600 ring-1 ring-brand-500/15">
            <BrainCircuit size={24} aria-hidden="true" />
          </div>
          <CardTitle className="mt-3 text-xl">智慧大脑</CardTitle>
          <div className="mt-1 text-xs text-[#6e7d97]">企业知识库与长期记忆工作台</div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="text-xs font-medium text-[#53647d]">用户名或邮箱</label>
              <Input
                type="text"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="test1 或 you@company.com"
                autoFocus
                autoComplete="username"
                required
              />
            </div>
            <div>
              <label className="text-xs font-medium text-[#53647d]">密码</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
                required
              />
            </div>
            {err && (
              <div role="alert" className="rounded-md border border-[#efc3c8] bg-[#fff5f6] px-3 py-2 text-xs text-[#b83d49]">
                {err}
              </div>
            )}
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? <LoadingDots /> : <><LogIn size={16} aria-hidden="true" />登录</>}
            </Button>
            <div className="pt-2 text-center text-xs text-[#8b99ae]">
              默认项目成员才能登录。如未开通请联系管理员。
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
