"use client";

import { useMemo, useState } from "react";
import JobCard from "@/components/JobCard";
import type { Job } from "@/lib/supabase";

type DateRange = "today" | "7d" | "all";

const RANGE_LABELS: Record<DateRange, string> = {
  today: "Today",
  "7d": "Last 7 days",
  all: "All",
};

function withinRange(iso: string, range: DateRange): boolean {
  if (range === "all") return true;
  const seen = new Date(iso).getTime();
  const now = Date.now();
  const days = range === "today" ? 1 : 7;
  return now - seen <= days * 24 * 60 * 60 * 1000;
}

function matchesQuery(job: Job, q: string): boolean {
  if (!q) return true;
  const hay = [
    job.title,
    job.companies.name,
    job.location ?? "",
    job.department ?? "",
    job.ai_reason ?? "",
  ]
    .join(" ")
    .toLowerCase();
  return hay.includes(q.toLowerCase());
}

export default function JobsView({ jobs }: { jobs: Job[] }) {
  const [query, setQuery] = useState("");
  const [range, setRange] = useState<DateRange>("all");

  const filtered = useMemo(
    () => jobs.filter((j) => withinRange(j.first_seen_at, range) && matchesQuery(j, query)),
    [jobs, query, range],
  );

  const byCompany = useMemo(() => {
    const acc: Record<string, Job[]> = {};
    for (const j of filtered) {
      const name = j.companies.name;
      (acc[name] ??= []).push(j);
    }
    return acc;
  }, [filtered]);

  const sortedCompanies = Object.keys(byCompany).sort();

  return (
    <>
      <div className="mb-6 space-y-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search title, company, location, department…"
          className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {(Object.keys(RANGE_LABELS) as DateRange[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={
                "rounded-full border px-3 py-1 transition-colors " +
                (range === r
                  ? "border-blue-600 bg-blue-600 text-white"
                  : "border-gray-200 bg-white text-gray-600 hover:border-gray-300")
              }
            >
              {RANGE_LABELS[r]}
            </button>
          ))}
          <span className="ml-auto text-xs text-gray-400">
            Showing {filtered.length} of {jobs.length}
          </span>
        </div>
      </div>

      {filtered.length === 0 ? (
        <p className="py-20 text-center text-gray-400">
          No matches for current filters.
        </p>
      ) : (
        <div className="space-y-10">
          {sortedCompanies.map((company) => (
            <section key={company}>
              <h2 className="mb-3 flex items-center justify-between border-b border-gray-200 pb-2 text-base font-semibold">
                {company}
                <span className="text-sm font-normal text-gray-400">
                  {byCompany[company].length}
                </span>
              </h2>
              <ul className="space-y-2">
                {byCompany[company].map((job) => (
                  <JobCard key={job.id} job={job} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
