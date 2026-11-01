// Validate a BPMN 2.0 file and, when it has no diagram interchange (DI),
// add coordinates so modelers and renderers can draw it. Hand-written DI
// is the failure this exists to remove.
//
// Usage: node layout.mjs <deps-dir> <file.bpmn> [--relayout]
// Exit 1 with every problem on stderr when the model cannot be laid out.

import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { arrangeLanes, unassignedNodes } from "./lanes.mjs";

const [depsDir, source, flag] = process.argv.slice(2);
if (!depsDir || !source) {
  console.error("Usage: node layout.mjs <deps-dir> <file.bpmn> [--relayout]");
  process.exit(2);
}

const fail = (problems) => {
  for (const problem of problems) {
    console.error(`ERROR: ${problem}`);
  }
  console.error(`ERROR: ${source} cannot be laid out (${problems.length} problem(s))`);
  process.exit(1);
};

// Resolve from the cache dir, not from this script's location: the
// toolchain is installed there once by render.sh. Both packages expose
// these as named exports at the versions pinned in package.json.
const require = createRequire(join(depsDir, "package.json"));
const load = async (name) => import(pathToFileURL(require.resolve(name)).href);

const { BpmnModdle } = await load("bpmn-moddle");

// bpmn-auto-layout walks the graph through each node's incoming /
// outgoing refs, not through the sequenceFlow list. Deriving them from
// the flows means an author never has to keep both sides in sync.
const linkFlows = (definitions) => {
  for (const process of definitions.rootElements ?? []) {
    for (const flow of process.flowElements ?? []) {
      if (flow.$type !== "bpmn:SequenceFlow") continue;
      const outgoing = (flow.sourceRef.outgoing ??= []);
      const incoming = (flow.targetRef.incoming ??= []);
      if (!outgoing.includes(flow)) outgoing.push(flow);
      if (!incoming.includes(flow)) incoming.push(flow);
    }
  }
};

const byType = (definitions, type) =>
  (definitions.rootElements ?? []).filter((element) => element.$type === type);
const lanesOf = (process) => process.laneSets?.[0]?.lanes ?? [];
const laneIndex = (lanes) =>
  new Map(lanes.flatMap((lane) => (lane.flowNodeRef ?? []).map((node) => [node.id, lane.id])));
const flowNodesOf = (process) =>
  (process.flowElements ?? []).filter((element) => element.$instanceOf("bpmn:FlowNode"));

const moddle = new BpmnModdle();
let parsed;
try {
  parsed = await moddle.fromXML(await readFile(source, "utf8"));
} catch (error) {
  fail([error.message]);
}
const { rootElement, warnings } = parsed;
if (warnings.length > 0) {
  fail(warnings.map((warning) => warning.message));
}

// Model checks run before the keep-existing-layout exit, so a file tuned
// in a modeler is held to the same rules as one this script lays out.
// More than one pool stops here; every later check assumes one process.
const [collaboration] = byType(rootElement, "bpmn:Collaboration");
const participants = collaboration?.participants ?? [];
if (participants.length > 1 || (collaboration?.messageFlows ?? []).length > 0) {
  fail(["only a single pool is laid out; split each pool into its own file"]);
}

const problems = [];
const processes = byType(rootElement, "bpmn:Process");
if (participants.length === 0 && processes.some((process) => lanesOf(process).length > 0)) {
  problems.push("lanes need a pool: wrap the process in a collaboration participant");
}
for (const process of processes) {
  const nodes = flowNodesOf(process);
  if (nodes.length === 0) {
    problems.push(`${process.id} has no flow nodes to lay out; add a start event`);
  }
  const lanes = lanesOf(process);
  if (lanes.length === 0) continue;
  const laneOf = laneIndex(lanes);
  const missing = unassignedNodes({
    lanes,
    nodes: nodes.map((node) => ({ id: node.id, lane: laneOf.get(node.id) })),
  });
  problems.push(...missing.map((id) => `${id} is in no lane; add it to one lane's flowNodeRef`));
}
if (problems.length > 0) {
  fail(problems);
}

if ((rootElement.diagrams ?? []).length > 0 && flag !== "--relayout") {
  console.error(`kept existing layout in ${source} (pass --relayout to regenerate)`);
  process.exit(0);
}

// Loaded only once validation has passed: no exit above needs it.
const { layoutProcess } = await load("bpmn-auto-layout");
linkFlows(rootElement);
const { xml: linked } = await moddle.toXML(rootElement, { format: true });
const laidOut = await layoutProcess(linked);

if (participants.length === 0) {
  await writeFile(source, laidOut);
  console.error(`laid out ${source}`);
  process.exit(0);
}

// One pool: re-band the auto-layout result into the pool and its lanes.
// A pool without lanes is laid out as one implicit lane named after it.
const { rootElement: result } = await moddle.fromXML(laidOut);
const [laidOutCollaboration] = byType(result, "bpmn:Collaboration");
const [pool] = laidOutCollaboration.participants;
const declaredLanes = lanesOf(pool.processRef);
const hasLanes = declaredLanes.length > 0;
const lanes = hasLanes ? declaredLanes : [{ id: pool.id }];
const laneOf = laneIndex(declaredLanes);

const plane = result.diagrams[0].plane;
const shapes = plane.planeElement.filter((element) => element.$type === "bpmndi:BPMNShape");
const diEdges = plane.planeElement.filter((element) => element.$type === "bpmndi:BPMNEdge");

const geometry = arrangeLanes({
  lanes,
  nodes: shapes.map((shape) => ({
    id: shape.bpmnElement.id,
    lane: hasLanes ? laneOf.get(shape.bpmnElement.id) : pool.id,
    x: shape.bounds.x,
    y: shape.bounds.y,
    width: shape.bounds.width,
    height: shape.bounds.height,
  })),
  edges: diEdges.map((edge) => ({
    id: edge.bpmnElement.id,
    source: edge.bpmnElement.sourceRef.id,
    target: edge.bpmnElement.targetRef.id,
  })),
});

const bounds = (box) =>
  moddle.create("dc:Bounds", { x: box.x, y: box.y, width: box.width, height: box.height });
const placed = new Map(geometry.nodes.map((node) => [node.id, node]));
for (const shape of shapes) {
  shape.bounds = bounds(placed.get(shape.bpmnElement.id));
}
const routed = new Map(geometry.edges.map((edge) => [edge.id, edge.waypoints]));
for (const edge of diEdges) {
  edge.waypoint = routed
    .get(edge.bpmnElement.id)
    .map((point) => moddle.create("dc:Point", point));
}

const header = (element, box) =>
  moddle.create("bpmndi:BPMNShape", {
    id: `${element.id}_di`,
    bpmnElement: element,
    isHorizontal: true,
    bounds: bounds(box),
  });
const laneShapes = declaredLanes.map((lane, index) => header(lane, geometry.lanes[index]));

plane.bpmnElement = laidOutCollaboration;
plane.planeElement = [header(pool, geometry.pool), ...laneShapes, ...shapes, ...diEdges];

const { xml } = await moddle.toXML(result, { format: true });
await writeFile(source, xml);
console.error(`laid out ${source} with ${declaredLanes.length} lane(s)`);
