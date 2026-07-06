import type { Verification } from "@/lib/types";

export default function VerificationBadge({ verification }: { verification: Verification }) {
  const { verified, confidence } = verification;
  const pct = Math.round(confidence * 100);

  return (
    <div className="flex flex-wrap items-center gap-3">
      <span
        className={
          "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-semibold " +
          (verified
            ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200"
            : "bg-amber-100 text-amber-800 ring-1 ring-amber-200")
        }
      >
        <span
          className={
            "h-2 w-2 rounded-full " + (verified ? "bg-emerald-500" : "bg-amber-500")
          }
        />
        {verified ? "Verified" : "Unverified"}
      </span>

      <div className="flex items-center gap-2">
        <div className="h-2 w-28 overflow-hidden rounded-full bg-slate-200">
          <div
            className={"h-full rounded-full " + (verified ? "bg-emerald-500" : "bg-amber-500")}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-sm font-medium tabular-nums text-slate-600">
          {pct}% confidence
        </span>
      </div>
    </div>
  );
}
