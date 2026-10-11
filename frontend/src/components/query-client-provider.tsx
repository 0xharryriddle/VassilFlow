"use client";

import {
  QueryClient,
  QueryClientProvider as TanStackQueryClientProvider,
} from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useAuth } from "@/core/auth/AuthProvider";

export function QueryClientProvider({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const { user } = useAuth();
  // A changed account replaces the entire cache before descendants render.
  // Unmounting the workspace also discards the previous session's cache.
  return (
    <AccountQueryClientProvider key={user?.id ?? "anonymous"}>
      {children}
    </AccountQueryClientProvider>
  );
}

function AccountQueryClientProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [queryClient] = useState(() => new QueryClient());
  useEffect(() => () => queryClient.clear(), [queryClient]);

  return (
    <TanStackQueryClientProvider client={queryClient}>
      {children}
    </TanStackQueryClientProvider>
  );
}
