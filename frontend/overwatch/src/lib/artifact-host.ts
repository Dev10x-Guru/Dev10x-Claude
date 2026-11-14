import { createContext } from "svelte";

import type { ControlBlock, ControlState, ControlValue } from "./artifact";

export interface ControlStatus {
  state: ControlState;
  note: string;
}

export interface ControlHost {
  status(controlId: string): ControlStatus;
  send(control: ControlBlock, value: ControlValue): Promise<void>;
  find(controlId: string): ControlBlock | null;
}

export const [getControlHost, setControlHost] = createContext<ControlHost>();
