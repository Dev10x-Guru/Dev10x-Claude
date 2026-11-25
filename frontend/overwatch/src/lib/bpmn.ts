import type { BpmnColors } from "./diagram-theme";

interface Canvas {
  zoom(level: "fit-viewport", center?: "auto"): number;
}

export async function renderBpmn(
  container: HTMLElement,
  xml: string,
  colors: BpmnColors,
): Promise<() => void> {
  const [{ default: Viewer }] = await Promise.all([
    import("bpmn-js/lib/Viewer"),
    import("bpmn-js/dist/assets/diagram-js.css"),
    import("bpmn-js/dist/assets/bpmn-js.css"),
  ]);
  const viewer = new Viewer({ container, bpmnRenderer: colors });
  try {
    await viewer.importXML(xml);
    viewer.get<Canvas>("canvas").zoom("fit-viewport", "auto");
  } catch (error) {
    viewer.destroy();
    throw error;
  }
  return () => viewer.destroy();
}
