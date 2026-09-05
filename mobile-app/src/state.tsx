import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { router } from "expo-router";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Platform } from "react-native";

import { apiRequest, runtimeConfig, type SessionHeaders } from "@/api";
import type { ClientAdminProfile, ClientProfile, MobileSession, RelayDeskRole } from "@/types";

const ACCESS_TOKEN_KEY = "relaydesk_mobile_access_token";
const USER_EMAIL_KEY = "relaydesk_mobile_user_email";
const ROLE_KEY = "relaydesk_mobile_role";
const CLIENT_KEY = "relaydesk_mobile_selected_client";

type AuthContextValue = {
  booting: boolean;
  authenticated: boolean;
  session: MobileSession | null;
  accessToken: string | null;
  userEmail: string | null;
  role: RelayDeskRole | null;
  selectedClient: ClientProfile | null;
  clients: ClientAdminProfile[];
  signInLocal: (email: string, role: RelayDeskRole) => Promise<void>;
  signOut: () => Promise<void>;
  refreshSession: (emailOverride?: string | null) => Promise<void>;
  selectClient: (clientEmailId: string) => Promise<void>;
  sessionHeaders: SessionHeaders;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function normalizeEmail(value: string) {
  return value.trim().toLowerCase();
}

async function getStoredAccessToken(): Promise<string | null> {
  if (Platform.OS === "web") {
    if (typeof localStorage === "undefined") {
      return null;
    }
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  }
  if (typeof SecureStore.getItemAsync !== "function") {
    return null;
  }
  return SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
}

async function deleteStoredAccessToken(): Promise<void> {
  if (Platform.OS === "web") {
    if (typeof localStorage !== "undefined") {
      localStorage.removeItem(ACCESS_TOKEN_KEY);
    }
    return;
  }
  if (typeof SecureStore.deleteItemAsync === "function") {
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [booting, setBooting] = useState(true);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [role, setRole] = useState<RelayDeskRole | null>(null);
  const [session, setSession] = useState<MobileSession | null>(null);
  const [selectedClientEmail, setSelectedClientEmail] = useState<string | null>(null);

  const sessionHeaders = useMemo<SessionHeaders>(
    () => ({
      accessToken,
      sessionEmail: runtimeConfig.authDisableSso ? userEmail : null,
      sessionRole: runtimeConfig.authDisableSso ? role : null,
    }),
    [accessToken, role, userEmail],
  );

  const selectClient = useCallback(
    async (clientEmailId: string) => {
      const normalized = normalizeEmail(clientEmailId);
      setSelectedClientEmail(normalized);
      await AsyncStorage.setItem(CLIENT_KEY, normalized);
      await apiRequest<MobileSession>(sessionHeaders, "v1/mobile/me", undefined, {
        selected_client_email_id: normalized,
      }).then(setSession);
    },
    [sessionHeaders],
  );

  const refreshSession = useCallback(
    async (emailOverride?: string | null) => {
      const activeEmail = emailOverride ?? selectedClientEmail ?? undefined;
      const data = await apiRequest<MobileSession>(sessionHeaders, "v1/mobile/me", undefined, {
        selected_client_email_id: activeEmail,
      });
      setSession(data);
      if (data.selected_client?.client_email_id) {
        const normalized = normalizeEmail(data.selected_client.client_email_id);
        setSelectedClientEmail(normalized);
        await AsyncStorage.setItem(CLIENT_KEY, normalized);
      }
    },
    [selectedClientEmail, sessionHeaders],
  );

  const signInLocal = useCallback(async (email: string, nextRole: RelayDeskRole) => {
    const normalizedEmail = normalizeEmail(email);
    setAccessToken(null);
    setUserEmail(normalizedEmail);
    setRole(nextRole);
    await Promise.all([
      AsyncStorage.setItem(USER_EMAIL_KEY, normalizedEmail),
      AsyncStorage.setItem(ROLE_KEY, nextRole),
    ]);
    await deleteStoredAccessToken();
    const nextSession = await apiRequest<MobileSession>(
      {
        accessToken: null,
        sessionEmail: normalizedEmail,
        sessionRole: nextRole,
      },
      "v1/mobile/me",
    );
    setSession(nextSession);
    router.replace("/");
  }, []);

  const signOut = useCallback(async () => {
    setAccessToken(null);
    setUserEmail(null);
    setRole(null);
    setSession(null);
    setSelectedClientEmail(null);
    await deleteStoredAccessToken();
    await Promise.all([
      AsyncStorage.removeItem(USER_EMAIL_KEY),
      AsyncStorage.removeItem(ROLE_KEY),
      AsyncStorage.removeItem(CLIENT_KEY),
    ]);
    router.replace("/login");
  }, []);

  useEffect(() => {
    async function bootstrap() {
      const [storedEmail, storedRole, storedClient] = await Promise.all([
        AsyncStorage.getItem(USER_EMAIL_KEY),
        AsyncStorage.getItem(ROLE_KEY),
        AsyncStorage.getItem(CLIENT_KEY),
      ]);
      const token = await getStoredAccessToken();
      const email = storedEmail;
      const savedRole = storedRole as RelayDeskRole | null;
      const clientEmail = storedClient;

      setAccessToken(token);
      setUserEmail(email);
      setRole(savedRole);
      setSelectedClientEmail(clientEmail);

      if (token || (runtimeConfig.authDisableSso && email && savedRole)) {
        try {
          await apiRequest<MobileSession>(
            {
              accessToken: token,
              sessionEmail: runtimeConfig.authDisableSso ? email : null,
              sessionRole: runtimeConfig.authDisableSso ? savedRole : null,
            },
            "v1/mobile/me",
            undefined,
            { selected_client_email_id: clientEmail ?? undefined },
          ).then(setSession);
        } catch {
          await deleteStoredAccessToken();
          await Promise.all([
            AsyncStorage.removeItem(USER_EMAIL_KEY),
            AsyncStorage.removeItem(ROLE_KEY),
            AsyncStorage.removeItem(CLIENT_KEY),
          ]);
        }
      }

      setBooting(false);
    }

    void bootstrap();
  }, []);

  const value = useMemo<AuthContextValue>(() => {
    const clients = session?.clients ?? [];
    const selectedClient =
      session?.selected_client ??
      clients.find((item) => item.client_email_id === selectedClientEmail) ??
      null;

    return {
      booting,
      authenticated: Boolean(session),
      session,
      accessToken,
      userEmail,
      role,
      selectedClient,
      clients,
      signInLocal,
      signOut,
      refreshSession,
      selectClient,
      sessionHeaders,
    };
  }, [
    accessToken,
    booting,
    refreshSession,
    role,
    selectedClientEmail,
    session,
    sessionHeaders,
    signInLocal,
    signOut,
    selectClient,
    userEmail,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}

export function usePermissions() {
  const { session } = useAuth();
  return {
    role: session?.role ?? null,
    isAdmin: session?.is_admin ?? false,
    isGuest: session?.is_guest ?? true,
    canUploadDocuments: session?.can_upload_documents ?? false,
    canManageData: session?.can_manage_data ?? false,
    canManageOwnConsumers: session?.can_upload_documents ?? false,
  };
}
