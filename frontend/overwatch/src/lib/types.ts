export type Group = "needs-you" | "working" | "done";

export type View = "transcript" | "screen";

export interface PromptOption {
  key: string;
  label: string;
  detail: string;
  selected: boolean;
}

export interface Prompt {
  question: string;
  options: PromptOption[];
  context: string[];
  option_preview?: string[];
}

export interface ToolCallPreview {
  tool: string;
  title: string;
  kind: "diff" | "command" | "text";
  body: string;
  truncated: boolean;
}

export interface Decision {
  decision_id: string;
  session_id: string;
  question: string;
  header: string;
  options: string[];
  multi_select: boolean;
  created: string;
  held_until?: string;
  held_elsewhere_until?: string;
}

export interface Session {
  session_id: string;
  name: string;
  cwd: string;
  status: string;
  waiting_for: string;
  pane_id: string;
  callsign: string;
  summary: string;
  board_state: string;
  group: Group;
  prompt: Prompt | null;
  preview: ToolCallPreview | null;
  excerpt: string;
  status_line: string;
  status_line_ansi: string;
  workspace: Workspace;
  decisions: Decision[];
}

export interface Workspace {
  project: string;
  root: string;
  branch: string;
  issue: string;
  repo_url: string;
  issue_url: string;
  pr: string;
  pr_url: string;
}

export interface RecentTool {
  tool: string;
  target: string;
  outcome: "ran" | "failed" | "rejected" | "pending";
  command: string;
  decided_by: string;
}

export interface ProjectCheckout {
  path: string;
  branch: string;
  is_main: boolean;
  open: boolean;
}

export interface PastSession {
  session_id: string;
  cwd: string;
  title: string;
  topic: string;
  active_at: string;
  named: boolean;
}

export interface ProjectDetail {
  root: string;
  name: string;
  checkouts: ProjectCheckout[];
  past: PastSession[];
}

export interface ConversationEntry {
  role: "user" | "assistant";
  kind: "text" | "tool";
  text: string;
  at: string;
  tool: string;
  outcome: "" | RecentTool["outcome"];
  result: string;
}

export interface SessionTask {
  id: string;
  subject: string;
  status: "pending" | "in_progress" | "completed" | string;
  active_form: string;
}

export interface SessionDetail {
  session_id: string;
  conversation: ConversationEntry[];
  tasks: SessionTask[];
  tail: string;
  preview: ToolCallPreview | null;
  recent: RecentTool[];
}

export interface PageSettings {
  answer_wait_seconds: number;
}

export interface Snapshot {
  version: number;
  taken_at: string;
  errors: Record<string, string>;
  sessions: Session[];
  settings?: PageSettings;
  artifacts?: ArtifactSummary[];
}

export interface ActionResult {
  ok: boolean;
  error?: string;
  sent?: string;
  channel?: string;
  commands?: number;
  event_id?: string;
}

export type Tone = "ok" | "warn" | "bad" | "info";

export interface ArtifactSummary {
  id: string;
  title: string;
  session: string;
  revision: number;
  updated_at: string;
}

export interface FormField {
  name: string;
  label: string;
  kind?: "text" | "textarea";
  required?: boolean;
}

export type ArtifactBlock = { id?: string } & (
  | { type: "summary"; title?: string; text: string }
  | { type: "claim"; text: string; tone?: Tone }
  | { type: "decisions"; title?: string; items: { question: string; owner?: string; status?: string; tone?: Tone }[] }
  | { type: "kv"; title?: string; items: { key: string; value: string }[] }
  | { type: "table"; title?: string; columns: string[]; rows: string[][] }
  | { type: "pills"; items: { label: string; tone: Tone }[] }
  | { type: "stats"; title?: string; items: { label: string; value: string; tone?: Tone }[] }
  | { type: "draft"; title?: string; text: string }
  | { type: "evidence"; title?: string; items: { claim: string; source: string; checked?: string }[] }
  | ArtifactControl
);

export type ArtifactControl = { id: string } & (
  | { type: "button"; label: string; tone?: Tone }
  | { type: "choice"; prompt: string; options: string[]; multiple?: boolean }
  | { type: "form"; title?: string; fields: FormField[]; submit?: string }
);

export interface ArtifactDocument extends ArtifactSummary {
  blocks: ArtifactBlock[];
}
