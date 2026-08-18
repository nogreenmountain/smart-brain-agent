import { redirect } from 'next/navigation';

export default function TeamPage() {
  redirect('/admin?view=members');
}
