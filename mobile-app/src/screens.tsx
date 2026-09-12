/* eslint-disable react-hooks/set-state-in-effect, react-hooks/preserve-manual-memoization */
import * as DocumentPicker from "expo-document-picker";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Switch, Text, View } from "react-native";

import { apiJson, apiRequest, apiUpload, runtimeConfig } from "@/api";
import { useAuth, usePermissions } from "@/state";
import type {
  CallJob,
  CallJobListResponse,
  CallSummary,
  CallSummaryListResponse,
  ClientAdminListResponse,
  ClientAdminProfile,
  CollectionInfo,
  CollectionListResponse,
  Consumer,
  ConsumerListResponse,
  ConsumerStatusValue,
  DocumentListResponse,
  PhoneLine,
  SearchResponse,
  VoiceAgentConfig,
  VoiceAgentScheduleOverview,
} from "@/types";
import {
  Banner,
  Card,
  Field,
  ListItem,
  LoadingBlock,
  PrimaryButton,
  Screen,
  SecondaryButton,
  SectionTitle,
  StatRow,
} from "@/ui";

const SUPPORTED_LANGUAGES = [
  "hi-IN",
  "en-IN",
  "bn-IN",
  "gu-IN",
  "kn-IN",
  "ml-IN",
  "mr-IN",
  "od-IN",
  "pa-IN",
  "ta-IN",
  "te-IN",
];

const DAY_OPTIONS = [
  { value: 1, label: "Mon" },
  { value: 2, label: "Tue" },
  { value: 3, label: "Wed" },
  { value: 4, label: "Thu" },
  { value: 5, label: "Fri" },
  { value: 6, label: "Sat" },
  { value: 7, label: "Sun" },
];

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function formatPhoneDisplay(value: string | null | undefined) {
  if (!value) return "-";
  return value.startsWith("+") ? value : `+${value}`;
}

function buildClientQuery(clientEmailId: string | null | undefined) {
  return clientEmailId ? { client_email_id: clientEmailId } : undefined;
}

function BuyNumberCard({
  clientEmailId,
  sessionHeaders,
  onPurchased,
}: {
  clientEmailId: string | null | undefined;
  sessionHeaders: { accessToken: string | null; sessionEmail: string | null; sessionRole: string | null };
  onPurchased?: () => Promise<void> | void;
}) {
  const [line, setLine] = useState<PhoneLine | null>(null);
  const [buying, setBuying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientEmailId) return;
    try {
      const data = await apiRequest<PhoneLine>(
        sessionHeaders,
        "v1/mobile/phone-line",
        undefined,
        buildClientQuery(clientEmailId),
      );
      setLine(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load phone line");
    }
  }, [clientEmailId, sessionHeaders]);

  useEffect(() => {
    void load();
  }, [load]);

  async function buy() {
    if (!clientEmailId) return;
    setBuying(true);
    try {
      const data = await apiJson<PhoneLine>(
        sessionHeaders,
        "v1/mobile/phone-line/buy",
        "POST",
        {},
        buildClientQuery(clientEmailId),
      );
      setLine(data);
      setError(null);
      await onPurchased?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to buy number");
      await load();
    } finally {
      setBuying(false);
    }
  }

  const active = line?.status === "active";
  const buttonTitle = buying
    ? "Buying number..."
    : line?.status === "failed" || line?.status === "provisioning"
      ? "Retry number setup"
      : "Buy a business number";

  return (
    <Card>
      <SectionTitle>Business number</SectionTitle>
      <StatRow
        label="Number"
        value={formatPhoneDisplay(line?.phone_number_e164 ?? line?.phone_number)}
      />
      <StatRow label="Status" value={line?.status ?? "none"} />
      {line?.message ? <Banner kind={active ? "info" : "error"} message={line.message} /> : null}
      {error ? <Banner kind="error" message={error} /> : null}
      {active ? null : (
        <PrimaryButton title={buttonTitle} onPress={() => void buy()} disabled={buying || !clientEmailId} />
      )}
    </Card>
  );
}

