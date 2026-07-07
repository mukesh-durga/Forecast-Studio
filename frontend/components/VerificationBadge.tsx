import type { Verification } from "@/lib/types";

function CheckCircle() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
      <path
        fillRule="evenodd"
        d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.7-9.3a1 1 0 00-1.4-1.4L9 10.6 7.7 9.3a1 1 0 10-1.4 1.4l2 2a1 1 0 001.4 0l4-4z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function AlertTriangle() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="currentColor" aria-hidden>
      <path
        fillRule="evenodd"
        d="M8.3 2.9c.75-1.3 2.65-1.3 3.4 0l6.1 10.6c.75 1.3-.2 2.9-1.7 2.9H3.9c-1.5 0-2.45-1.6-1.7-2.9L8.3 2.9zM10 7a1 1 0 00-1 1v3a1 1 0 102 0V8a1 1 0 00-1-1zm0 7.5a1.1 1.1 0 100-2.2 1.1 1.1 0 000 2.2z"
        clipRule="evenodd"
      />
    </svg>
  );
}

/** Compact status pill for quick glance. Confidence detail lives in AnswerCard. */
export default function VerificationBadge({ verification }: { verification: Verification }) {
  const { verified } = verification;
  return (
    <span
      className={
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold ring-1 " +
        (verified
          ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
          : "bg-amber-50 text-amber-800 ring-amber-200")
      }
    >
      {verified ? <CheckCircle /> : <AlertTriangle />}
      {verified ? "Verified" : "Not verified"}
    </span>
  );
}
