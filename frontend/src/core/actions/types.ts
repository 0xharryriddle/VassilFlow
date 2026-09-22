export type ActionStatus =
  | "running"
  | "succeeded"
  | "rejected"
  | "failed"
  | "partial";

export type ActionReference = {
  kind: string;
  id: string;
  role: string | null;
};

export type ActionArtifactIdentity = {
  sha256: string;
  size_bytes: number;
};

export type ProvenanceAction = {
  schema: "vassilflow.action.v1";
  action_id: string;
  owner_user_id: string;
  operation: string;
  source: "agent_run" | "user_api";
  assistant_id: string | null;
  thread_id: string | null;
  run_id: string | null;
  started_at: string;
  completed_at: string | null;
  status: ActionStatus;
  references: ActionReference[];
  before_artifact: ActionArtifactIdentity | null;
  after_artifact: ActionArtifactIdentity | null;
  evidence: ActionReference[];
  error: {
    type: string;
    message: string;
  } | null;
  metadata: Record<string, unknown>;
};

export type ActionsResponse = {
  actions: ProvenanceAction[];
};
