'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
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
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-brand-50 via-white to-brand-50 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center border-b-0 pb-0">
          <div className="w-14 h-14 mx-auto rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-2xl text-white shadow-md">
            🧠
          </div>
          <CardTitle className="mt-3 text-xl">智慧大脑</CardTitle>
          <div className="text-xs text-gray-500 mt-1">局域网知识库与智能问答</div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="text-xs text-gray-600">用户名或邮箱</label>
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
              <label className="text-xs text-gray-600">密码</label>
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
              <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-2 py-1.5">
                {err}
              </div>
            )}
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? <LoadingDots /> : '登录'}
            </Button>
            <div className="text-xs text-center text-gray-400 pt-2">
              默认项目成员才能登录。如未开通请联系管理员。
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
