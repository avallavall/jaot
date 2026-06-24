
// LLM Feature Types
// TypeScript types for formulation, SSE events, chat messages

export interface FormulationVariable {
  name: string;
  type: "continuous" | "integer" | "binary";
  lower_bound: number | null;
  upper_bound: number | null;
  description: string;
}

export interface FormulationConstraint {
  name: string;
  expression: string;
  description: string;
}

export interface FormulationObjective {
  sense: "minimize" | "maximize";
  expression: string;
  description: string;
}

export interface Formulation {
  summary: string;
  variables: FormulationVariable[];
  constraints: FormulationConstraint[];
  objective: FormulationObjective;
  problem_name: string;
}

export interface ValidationError {
  field: "variable" | "constraint" | "objective";
  index: number | null;
  message: string;
  suggestion: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  formulation_json: Formulation | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  created_at: string;
  expires_at: string;
  messages: ChatMessage[];
  current_formulation: Formulation | null;
  model_id: string | null;
}

export type SSEEventType = "delta" | "formulation" | "validation_errors" | "done" | "error" | "status" | "partial_result";

export interface SSEEvent {
  event: SSEEventType;
  data: string;
}

export interface AttachmentInfo {
  id: string;
  filename: string;
  mime_type: string;
  char_count: number;
  preview: string;
  created_at: string;
  estimated_tokens: number;
}