function summaryPreview(text: string, max = 120) {
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max).trim()}...`;
}

function useSelectedClientEmail() {
  const { selectedClient } = useAuth();
  return selectedClient?.client_email_id ?? null;
}

export function LoginScreen() {
  const { signInLocal, booting } = useAuth();
  const [email, setEmail] = useState("acme@example.com");
  const [role, setRole] = useState<"approved-clients" | "relaydesk-admins">(
    "approved-clients",
  );
  const [error, setError] = useState<string | null>(null);

  async function handleLocalSignIn() {
    try {
      setError(null);
      await signInLocal(email, role);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    }
  }

  return (
    <Screen
      title="RelayDesk Mobile"
      subtitle="Low-cost mobile operations app for campaigns, consumers, knowledge, and voice settings."
    >
      {error ? <Banner kind="error" message={error} /> : null}
      <Card>
        <SectionTitle>Sign in</SectionTitle>
        <Field
          label="Email"
          value={email}
          onChangeText={setEmail}
          keyboardType="email-address"
          placeholder="you@example.com"
        />
        <Field
          label="Role"
          value={role}
          onChangeText={(value) =>
            setRole(value === "relaydesk-admins" ? "relaydesk-admins" : "approved-clients")
          }
          placeholder="approved-clients or relaydesk-admins"
        />
        <PrimaryButton
          title={booting ? "Starting..." : "Continue in local mode"}
          onPress={() => void handleLocalSignIn()}
          disabled={booting}
        />
        {!runtimeConfig.authDisableSso ? (
          <Banner
            kind="info"
            message="Set up Cognito issuer and client ID in app config to replace the local sign-in flow with hosted OAuth."
          />
        ) : null}
      </Card>
    </Screen>
  );
}

export function DashboardScreen() {
  const { sessionHeaders, selectedClient } = useAuth();
  const { canManageData } = usePermissions();
  const clientEmailId = useSelectedClientEmail();
  const [overview, setOverview] = useState<VoiceAgentScheduleOverview | null>(null);
  const [consumers, setConsumers] = useState<ConsumerListResponse | null>(null);
  const [collections, setCollections] = useState<CollectionListResponse | null>(null);
  const [calls, setCalls] = useState<CallSummaryListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!clientEmailId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const query = buildClientQuery(clientEmailId);
      const [overviewData, consumerData, collectionData, callData] = await Promise.all([
        apiRequest<VoiceAgentScheduleOverview>(sessionHeaders, "v1/mobile/voice-agent-schedule", undefined, query),
        apiRequest<ConsumerListResponse>(sessionHeaders, "v1/mobile/consumers", undefined, query),
        apiRequest<CollectionListResponse>(sessionHeaders, "v1/mobile/collections", undefined, query),
        apiRequest<CallSummaryListResponse>(sessionHeaders, "v1/mobile/call-summaries", undefined, {
          ...query,
          limit: 5,
        }),
      ]);
      setOverview(overviewData);
      setConsumers(consumerData);
      setCollections(collectionData);
      setCalls(callData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, [clientEmailId, sessionHeaders]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Screen
      title="Dashboard"
      subtitle={selectedClient ? `Overview for ${selectedClient.client_name}` : "Select a client to begin."}
    >
      {error ? <Banner kind="error" message={error} /> : null}
      {loading ? <LoadingBlock label="Loading dashboard" /> : null}
      {!loading && overview ? (
        <>
          <Card>
            <SectionTitle>Overview</SectionTitle>
            <StatRow label="Ready to call" value={overview.ready_consumer_count} />
            <StatRow label="Consumers" value={consumers?.count ?? 0} />
            <StatRow label="Knowledge bases" value={collections?.count ?? 0} />
            <StatRow label="Calls logged" value={calls?.count ?? 0} />
            <StatRow
              label="Business phone"
              value={formatPhoneDisplay(overview.client_business_phone_number)}
            />
            <StatRow
              label="Next campaign"
              value={overview.schedule.enabled ? formatDate(overview.schedule.next_run_at) : "Disabled"}
            />
          </Card>
          <Card>
            <SectionTitle>Voice agent</SectionTitle>
            <Text>Language: {overview.voice_agent_config.voice_agent_language}</Text>
            <Text>
              Cal.com:{" "}
              {overview.voice_agent_config.calcom_username &&
              overview.voice_agent_config.calcom_event_type_slug
                ? "Configured"
                : "Not configured"}
            </Text>
          </Card>
          <Card>
            <SectionTitle>Recent calls</SectionTitle>
            {(calls?.summaries ?? []).map((summary) => (
              <ListItem
                key={summary.id}
                title={formatPhoneDisplay(summary.consumer_phone_number)}
                subtitle={summaryPreview(summary.call_summary)}
                rightText={formatDate(summary.call_start_time)}
              />
            ))}
            {!calls?.summaries?.length ? <Text>No calls yet.</Text> : null}
          </Card>
          {canManageData ? (
            <Banner
              kind="info"
              message="Admin mode is enabled. Use the Admin tab for client approval, semantic search, and collections."
            />
          ) : null}
        </>
      ) : null}
      <SecondaryButton title="Refresh" onPress={() => void load()} />
    </Screen>
  );
}

export function ConsumersScreen() {
  const { sessionHeaders } = useAuth();
  const { canManageOwnConsumers } = usePermissions();
  const clientEmailId = useSelectedClientEmail();
  const [consumers, setConsumers] = useState<Consumer[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [consumerName, setConsumerName] = useState("");
  const [consumerPhone, setConsumerPhone] = useState("");
  const [consumerEmail, setConsumerEmail] = useState("");
  const [consumerAddress, setConsumerAddress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const resetForm = () => {
    setEditingId(null);
    setConsumerName("");
    setConsumerPhone("");
    setConsumerEmail("");
    setConsumerAddress("");
  };

  const load = useCallback(async () => {
    if (!clientEmailId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await apiRequest<ConsumerListResponse>(
        sessionHeaders,
        "v1/mobile/consumers",
        undefined,
        buildClientQuery(clientEmailId),
      );
      setConsumers(data.consumers);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load consumers");
    } finally {
      setLoading(false);
    }
  }, [clientEmailId, sessionHeaders]);

  useEffect(() => {
    void load();
  }, [load]);

  const startEdit = (consumer: Consumer) => {
    setEditingId(consumer.id);
    setConsumerName(consumer.consumer_name);
    setConsumerPhone(consumer.consumer_phone_number);
    setConsumerEmail(consumer.consumer_email_id);
    setConsumerAddress(consumer.consumer_address);
  };

  async function saveConsumer() {
    if (!clientEmailId) return;
    setSaving(true);
    try {
      if (editingId) {
        await apiJson(
          sessionHeaders,
          `v1/mobile/consumers/${editingId}`,
          "PUT",
          {
            consumer_name: consumerName,
            consumer_phone_number: consumerPhone,
            consumer_email_id: consumerEmail,
            consumer_address: consumerAddress,
          },
          buildClientQuery(clientEmailId),
        );
      } else {
        await apiJson(
          sessionHeaders,
          "v1/mobile/consumers",
          "POST",
          {
            consumer_name: consumerName,
            consumer_phone_number: consumerPhone,
            consumer_email_id: consumerEmail,
            consumer_address: consumerAddress,
          },
          buildClientQuery(clientEmailId),
        );
      }
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save consumer");
    } finally {
      setSaving(false);
    }
  }

  async function deleteConsumer(id: number) {
    if (!clientEmailId) return;
    try {
      await apiRequest(
        sessionHeaders,
        `v1/mobile/consumers/${id}`,
        { method: "DELETE" },
        buildClientQuery(clientEmailId),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete consumer");
    }
  }

  return (
    <Screen title="Consumers" subtitle="Manage consumers for the selected client.">
      {error ? <Banner kind="error" message={error} /> : null}
      {loading ? <LoadingBlock label="Loading consumers" /> : null}
      {canManageOwnConsumers ? (
        <Card>
          <SectionTitle>{editingId ? "Edit consumer" : "Add consumer"}</SectionTitle>
          <Field label="Consumer name" value={consumerName} onChangeText={setConsumerName} />
          <Field
            label="Consumer phone"
            value={consumerPhone}
            onChangeText={setConsumerPhone}
            keyboardType="phone-pad"
          />
          <Field
            label="Consumer email"
            value={consumerEmail}
            onChangeText={setConsumerEmail}
            keyboardType="email-address"
          />
          <Field
            label="Consumer address"
            value={consumerAddress}
            onChangeText={setConsumerAddress}
            multiline
          />
          <PrimaryButton
            title={saving ? "Saving..." : editingId ? "Update consumer" : "Create consumer"}
            onPress={() => void saveConsumer()}
            disabled={saving}
          />
          {editingId ? <SecondaryButton title="Cancel" onPress={resetForm} /> : null}
        </Card>
      ) : (
        <Banner kind="info" message="Your role can view consumers but cannot change them." />
      )}
      <Card>
        <SectionTitle>All consumers</SectionTitle>
        {consumers.map((consumer) => (
          <View key={consumer.id}>
            <ListItem
              title={consumer.consumer_name || formatPhoneDisplay(consumer.consumer_phone_number)}
              subtitle={`${consumer.consumer_email_id} | ${consumer.status}`}
            />
            {canManageOwnConsumers ? (
              <View style={{ flexDirection: "row", gap: 8, marginBottom: 12 }}>
                <View style={{ flex: 1 }}>
                  <SecondaryButton title="Edit" onPress={() => startEdit(consumer)} />
                </View>
                <View style={{ flex: 1 }}>
                  <SecondaryButton
                    title="Delete"
                    onPress={() =>
                      Alert.alert("Delete consumer", "This cannot be undone.", [
                        { text: "Cancel", style: "cancel" },
                        { text: "Delete", style: "destructive", onPress: () => void deleteConsumer(consumer.id) },
                      ])
                    }
                  />
                </View>
              </View>
            ) : null}
          </View>
        ))}
        {!consumers.length ? <Text>No consumers yet.</Text> : null}
      </Card>
      <SecondaryButton title="Refresh" onPress={() => void load()} />
    </Screen>
  );
}

export function CampaignsScreen() {
  const { sessionHeaders } = useAuth();
  const { canManageOwnConsumers } = usePermissions();
  const clientEmailId = useSelectedClientEmail();
  const [overview, setOverview] = useState<VoiceAgentScheduleOverview | null>(null);
  const [consumers, setConsumers] = useState<Consumer[]>([]);
  const [jobs, setJobs] = useState<CallJob[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [runTime, setRunTime] = useState("09:00");
  const [daysOfWeek, setDaysOfWeek] = useState<number[]>([1, 2, 3, 4, 5]);
  const [timezone, setTimezone] = useState("Asia/Kolkata");

  const query = buildClientQuery(clientEmailId);

  const load = useCallback(async () => {
    if (!clientEmailId) return;
    try {
      const [overviewData, consumerData, jobData] = await Promise.all([
        apiRequest<VoiceAgentScheduleOverview>(sessionHeaders, "v1/mobile/voice-agent-schedule", undefined, query),
        apiRequest<ConsumerListResponse>(sessionHeaders, "v1/mobile/consumers", undefined, query),
        apiRequest<CallJobListResponse>(sessionHeaders, "v1/mobile/call-jobs", undefined, {
          ...query,
          limit: 10,
        }),
      ]);
      setOverview(overviewData);
      setConsumers(consumerData.consumers);
      setJobs(jobData.jobs);
      setScheduleEnabled(overviewData.schedule.enabled);
      setRunTime(overviewData.schedule.run_time);
      setDaysOfWeek(overviewData.schedule.days_of_week);
      setTimezone(overviewData.schedule.timezone);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load campaigns");
    }
  }, [clientEmailId, query, sessionHeaders]);

  useEffect(() => {
    void load();
  }, [load]);

  async function triggerNow() {
    if (!clientEmailId) return;
    setTriggering(true);
    try {
      await apiJson(sessionHeaders, "v1/mobile/call-jobs/trigger", "POST", undefined, query);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to trigger campaign");
    } finally {
      setTriggering(false);
    }
  }

  async function saveSchedule() {
    if (!clientEmailId) return;
    setSaving(true);
    try {
      await apiJson(
        sessionHeaders,
        "v1/mobile/voice-agent-schedule",
        "PUT",
        {
          enabled: scheduleEnabled,
          run_time: runTime,
          days_of_week: daysOfWeek,
          timezone,
        },
        query,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save schedule");
    } finally {
      setSaving(false);
    }
  }

  async function updateStatus(consumer: Consumer, status: ConsumerStatusValue) {
    if (!clientEmailId) return;
    try {
      await apiJson(
        sessionHeaders,
        `v1/mobile/consumers/${consumer.id}`,
        "PUT",
        { status },
        query,
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status");
    }
  }

  return (
    <Screen title="Campaigns" subtitle="Run outbound calls now or on a schedule.">
      {error ? <Banner kind="error" message={error} /> : null}
      <BuyNumberCard
        clientEmailId={clientEmailId}
        sessionHeaders={sessionHeaders}
        onPurchased={load}
      />
      <Card>
        <SectionTitle>Run campaign</SectionTitle>
        <StatRow label="Ready consumers" value={overview?.ready_consumer_count ?? 0} />
        <StatRow
          label="Business phone"
          value={formatPhoneDisplay(overview?.client_business_phone_number)}
        />
        <StatRow
          label="Active job"
          value={overview?.has_active_job ? "Running" : "No"}
        />
        <PrimaryButton
          title={triggering ? "Starting..." : "Run now"}
          onPress={() => void triggerNow()}
          disabled={!canManageOwnConsumers || triggering}
        />
      </Card>
      <Card>
        <SectionTitle>Schedule</SectionTitle>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <Text>Enable automatic campaigns</Text>
          <Switch value={scheduleEnabled} onValueChange={setScheduleEnabled} />
        </View>
        <Field label="Run time" value={runTime} onChangeText={setRunTime} />
        <Field label="Timezone" value={timezone} onChangeText={setTimezone} />
        <Field
          label="Days of week"
          value={daysOfWeek.join(",")}
          onChangeText={(value) => {
            const parsed = value
              .split(",")
              .map((part) => Number(part.trim()))
              .filter((part) => DAY_OPTIONS.some((day) => day.value === part));
            setDaysOfWeek(parsed);
          }}
          placeholder="1,2,3,4,5"
        />
        <PrimaryButton
          title={saving ? "Saving..." : "Save schedule"}
          onPress={() => void saveSchedule()}
          disabled={!canManageOwnConsumers || saving}
        />
      </Card>
      <Card>
        <SectionTitle>Ready consumers</SectionTitle>
        {consumers.map((consumer) => (
          <View key={consumer.id}>
            <ListItem
              title={consumer.consumer_name || formatPhoneDisplay(consumer.consumer_phone_number)}
              subtitle={consumer.consumer_email_id}
              rightText={consumer.status}
            />
            {canManageOwnConsumers ? (
              <View style={{ flexDirection: "row", gap: 8, marginBottom: 12 }}>
                <View style={{ flex: 1 }}>
                  <SecondaryButton title="Ready" onPress={() => void updateStatus(consumer, "READY")} />
                </View>
                <View style={{ flex: 1 }}>
                  <SecondaryButton
                    title="Meeting scheduled"
                    onPress={() => void updateStatus(consumer, "MEETING_SCHEDULED")}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <SecondaryButton
                    title="No meeting"
                    onPress={() => void updateStatus(consumer, "MEETING_NOT_SCHEDULED")}
                  />
                </View>
              </View>
            ) : null}
          </View>
        ))}
      </Card>
      <Card>
        <SectionTitle>Recent jobs</SectionTitle>
        {jobs.map((job) => (
          <ListItem
            key={job.id}
            title={formatDate(job.created_at)}
            subtitle={`${job.calls_completed}/${job.total_consumers} calls`}
            rightText={job.status}
          />
        ))}
        {!jobs.length ? <Text>No jobs yet.</Text> : null}
      </Card>
      <SecondaryButton title="Refresh" onPress={() => void load()} />
    </Screen>
  );
}

export function KnowledgeScreen() {
  const { sessionHeaders, selectedClient } = useAuth();
  const { canUploadDocuments } = usePermissions();
  const clientEmailId = useSelectedClientEmail();
  const [documents, setDocuments] = useState<DocumentListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async () => {
    if (!clientEmailId) return;
    try {
      const data = await apiRequest<DocumentListResponse>(
        sessionHeaders,
        "v1/mobile/documents",
        undefined,
        buildClientQuery(clientEmailId),
      );
      setDocuments(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load documents");
    }
  }, [clientEmailId, sessionHeaders]);

  useEffect(() => {
    void load();
  }, [load]);

  async function pickAndUpload() {
    if (!clientEmailId) return;
    const result = await DocumentPicker.getDocumentAsync({
      type: ["application/pdf", "text/plain", "text/markdown"],
      multiple: false,
      copyToCacheDirectory: true,
    });
    if (result.canceled) return;
    const asset = result.assets[0];
    setUploading(true);
    try {
      await apiUpload(
        sessionHeaders,
        "v1/mobile/documents",
        { uri: asset.uri, name: asset.name, mimeType: asset.mimeType },
        buildClientQuery(clientEmailId),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload document");
    } finally {
      setUploading(false);
    }
  }

  async function deleteDocument(documentId: string) {
    if (!clientEmailId) return;
    try {
      await apiRequest(
        sessionHeaders,
        `v1/mobile/documents/${encodeURIComponent(documentId)}`,
        { method: "DELETE" },
        buildClientQuery(clientEmailId),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete document");
    }
  }

  return (
    <Screen
      title="Knowledge"
      subtitle={selectedClient ? `Documents for ${selectedClient.client_name}` : "Select a client first."}
    >
      {error ? <Banner kind="error" message={error} /> : null}
      <Card>
        <SectionTitle>Upload document</SectionTitle>
        <Text>Allowed types: PDF, TXT, MD</Text>
        <PrimaryButton
          title={uploading ? "Uploading..." : "Choose file"}
          onPress={() => void pickAndUpload()}
          disabled={!canUploadDocuments || uploading}
        />
        {!canUploadDocuments ? (
          <Banner kind="info" message="Your role can view documents but cannot upload or delete them." />
        ) : null}
      </Card>
      <Card>
        <SectionTitle>Documents</SectionTitle>
        {(documents?.documents ?? []).map((doc) => (
          <View key={doc.document_id}>
            <ListItem
              title={doc.source_uri}
              subtitle={`${doc.chunk_count} chunks | ${doc.document_id}`}
            />
            {canUploadDocuments ? (
              <SecondaryButton title="Delete" onPress={() => void deleteDocument(doc.document_id)} />
            ) : null}
          </View>
        ))}
        {!documents?.documents?.length ? <Text>No documents yet.</Text> : null}
      </Card>
      <SecondaryButton title="Refresh" onPress={() => void load()} />
    </Screen>
  );
}

export function CallHistoryScreen() {
  const { sessionHeaders } = useAuth();
  const clientEmailId = useSelectedClientEmail();
  const [search, setSearch] = useState("");
  const [summaries, setSummaries] = useState<CallSummary[]>([]);
  const [selected, setSelected] = useState<CallSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientEmailId) return;
    try {
      const data = await apiRequest<CallSummaryListResponse>(
        sessionHeaders,
        "v1/mobile/call-summaries",
        undefined,
        { ...buildClientQuery(clientEmailId), limit: 200 },
      );
      setSummaries(data.summaries);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load call history");
    }
  }, [clientEmailId, sessionHeaders]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return summaries;
    return summaries.filter((item) =>
      [item.consumer_phone_number, item.consumer_email_id, item.call_summary]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [search, summaries]);

  return (
    <Screen title="Call history" subtitle="Review completed calls and summaries.">
      {error ? <Banner kind="error" message={error} /> : null}
      <Card>
        <Field label="Search" value={search} onChangeText={setSearch} placeholder="Phone, email, summary" />
        {filtered.map((item) => (
          <ListItem
            key={item.id}
            title={item.consumer_phone_number ?? `Consumer #${item.consumer_id}`}
            subtitle={summaryPreview(item.call_summary)}
            rightText={formatDate(item.call_start_time)}
            onPress={() => setSelected(item)}
          />
        ))}
        {!filtered.length ? <Text>No call summaries yet.</Text> : null}
      </Card>
      {selected ? (
        <Card>
          <SectionTitle>Call details</SectionTitle>
          <Text>{selected.consumer_email_id ?? "No consumer email"}</Text>
          <Text>{formatDate(selected.call_start_time)}</Text>
          <Text>{selected.call_summary}</Text>
        </Card>
      ) : null}
      <SecondaryButton title="Refresh" onPress={() => void load()} />
    </Screen>
  );
}

