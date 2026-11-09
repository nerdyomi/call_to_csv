export type CallStatus = "uploaded" | "queued" | "processing" | "done" | "failed";

export interface Call {
  id: string;
  phone: string;
  call_date: string | null;
  call_seq: number;
  file_name: string;
  storage_path: string;
  file_size: number | null;
  duration_seconds: number | null;
  status: CallStatus;
  stage?: string | null; // exists after migration 002
  progress?: number | null; // exists after migration 002
  error: string | null;
  attempts: number;
  model: string | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface TranscriptTurn {
  speaker: "CEX" | "farmer" | "other";
  time: string;
  text: string;
}
export interface EvidenceItem {
  confidence: "high" | "medium" | "low";
  evidence: string;
  timestamp: string;
}
export interface ReviewItem {
  field: string;
  kind: string;
  detail: string;
}

export interface Behaviour {
  overall: string;
  tone: string;
  cooperation: { level: "high" | "medium" | "low"; why: string };
  consistency: { level: "consistent" | "mostly_consistent" | "inconsistent"; why: string };
  confidence_in_answers: { level: "high" | "medium" | "low"; why: string };
  financial_stress_signals: string[];
  red_flags: { point: string; time: string }[];
  positives: { point: string; time: string }[];
  follow_up_questions: string[];
}

export interface CallResult {
  call_id: string;
  transcript: TranscriptTurn[];
  transcript_text: string;
  fields: Record<string, string>;
  evidence: Record<string, EvidenceItem>;
  review: ReviewItem[];
  notes: string | null;
  eng_notes: string | null;
  assessment: {
    audio_quality?: string;
    is_kyc_call?: boolean;
    respondent_is_farmer?: string;
    language_note?: string;
  } | null;
  usage: Record<string, unknown> | null;
  model: string | null;
  updated_at: string;
  behaviour?: Behaviour | null;
  behaviour_model?: string | null;
  behaviour_at?: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}
