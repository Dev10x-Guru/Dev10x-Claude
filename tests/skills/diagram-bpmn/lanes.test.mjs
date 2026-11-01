// Unit tests for skills/diagram-bpmn/scripts/lanes.mjs (GH-1637).
// Pure geometry, so these run on bare Node with no npm toolchain.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  LANE_PADDING,
  POOL_HEADER,
  ROW_HEIGHT,
  arrangeLanes,
  route,
  unassignedNodes,
} from "../../../skills/diagram-bpmn/scripts/lanes.mjs";

const task = (id, lane, x, y) => ({ id, lane, x, y, width: 100, height: 80 });
const centerY = (node) => node.y + node.height / 2;

describe("unassignedNodes", () => {
  test("names nodes whose lane is not declared", () => {
    const result = unassignedNodes({
      lanes: [{ id: "A" }],
      nodes: [task("t1", "A", 0, 0), task("t2", undefined, 0, 0)],
    });
    assert.deepEqual(result, ["t2"]);
  });

  test("is empty when every node has a declared lane", () => {
    const result = unassignedNodes({ lanes: [{ id: "A" }], nodes: [task("t1", "A", 0, 0)] });
    assert.deepEqual(result, []);
  });
});

describe("route", () => {
  const source = task("s", "A", 0, 0);

  test("same row forward is one straight segment", () => {
    const points = route({ source, target: task("t", "A", 200, 0) });
    assert.deepEqual(points, [
      { x: 100, y: 40 },
      { x: 200, y: 40 },
    ]);
  });

  test("forward to a lower row leaves through the bottom", () => {
    const points = route({ source, target: task("t", "A", 200, 140) });
    assert.deepEqual(points, [
      { x: 50, y: 80 },
      { x: 50, y: 180 },
      { x: 200, y: 180 },
    ]);
  });

  test("forward to a higher row leaves through the top", () => {
    const points = route({ source: task("s", "A", 0, 140), target: task("t", "A", 200, 0) });
    assert.deepEqual(points, [
      { x: 50, y: 140 },
      { x: 50, y: 40 },
      { x: 200, y: 40 },
    ]);
  });

  test("a target touching the source's right edge on another row is forward", () => {
    const points = route({ source, target: task("t", "B", 100, 180) });
    assert.deepEqual(points, [
      { x: 50, y: 80 },
      { x: 50, y: 220 },
      { x: 100, y: 220 },
    ]);
  });

  test("same column below is one straight drop", () => {
    const points = route({ source, target: task("t", "B", 0, 180) });
    assert.deepEqual(points, [
      { x: 50, y: 80 },
      { x: 50, y: 180 },
    ]);
  });

  test("same column above is one straight climb", () => {
    const points = route({ source: task("s", "B", 0, 180), target: task("t", "A", 0, 0) });
    assert.deepEqual(points, [
      { x: 50, y: 180 },
      { x: 50, y: 80 },
    ]);
  });

  test("loop-back to a lower row runs under both nodes", () => {
    const points = route({ source: task("s", "A", 300, 0), target: task("t", "B", 0, 140) });
    assert.deepEqual(points, [
      { x: 350, y: 80 },
      { x: 350, y: 220 + LANE_PADDING / 2 },
      { x: 50, y: 220 + LANE_PADDING / 2 },
      { x: 50, y: 220 },
    ]);
  });

  test("loop-back to the same row runs under both nodes", () => {
    const points = route({ source: task("s", "A", 300, 0), target: task("t", "A", 0, 0) });
    assert.deepEqual(points, [
      { x: 350, y: 80 },
      { x: 350, y: 80 + LANE_PADDING / 2 },
      { x: 50, y: 80 + LANE_PADDING / 2 },
      { x: 50, y: 80 },
    ]);
  });

  test("loop-back to a higher row climbs out of the source top", () => {
    const points = route({ source: task("s", "B", 300, 200), target: task("t", "A", 0, 0) });
    assert.deepEqual(points, [
      { x: 350, y: 200 },
      { x: 350, y: 80 + LANE_PADDING },
      { x: 50, y: 80 + LANE_PADDING },
      { x: 50, y: 80 },
    ]);
  });
});

describe("arrangeLanes", () => {
  const lanes = [{ id: "Author" }, { id: "Reviewer" }];
  const nodes = [
    task("open", "Author", 25, 30),
    task("fix", "Author", 175, 30),
    task("review", "Reviewer", 175, 170),
  ];
  const edges = [
    { id: "f1", source: "open", target: "fix" },
    { id: "f2", source: "fix", target: "review" },
  ];
  const result = arrangeLanes({ lanes, nodes, edges });
  const placed = Object.fromEntries(result.nodes.map((node) => [node.id, node]));

  test("stacks one band per lane, each one row tall", () => {
    const bandHeight = ROW_HEIGHT + 2 * LANE_PADDING;
    assert.deepEqual(
      result.lanes.map((lane) => [lane.id, lane.y, lane.height]),
      [
        ["Author", 0, bandHeight],
        ["Reviewer", bandHeight, bandHeight],
      ],
    );
  });

  test("puts each node inside its own lane band", () => {
    const [author, reviewer] = result.lanes;
    const inBand = (node, band) =>
      node.y >= band.y && node.y + node.height <= band.y + band.height;
    assert.deepEqual(
      [inBand(placed.open, author), inBand(placed.fix, author), inBand(placed.review, reviewer)],
      [true, true, true],
    );
  });

  test("keeps auto-layout columns", () => {
    assert.equal(placed.fix.x - placed.open.x, 150);
  });

  test("lane shapes start after the pool header and span the pool", () => {
    assert.deepEqual(
      result.lanes.map((lane) => [lane.x, lane.width]),
      [
        [POOL_HEADER, result.pool.width - POOL_HEADER],
        [POOL_HEADER, result.pool.width - POOL_HEADER],
      ],
    );
  });

  test("pool covers every lane", () => {
    assert.equal(result.pool.height, result.lanes.reduce((sum, lane) => sum + lane.height, 0));
  });

  test("routes the same-lane edge straight across", () => {
    const f1 = result.edges.find((edge) => edge.id === "f1").waypoints;
    assert.deepEqual(f1, [
      { x: placed.open.x + placed.open.width, y: centerY(placed.open) },
      { x: placed.fix.x, y: centerY(placed.fix) },
    ]);
  });

  test("routes the cross-lane edge in a shared column as a straight drop", () => {
    const f2 = result.edges.find((edge) => edge.id === "f2").waypoints;
    const x = placed.fix.x + placed.fix.width / 2;
    assert.deepEqual(f2, [
      { x, y: placed.fix.y + placed.fix.height },
      { x, y: placed.review.y },
    ]);
  });

  test("a declared lane with no members still gets a one-row band", () => {
    const sparse = arrangeLanes({
      lanes: [{ id: "A" }, { id: "Empty" }],
      nodes: [task("a", "A", 0, 0)],
      edges: [],
    });
    assert.deepEqual(
      sparse.lanes.map((lane) => [lane.id, lane.height]),
      [
        ["A", ROW_HEIGHT + 2 * LANE_PADDING],
        ["Empty", ROW_HEIGHT + 2 * LANE_PADDING],
      ],
    );
  });

  test("a lane with two rows grows by one row", () => {
    const tall = arrangeLanes({
      lanes: [{ id: "A" }],
      nodes: [task("a", "A", 0, 0), task("b", "A", 0, 140)],
      edges: [],
    });
    assert.equal(tall.lanes[0].height, 2 * ROW_HEIGHT + 2 * LANE_PADDING);
  });
});