export function VoiceAgentScreen() {
  const { sessionHeaders, selectedClient } = useAuth();
  const clientEmailId = useSelectedClientEmail();
  const [config, setConfig] = useState<VoiceAgentConfig | null>(null);
  const [language, setLanguage] = useState("hi-IN");
  const [greeting, setGreeting] = useState("");
  const [calcomUsername, setCalcomUsername] = useState("");
  const [eventSlug, setEventSlug] = useState("");
  const [eventTypeId, setEventTypeId] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!clientEmailId) return;
    try {
      const data = await apiRequest<VoiceAgentConfig>(
        sessionHeaders,
        "v1/mobile/voice-agent-config",
        undefined,
        buildClientQuery(clientEmailId),
      );
      setConfig(data);
      setLanguage(data.voice_agent_language);
      setGreeting(data.voice_agent_greeting_message);
      setCalcomUsername(data.calcom_username ?? "");
      setEventSlug(data.calcom_event_type_slug ?? "");
      setEventTypeId(data.calcom_event_type_id ? String(data.calcom_event_type_id) : "");
      setOrgSlug(data.calcom_organization_slug ?? "");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load voice settings");
    }
  }, [clientEmailId, sessionHeaders]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    if (!clientEmailId) return;
    setSaving(true);
    try {
      await apiJson(
        sessionHeaders,
        "v1/mobile/voice-agent-config",
        "PUT",
        {
          voice_agent_language: language,
          voice_agent_greeting_message: greeting,
          calcom_username: calcomUsername || null,
          calcom_event_type_slug: eventSlug || null,
          calcom_event_type_id: eventTypeId ? Number(eventTypeId) : null,
          calcom_organization_slug: orgSlug || null,
        },
        buildClientQuery(clientEmailId),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save voice settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Screen title="Voice agent" subtitle="Configure phone-call behavior and booking settings.">
      {error ? <Banner kind="error" message={error} /> : null}
      <BuyNumberCard clientEmailId={clientEmailId} sessionHeaders={sessionHeaders} />
      <Card>
        <SectionTitle>Client</SectionTitle>
        <StatRow label="Name" value={selectedClient?.client_name ?? "-"} />
        <StatRow
          label="Business phone"
          value={formatPhoneDisplay(selectedClient?.client_business_phone_number)}
        />
      </Card>
      <Card>
        <SectionTitle>Settings</SectionTitle>
        <Field
          label="Language"
          value={language}
          onChangeText={(value) =>
            setLanguage(SUPPORTED_LANGUAGES.includes(value) ? value : "hi-IN")
          }
          placeholder="hi-IN"
        />
        <Field label="Greeting message" value={greeting} onChangeText={setGreeting} multiline />
        <Field label="Cal.com username" value={calcomUsername} onChangeText={setCalcomUsername} />
        <Field label="Event slug" value={eventSlug} onChangeText={setEventSlug} />
        <Field label="Event type ID" value={eventTypeId} onChangeText={setEventTypeId} keyboardType="numeric" />
        <Field label="Organization slug" value={orgSlug} onChangeText={setOrgSlug} />
        <PrimaryButton title={saving ? "Saving..." : "Save settings"} onPress={() => void save()} disabled={saving} />
      </Card>
      {config ? <Banner kind="info" message={`Current language: ${config.voice_agent_language}`} /> : null}
    </Screen>
  );
}

