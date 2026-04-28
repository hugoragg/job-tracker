import JobCard from "@/components/JobCard";
import { supabase, type Job } from "@/lib/supabase";

export const revalidate = 3600; // ISR: rebuild at most once per hour

async function getJobs(): Promise<Job[]> {
  const { data, error } = await supabase
    .from("jobs")
    .select("*, companies(name)")
    .eq("is_active", true)
    .order("first_seen_at", { ascending: false });

  if (error) throw new Error(error.message);
  return (data ?? []) as Job[];
}

export default async function Home() {
  const jobs = await getJobs();

  const byCompany = jobs.reduce<Record<string, Job[]>>((acc, job) => {
    const name = job.companies.name;
    (acc[name] ??= []).push(job);
    return acc;
  }, {});

  const sortedCompanies = Object.keys(byCompany).sort();

  return (
    <main className="mx-auto max-w-3xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Job Tracker</h1>
        <p className="mt-1 text-sm text-gray-500">
          Madrid, Spain &mdash; {jobs.length} active listing{jobs.length !== 1 ? "s" : ""}
          {" across "}
          {sortedCompanies.length} {sortedCompanies.length !== 1 ? "companies" : "company"}
        </p>
      </header>

      {jobs.length === 0 ? (
        <p className="py-20 text-center text-gray-400">
          No active listings yet. Run the scraper to populate.
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
    </main>
  );
}
