import { Redirect } from "expo-router";

import { LoginScreen } from "@/screens";
import { useAuth } from "@/state";

export default function LoginRoute() {
  const { authenticated } = useAuth();
  if (authenticated) {
    return <Redirect href="/" />;
  }
  return <LoginScreen />;
}
