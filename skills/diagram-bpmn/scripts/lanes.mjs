// Pool and lane geometry for a single-pool BPMN diagram.
//
// bpmn-auto-layout places flow nodes and edges but draws no pool or
// lane shapes. This module takes its node positions, keeps each node's
// column (x), bands nodes into their lane's rows (y), and returns pool,
// lane, node and edge geometry. It is pure data in, data out — no
// bpmn-moddle — so it is testable without the rendering toolchain.

export const ROW_HEIGHT = 140;
export const POOL_HEADER = 30;
const LANE_HEADER = 30;
export const LANE_PADDING = 20;
const MARGIN = 50;

const right = (node) => node.x + node.width;
const bottom = (node) => node.y + node.height;
const centerX = (node) => node.x + node.width / 2;
const centerY = (node) => node.y + node.height / 2;

export function unassignedNodes({ lanes, nodes }) {
  const laneIds = new Set(lanes.map((lane) => lane.id));
  return nodes.filter((node) => !laneIds.has(node.lane)).map((node) => node.id);
}

// Three cases: nodes sharing a column, forward edges, and loop-backs.
export function route({ source, target }) {
  const dy = centerY(target) - centerY(source);

  // Same column (spans overlap): a straight vertical drop or climb, at
  // the middle of the overlap so it lands on both nodes.
  if (dy !== 0 && target.x < right(source) && right(target) > source.x) {
    const x = (Math.max(source.x, target.x) + Math.min(right(source), right(target))) / 2;
    return dy > 0
      ? [
          { x, y: bottom(source) },
          { x, y: target.y },
        ]
      : [
          { x, y: source.y },
          { x, y: bottom(target) },
        ];
  }

  // Forward (target starts at or right of the source's right edge).
  if (target.x >= right(source)) {
    if (dy === 0) {
      return [
        { x: right(source), y: centerY(source) },
        { x: target.x, y: centerY(target) },
      ];
    }
    // Leave through the top or bottom so a gateway's second branch never
    // shares the right-hand exit with its first.
    return [
      { x: centerX(source), y: dy > 0 ? bottom(source) : source.y },
      { x: centerX(source), y: centerY(target) },
      { x: target.x, y: centerY(target) },
    ];
  }

  // Loop-back, entering the target from below. To a target above, climb
  // out of the source's top and cross just under the target, so the edge
  // never passes through nodes in the lanes between; otherwise run
  // through the padding under both nodes.
  const channel =
    dy < 0
      ? bottom(target) + LANE_PADDING
      : Math.max(bottom(source), bottom(target)) + LANE_PADDING / 2;
  return [
    { x: centerX(source), y: dy < 0 ? source.y : bottom(source) },
    { x: centerX(source), y: channel },
    { x: centerX(target), y: channel },
    { x: centerX(target), y: bottom(target) },
  ];
}

export function arrangeLanes({ lanes, nodes, edges }) {
  const offsetX = MARGIN + POOL_HEADER + LANE_HEADER - Math.min(...nodes.map((node) => node.x));
  const placed = new Map();
  const laneBands = [];
  let top = 0;

  for (const lane of lanes) {
    const members = nodes.filter((node) => node.lane === lane.id);
    const rows = [...new Set(members.map(centerY))].sort((a, b) => a - b);
    const height = Math.max(rows.length, 1) * ROW_HEIGHT + 2 * LANE_PADDING;
    for (const node of members) {
      const row = rows.indexOf(centerY(node));
      const middle = top + LANE_PADDING + row * ROW_HEIGHT + ROW_HEIGHT / 2;
      placed.set(node.id, { ...node, x: node.x + offsetX, y: middle - node.height / 2 });
    }
    laneBands.push({ id: lane.id, top, height });
    top += height;
  }

  const width = Math.max(...[...placed.values()].map(right)) + MARGIN;
  return {
    pool: { x: 0, y: 0, width, height: top },
    lanes: laneBands.map((band) => ({
      id: band.id,
      x: POOL_HEADER,
      y: band.top,
      width: width - POOL_HEADER,
      height: band.height,
    })),
    nodes: [...placed.values()],
    edges: edges.map((edge) => ({
      id: edge.id,
      waypoints: route({ source: placed.get(edge.source), target: placed.get(edge.target) }),
    })),
  };
}
