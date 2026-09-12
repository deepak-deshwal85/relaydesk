export type RelayDeskRole =
  | "guest-clients"
  | "approved-clients"
  | "relaydesk-admins";

export interface ClientProfile {
  id: number;
  client_phone_number: string | null;
  client_business_phone_number: string | null;
  client_name: string;
  client_email_id: string;
  created_at: string;
}

export interface ClientAdminProfile extends ClientProfile {
  is_approved: boolean;
}

export interface MobileSession {
  user_email: string | null;
  role: RelayDeskRole | null;
  is_admin: boolean;
  is_guest: boolean;
  can_upload_documents: boolean;
  can_manage_data: boolean;
  clients: ClientAdminProfile[];
  selected_client: ClientProfile | null;
}

export type ConsumerStatusValue =
  | "READY"
  | "MEETING_SCHEDULED"
  | "MEETING_NOT_SCHEDULED";

export interface Consumer {
  id: number;
  client_id: number;
  consumer_phone_number: string;
  consumer_email_id: string;
  consumer_name: string;
  consumer_address: string;
  is_approved: boolean;
  status: ConsumerStatusValue;
  created_at: string;
  updated_at: string;
}

export interface PhoneLine {
  status: string;
  phone_number: string | null;
  phone_number_e164: string | null;
  provider: string | null;
  message: string;
  last_error: string | null;
}

export interface ConsumerListResponse {
  consumers: Consumer[];
  count: number;
}

export interface CallAttempt {
  consumer_id: number;
  consumer_phone_number: string;
  success: boolean;
  detail: string;
}

export interface CallJob {
  id: string;
  client_id: number;
  status: string;
  total_consumers: number;
  calls_completed: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  results: CallAttempt[] | null;
}

export interface CallJobListResponse {
  jobs: CallJob[];
  count: number;
}

export interface CallSummary {
  id: number;
  consumer_id: number;
  client_id: number;
  call_start_time: string;
  call_end_time: string | null;
  call_summary: string;
  job_id: string | null;
  created_at: string;
  consumer_phone_number?: string | null;
  consumer_email_id?: string | null;
}

export interface CallSummaryListResponse {
  summaries: CallSummary[];
  count: number;
}

export interface VoiceAgentConfig {
  id: number;
  client_id: number;
  client_email_id: string;
  client_name: string;
  client_business_phone_number: string | null;
  voice_agent_language: string;
  voice_agent_greeting_message: string;
  calcom_username: string | null;
  calcom_event_type_slug: string | null;
  calcom_event_type_id: number | null;
  calcom_organization_slug: string | null;
  created_at: string;
  updated_at: string;
}

export interface VoiceAgentSchedule {
  id: number;
  client_id: number;
  enabled: boolean;
  run_time: string;
  days_of_week: number[];
  timezone: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_job_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface VoiceAgentScheduleOverview {
  client_email_id: string;
  client_name: string;
  client_business_phone_number: string | null;
  ready_consumer_count: number;
  has_active_job: boolean;
  voice_agent_config: VoiceAgentConfig;
  schedule: VoiceAgentSchedule;
}

export interface DocumentSummary {
  document_id: string;
  source_uri: string;
  chunk_count: number;
}

export interface DocumentListResponse {
  collection: string;
  documents: DocumentSummary[];
  count: number;
  client_business_phone_number?: string | null;
}

export interface SearchHit {
  text: string;
  score: number;
  source_uri: string | null;
}

export interface SearchResponse {
  hits: SearchHit[];
  count: number;
  collection: string;
  client_business_phone_number?: string | null;
  client_email_id?: string | null;
}

export interface CollectionInfo {
  name: string;
  points_count: number;
  vector_size: number;
  client_business_phone_number?: string | null;
}

export interface CollectionListResponse {
  collections: string[];
  count: number;
  client_business_phone_number?: string | null;
  client_email_id?: string | null;
}

export interface ClientAdminListResponse {
  clients: ClientAdminProfile[];
  count: number;
}
