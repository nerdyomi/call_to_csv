"use client";

import ChatPanel from "@/components/ChatPanel";

export default function GlobalChatPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Ask AI about all calls</h1>
        <p className="text-slate-500">
          Questions across every evaluated call: totals, averages, lists, comparisons. Numbers are calculated exactly from the extracted fields, not guessed.
        </p>
      </div>
      <ChatPanel
        scope="global" height="h-[600px]"
        intro="Try a question like these. You can write in Bangla, Banglish or English; the answer comes in Bangla."
        suggestions={[
          "মোট কতটি কল মূল্যায়ন করা হয়েছে?",
          "সবার মোট লোনের পরিমাণ কত?",
          "Which farmers have a spouse loan?",
          "Average monthly expenses koto?",
          "যাদের লোন ৫০ হাজারের বেশি তাদের তালিকা দাও",
        ]}
      />
    </div>
  );
}
