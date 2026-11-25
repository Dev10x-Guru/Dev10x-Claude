import { mermaidConfig, type DiagramPalette } from "./diagram-theme";

let counter = 0;

export async function renderMermaid(
  source: string,
  palette: DiagramPalette,
  dark: boolean,
): Promise<string> {
  const { default: mermaid } = await import("mermaid");
  mermaid.initialize(mermaidConfig(palette, dark));
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
