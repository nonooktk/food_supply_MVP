"use client";

// ルート。ログイン状態に応じて案件一覧またはログインへ振り分ける。
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Spinner } from "@/components/ui/Spinner";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    router.replace(user ? "/cases" : "/login");
  }, [user, loading, router]);

  return (
    <div className="flex min-h-screen items-center justify-center text-slate-400">
      <Spinner className="h-6 w-6" />
    </div>
  );
}
