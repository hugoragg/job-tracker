import type { Job } from "@/lib/supabase";

export default function JobCard({ job }: { job: Job }) {
  const date = new Date(job.first_seen_at).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
  });

  return (
    <li className="flex items-start justify-between gap-4 rounded-lg border border-gray-200 bg-white px-4 py-3 hover:border-gray-300 transition-colors">
      <div className="min-w-0">
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-blue-700 hover:underline leading-snug"
        >
          {job.title}
        </a>

        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-500">
          {job.location && <span>{job.location}</span>}
          {job.department && (
            <>
              <span className="text-gray-300">·</span>
              <span>{job.department}</span>
            </>
          )}
          {job.job_type && (
            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600">
              {job.job_type}
            </span>
          )}
        </div>
      </div>

      <time
        dateTime={job.first_seen_at}
        className="shrink-0 text-xs text-gray-400 mt-0.5"
        title={`First seen: ${new Date(job.first_seen_at).toLocaleString()}`}
      >
        {date}
      </time>
    </li>
  );
}
