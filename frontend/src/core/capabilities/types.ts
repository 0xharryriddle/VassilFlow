export const CAPABILITY_INPUT_SCHEMA =
  "vassilflow.capability_input.v1" as const;

export interface CapabilityInputEnvelope<TPayload = Record<string, unknown>> {
  schema: typeof CAPABILITY_INPUT_SCHEMA;
  capability: string;
  kind: string;
  payload: TPayload;
}
