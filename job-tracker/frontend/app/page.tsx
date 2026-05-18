import JobsView from "@/components/JobsView";
import { supabase, type Job } from "@/lib/supabase";

export const revalidate = 600; // ISR: rebuild at most every 10 min

async function getJobs(): Promise<Job[]> {
  // Mirror the email digest's Section B filter:
  //   is_active = true AND (ai_keep IS NULL OR ai_keep = true)
  // i.e. exclude only jobs the AI explicitly dropped.
  const { data, error } = await supabase
    .from("jobs")
    .select("*, companies(name)")
    .eq("is_active", true)
    .or("ai_keep.is.null,ai_keep.eq.true")
    .order("first_seen_at", { ascending: false });

  if (error) throw new Error(error.message);
  return (data ?? []) as Job[];
}

export default async function Home() {
  const jobs = await getJobs();
  const companies = Array.from(new Set(jobs.map((j) => j.companies.name))).sort();

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Job Tracker</h1>
        <p className="mt-1 text-sm text-gray-500">
          Madrid &middot; London &mdash; {jobs.length} active listing
          {jobs.length !== 1 ? "s" : ""}
          {" across "}
          {companies.length} {companies.length !== 1 ? "companies" : "company"}.
          Filtered by local AI ({" "}
          <code className="rounded bg-gray-100 px-1 py-0.5 text-[11px]">qwen2.5:7b</code>) against{" "}
          <code className="rounded bg-gray-100 px-1 py-0.5 text-[11px]">preferences.md</code>.
        </p>
      </header>

      {jobs.length === 0 ? (
        <p className="py-20 text-center text-gray-400">
          No active listings yet. Run the scraper to populate.
        </p>
      ) : (
        <JobsView jobs={jobs} />
      )}
    </main>
  );
}
