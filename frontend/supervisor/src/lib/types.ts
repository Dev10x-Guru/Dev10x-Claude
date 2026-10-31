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

export interface SessionDetail {
  session_id: string;
  conversation: ConversationEntry[];
  tail: string;
  preview: ToolCallPreview | null;
  recent: RecentTool[];
}

export interface Snapshot {
  version: number;
  taken_at: string;
  errors: Record<string, string>;
  sessions: Session[];
}

export interface ActionResult {
  ok: boolean;
  error?: string;
  sent?: string;
  channel?: string;
  commands?: number;
}
