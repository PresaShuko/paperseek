import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

import type { CitationEdge, CitationNode } from "../../api/types";

export interface LayoutPoint {
  x: number;
  y: number;
}

export const GRAPH_WIDTH = 640;
export const GRAPH_HEIGHT = 460;

// Fit the viewport to node positions without changing the force layout or drags.
export function fitCitationViewport(points: LayoutPoint[]): { zoom: number; x: number; y: number } {
  if (!points.length) return { zoom: 1, x: 0, y: 0 };
  const minX = Math.min(...points.map(point => point.x)) - 40;
  const maxX = Math.max(...points.map(point => point.x)) + 40;
  const minY = Math.min(...points.map(point => point.y)) - 40;
  const maxY = Math.max(...points.map(point => point.y)) + 40;
  const zoom = Math.min(1, GRAPH_WIDTH / (maxX - minX), GRAPH_HEIGHT / (maxY - minY));
  return {
    zoom,
    x: (GRAPH_WIDTH - (minX + maxX) * zoom) / 2,
    y: (GRAPH_HEIGHT - (minY + maxY) * zoom) / 2,
  };
}

// Citation count scales the radius within a bounded band (§10.1).
export function nodeRadius(citations: number | undefined | null): number {
  return Math.min(18, 8 + Math.sqrt(Math.max(0, Number(citations) || 0)) * 1.2);
}

// Deterministic per-id pseudo-random in [0, 1): the same map lays out identically.
function seededUnit(key: string): number {
  let hash = 2166136261;
  for (let index = 0; index < key.length; index += 1) {
    hash ^= key.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
}

interface SimNode extends SimulationNodeDatum {
  id: string;
}

// Synchronous force layout: iterate to stability once, then stop (§10.1).
export function layoutCitationMap(
  nodes: CitationNode[],
  edges: CitationEdge[],
  ticks = 280,
): Record<string, LayoutPoint> {
  const simNodes: SimNode[] = nodes.map((node) => ({
    id: node.id,
    x: GRAPH_WIDTH / 2 + (seededUnit(node.id) - 0.5) * GRAPH_WIDTH * 0.55,
    y: GRAPH_HEIGHT / 2 + (seededUnit(`${node.id}:y`) - 0.5) * GRAPH_HEIGHT * 0.55,
  }));
  const radiusById = new Map(nodes.map((node) => [node.id, nodeRadius(node.citations)]));
  const links: Array<SimulationLinkDatum<SimNode>> = edges.map((edge) => ({ source: edge.source, target: edge.target }));
  const simulation = forceSimulation(simNodes)
    .force("link", forceLink<SimNode, SimulationLinkDatum<SimNode>>(links).id((node) => node.id).distance(90).strength(0.6))
    .force("charge", forceManyBody().strength(-240))
    .force("center", forceCenter(GRAPH_WIDTH / 2, GRAPH_HEIGHT / 2))
    .force("collide", forceCollide((node: SimNode) => (radiusById.get(node.id) ?? 10) + 22))
    .stop();
  for (let index = 0; index < ticks; index += 1) simulation.tick();
  return Object.fromEntries(simNodes.map((node) => [node.id, { x: node.x ?? 0, y: node.y ?? 0 }]));
}