export function ProfileScreen() {
  const { session, userEmail, signOut, sessionHeaders, refreshSession } = useAuth();
  const { isAdmin } = usePermissions();
  const [name, setName] = useState(session?.selected_client?.client_name ?? "");
  const [phone, setPhone] = useState(session?.selected_client?.client_phone_number ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setName(session?.selected_client?.client_name ?? "");
    setPhone(session?.selected_client?.client_phone_number ?? "");
  }, [session?.selected_client?.client_name, session?.selected_client?.client_phone_number]);

  async function saveProfile() {
    setSaving(true);
    try {
      await apiJson(sessionHeaders, "v1/mobile/profile", "PUT", {
        client_name: name,
        client_phone_number: phone || null,
      });
      await refreshSession();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Screen title="Profile" subtitle="Account and client identity information.">
      {error ? <Banner kind="error" message={error} /> : null}
      <Card>
        <SectionTitle>Signed-in user</SectionTitle>
        <StatRow label="Email" value={userEmail ?? "-"} />
        <StatRow label="Role" value={session?.role ?? "-"} />
      </Card>
      {isAdmin ? (
        <Banner kind="info" message="Admin users manage clients from the Admin tab." />
      ) : (
        <>
          <BuyNumberCard
            clientEmailId={session?.selected_client?.client_email_id}
            sessionHeaders={sessionHeaders}
            onPurchased={refreshSession}
          />
          <Card>
          <SectionTitle>Personal information</SectionTitle>
          <Field label="Name" value={name} onChangeText={setName} />
          <Field label="Personal phone" value={phone} onChangeText={setPhone} keyboardType="phone-pad" />
          <Field label="Business phone" value={session?.selected_client?.client_business_phone_number ?? ""} />
          <PrimaryButton title={saving ? "Saving..." : "Save changes"} onPress={() => void saveProfile()} disabled={saving} />
        </Card>
        </>
      )}
      <SecondaryButton title="Sign out" onPress={() => void signOut()} />
    </Screen>
  );
}

