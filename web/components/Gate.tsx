"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { supabaseBrowser } from "@/lib/supabase/client";

/** Shows a clear message when someone is logged in but is not on the allow-list (the database would return nothing). */
export default function Gate({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [state, setState] = useState<"checking" | "ok" | "denied">("checking");

  useEffect(() => {
    if (path.startsWith("/login")) return;
    supabaseBrowser()
      .rpc("is_allowed")
      .then(({ data }) => setState(data === true ? "ok" : "denied"));
  }, [path]);

  if (path.startsWith("/login") || state === "ok") return <>{children}</>;
  if (state === "checking") return <div className="py-20 text-center text-slate-500"><span className="spinner" /> Loading…</div>;
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-amber-200 bg-amber-50 p-6 text-center">
      <h2 className="text-lg font-semibold text-amber-900">Your account is not allowed here yet</h2>
      <p className="mt-2 text-sm text-amber-800">Ask the project owner to add your email to the allow-list.</p>
      <button
        className="mt-4 rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm ring-1 ring-slate-200"
        onClick={async () => {
          await supabaseBrowser().auth.signOut();
          router.replace("/login");
        }}
      >
        Sign out
      </button>
    </div>
  );
}
