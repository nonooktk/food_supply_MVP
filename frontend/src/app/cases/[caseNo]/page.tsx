"use client";

// 案件ワークスペースの入口。最後にいたステップへリダイレクトする（m-2）。
import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { Spinner } from "@/components/ui/Spinner";
import * as store from "@/lib/store";

export default function WorkspaceIndex() {
  const params = useParams<{ caseNo: string }>();
  const router = useRouter();
  const caseNo = decodeURIComponent(params.caseNo);

  useEffect(() => {
    const last = store.getLastStep(caseNo); // 既定は "collect"
    router.replace(`/cases/${encodeURIComponent(caseNo)}/${last}`);
  }, [caseNo, router]);

  return (
    <div className="flex items-center justify-center py-12 text-slate-400">
      <Spinner className="h-6 w-6" />
    </div>
  );
}
