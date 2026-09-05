import { Redirect, Tabs } from "expo-router";

import { useAuth, usePermissions } from "@/state";

export default function TabsLayout() {
  const { authenticated, booting } = useAuth();
  const { canManageData } = usePermissions();

  if (booting) {
    return null;
  }
  if (!authenticated) {
    return <Redirect href="/login" />;
  }

  return (
    <Tabs screenOptions={{ headerShown: false }}>
      <Tabs.Screen name="index" options={{ title: "Dashboard" }} />
      <Tabs.Screen name="consumers" options={{ title: "Consumers" }} />
      <Tabs.Screen name="campaigns" options={{ title: "Campaigns" }} />
      <Tabs.Screen name="knowledge" options={{ title: "Knowledge" }} />
      <Tabs.Screen name="call-history" options={{ title: "Calls" }} />
      <Tabs.Screen name="voice-agent" options={{ title: "Agent" }} />
      <Tabs.Screen name="profile" options={{ title: "Profile" }} />
      <Tabs.Screen
        name="admin"
        options={{ title: "Admin", href: canManageData ? undefined : null }}
      />
    </Tabs>
  );
}
