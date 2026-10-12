import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationNodeDatum,
} from "d3-force";
interface Node extends SimulationNodeDatum {
  id: string;
  count: number;
}
self.onmessage = (
  event: MessageEvent<{
    nodes: Node[];
    edges: { source: string; target: string }[];
  }>,
) => {
  const nodes = event.data.nodes.map((node) => ({ ...node }));
  const links = event.data.edges.map((edge) => ({ ...edge }));
  const simulation = forceSimulation(nodes)
    .stop()
    .force(
      "link",
      forceLink<Node, { source: string; target: string }>(links)
        .id((node) => node.id)
        .distance(65),
    )
    .force("charge", forceManyBody().strength(-110))
    .force("center", forceCenter(400, 250))
    .force(
      "collide",
      forceCollide<Node>((node) => Math.min(15, 4 + Math.sqrt(node.count)) + 3),
    );
  for (let i = 0; i < 160; i++) simulation.tick();
  self.postMessage(
    nodes.map((node) => ({ id: node.id, x: node.x || 400, y: node.y || 250 })),
  );
};