export function AdminScreen() {
  const { sessionHeaders, selectClient, selectedClient, refreshSession } = useAuth();
  const { isAdmin } = usePermissions();
  const [clients, setClients] = useState<ClientAdminProfile[]>([]);
  const [pendingPhones, setPendingPhones] = useState<Record<string, string>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResponse | null>(null);
  const [collections, setCollections] = useState<string[]>([]);
  const [collectionDetails, setCollectionDetails] = useState<Record<string, CollectionInfo>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const clientData = await apiRequest<ClientAdminListResponse>(sessionHeaders, "v1/mobile/clients");
      setClients(clientData.clients);
      if (selectedClient?.client_email_id) {
        const collectionData = await apiRequest<CollectionListResponse>(
          sessionHeaders,
          "v1/mobile/collections",
          undefined,
          buildClientQuery(selectedClient.client_email_id),
        );
        setCollections(collectionData.collections);
        const entries = await Promise.all(
          collectionData.collections.map(async (name) => {
            const info = await apiRequest<CollectionInfo>(
              sessionHeaders,
              `v1/mobile/collections/${encodeURIComponent(name)}`,
              undefined,
              buildClientQuery(selectedClient.client_email_id),
            );
            return [name, info] as const;
          }),
        );
        setCollectionDetails(Object.fromEntries(entries));
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load admin data");
    }
  }, [isAdmin, selectedClient?.client_email_id, sessionHeaders]);

  useEffect(() => {
    void load();
  }, [load]);

  async function approveClient(client: ClientAdminProfile) {
    try {
      await apiJson(sessionHeaders, "v1/mobile/clients/approve", "POST", {
        client_email_id: client.client_email_id,
        client_business_phone_number: pendingPhones[client.client_email_id],
      });
      await load();
      await refreshSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve client");
    }
  }

  async function deleteClient(clientEmailId: string) {
    try {
      await apiRequest(sessionHeaders, `v1/mobile/clients/${encodeURIComponent(clientEmailId)}`, {
        method: "DELETE",
      });
      await load();
      await refreshSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete client");
    }
  }

  async function runSearch() {
    if (!selectedClient?.client_email_id || !searchQuery.trim()) return;
    try {
      const data = await apiJson<SearchResponse>(
        sessionHeaders,
        "v1/mobile/search",
        "POST",
        {
          query: searchQuery.trim(),
          client_email_id: selectedClient.client_email_id,
          max_results: 5,
        },
      );
      setSearchResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    }
  }

  async function deleteCollection(name: string) {
    if (!selectedClient?.client_email_id) return;
    try {
      await apiRequest(
        sessionHeaders,
        `v1/mobile/collections/${encodeURIComponent(name)}`,
        { method: "DELETE" },
        buildClientQuery(selectedClient.client_email_id),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete collection");
    }
  }

  if (!isAdmin) {
    return (
      <Screen title="Admin" subtitle="Admin-only tools.">
        <Banner kind="info" message="This area is available to relaydesk-admins only." />
      </Screen>
    );
  }

  return (
    <Screen title="Admin" subtitle="Approve clients, search knowledge, and manage collections.">
      {error ? <Banner kind="error" message={error} /> : null}
      <Card>
        <SectionTitle>Client scope</SectionTitle>
        {clients.map((client) => (
          <ListItem
            key={client.client_email_id}
            title={client.client_name || client.client_email_id}
            subtitle={client.client_email_id}
            rightText={selectedClient?.client_email_id === client.client_email_id ? "Selected" : "Switch"}
            onPress={() => void selectClient(client.client_email_id)}
          />
        ))}
      </Card>
      <Card>
        <SectionTitle>Approve clients</SectionTitle>
        {clients
          .filter((client) => !client.is_approved)
          .map((client) => (
            <View key={client.client_email_id}>
              <ListItem title={client.client_email_id} subtitle={client.client_name || "Pending"} />
              <Field
                label="Business phone"
                value={pendingPhones[client.client_email_id] ?? ""}
                onChangeText={(value) =>
                  setPendingPhones((current) => ({ ...current, [client.client_email_id]: value }))
                }
                keyboardType="phone-pad"
              />
              <PrimaryButton title="Approve client" onPress={() => void approveClient(client)} />
            </View>
          ))}
        {!clients.some((client) => !client.is_approved) ? <Text>No pending clients.</Text> : null}
      </Card>
      <Card>
        <SectionTitle>Semantic search</SectionTitle>
        <Field label="Query" value={searchQuery} onChangeText={setSearchQuery} />
        <PrimaryButton title="Run search" onPress={() => void runSearch()} />
        {(searchResults?.hits ?? []).map((hit, index) => (
          <ListItem
            key={`${hit.source_uri ?? "result"}-${index}`}
            title={hit.source_uri ?? "Result"}
            subtitle={summaryPreview(hit.text, 180)}
            rightText={hit.score.toFixed(3)}
          />
        ))}
      </Card>
      <Card>
        <SectionTitle>Collections</SectionTitle>
        {collections.map((name) => (
          <View key={name}>
            <ListItem
              title={name}
              subtitle={`${collectionDetails[name]?.points_count ?? 0} points | vector ${collectionDetails[name]?.vector_size ?? "-"}`}
            />
            <SecondaryButton title="Delete collection" onPress={() => void deleteCollection(name)} />
          </View>
        ))}
        {!collections.length ? <Text>No collections for the selected client.</Text> : null}
      </Card>
      <Card>
        <SectionTitle>Delete client account</SectionTitle>
        {clients.map((client) => (
          <SecondaryButton
            key={client.client_email_id}
            title={`Delete ${client.client_email_id}`}
            onPress={() =>
              Alert.alert("Delete client", `Delete ${client.client_email_id}?`, [
                { text: "Cancel", style: "cancel" },
                {
                  text: "Delete",
                  style: "destructive",
                  onPress: () => void deleteClient(client.client_email_id),
                },
              ])
            }
          />
        ))}
      </Card>
      <SecondaryButton title="Refresh" onPress={() => void load()} />
    </Screen>
  );
}
