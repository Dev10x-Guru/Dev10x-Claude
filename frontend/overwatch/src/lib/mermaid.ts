let counter = 0;

export async function renderMermaid(source: string, dark: boolean): Promise<string> {
  const { default: mermaid } = await import("mermaid");
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" });
  counter += 1;
  const id = `overwatch-mermaid-${counter}`;
  try {
    const { svg } = await mermaid.render(id, source);
    return svg;
  } finally {
    document.getElementById(id)?.remove();
    document.getElementById(`d${id}`)?.remove();
  }
}
