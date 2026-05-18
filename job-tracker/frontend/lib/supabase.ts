import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
);

export type Company = {
  id: string;
  name: string;
  careers_url: string | null;
  ats_platform: string;
};

export type Job = {
  id: string;
  company_id: string;
  title: string;
  url: string;
  location: string | null;
  department: string | null;
  job_type: string | null;
  description: string | null;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string;
  ai_keep: boolean | null;
  ai_reason: string | null;
  companies: Pick<Company, "name">;
};
