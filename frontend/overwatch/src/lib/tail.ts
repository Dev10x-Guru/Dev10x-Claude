import type { Attachment } from "svelte/attachments";

export function pinned(content: string, following: boolean): Attachment<HTMLElement> {
  return (node) => {
    if (content !== undefined && following) node.scrollTop = node.scrollHeight;
  };
}

export function tail(content: string): Attachment<HTMLElement> {
  return (node) => {
    const pin = (): void => {
      node.scrollTop = node.scrollHeight;
    };
    if (content !== undefined) pin();
    const details = node.closest("details");
    details?.addEventListener("toggle", pin);
    return () => details?.removeEventListener("toggle", pin);
  };
}
