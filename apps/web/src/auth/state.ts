import type { components } from "../api/schema";

export type Identity = {
  id: string;
  email: string;
};

export type TaskSummary = components["schemas"]["TaskSummary"];

export type SignedOutState =
  | { screen: "email"; email: string; busy: boolean; message: string | null }
  | { screen: "otp"; email: string; otp: string; busy: boolean; message: string | null };

export type AuthViewState =
  | { screen: "checking" }
  | SignedOutState
  | { screen: "workspace"; identity: Identity; tasks: TaskSummary[]; accessToken: string };
