"use client";

// 案件ワークスペースの入口。最後にいたステップ（MVPは②情報収集）へリダイレクト。
import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Spinner } from "@/components/ui/Spinner";

export default function WorkspaceIndex() {
  const params = useParams<{ caseNo: string }>();
  const router = useRouter();
  const caseNo = params.caseNo;

  useEffect(() => {
    router.replace(`/cases/${caseNo}/collect`);
  }, [caseNo, router]);

  return (
    <div className="flex items-center justify-center py-12 text-slate-400">
      <Spinner className="h-6 w-6" />
    </div>
  );
}
