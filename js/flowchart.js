/* =========================================================
   LEARNHUB LMS - flowchart renderer
   Renders a lesson flowchart ({nodes, edges}) as inline SVG.
   No dependency, works offline. Nodes are laid out top-down;
   decision branches rejoin, and long edges are routed down a
   side lane so they never cross a node.
   Node kinds: start | end | process | decision | input | output
   ========================================================= */

(function () {
    "use strict";

    var W = 640;          // svg width (scales via CSS)
    var CX = W / 2;       // centre x
    var NODE_W = 240;
    var NODE_H = 56;
    var ROW_GAP = 48;
    var LANE_X = CX + 190; // side lane for long edges

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    // Word-wrap a label into lines of at most ~22 chars.
    function wrap(label) {
        var words = String(label).split(/\s+/);
        var lines = [], line = "";
        words.forEach(function (w) {
            if ((line + " " + w).trim().length > 22 && line) {
                lines.push(line.trim());
                line = w;
            } else {
                line = (line + " " + w).trim();
            }
        });
        if (line) lines.push(line);
        return lines.slice(0, 3);
    }

    function nodeHeight(kind, lines) {
        if (kind === "decision") return 96;
        return Math.max(NODE_H, 20 + lines.length * 18);
    }

    function shape(kind, x, y, w, h) {
        // x,y = top-left of the node box. Returns SVG markup.
        var cx = x + w / 2, cy = y + h / 2;
        if (kind === "decision") {
            return '<polygon points="' + cx + ',' + y + ' ' + (x + w) + ',' + cy +
                ' ' + cx + ',' + (y + h) + ' ' + x + ',' + cy + '"' +
                ' fill="#fef3c7" stroke="#d97706" stroke-width="2"/>';
        }
        if (kind === "start" || kind === "end") {
            return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h +
                '" rx="' + (h / 2) + '" fill="#dcfce7" stroke="#16a34a" stroke-width="2"/>';
        }
        if (kind === "input" || kind === "output") {
            var s = 16; // slant
            return '<polygon points="' + (x + s) + ',' + y + ' ' + (x + w) + ',' + y +
                ' ' + (x + w - s) + ',' + (y + h) + ' ' + x + ',' + (y + h) + '"' +
                ' fill="#dbeafe" stroke="#2563eb" stroke-width="2"/>';
        }
        return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h +
            '" rx="10" fill="#eef2ff" stroke="#4f46e5" stroke-width="2"/>';
    }

    function render(container, flowchart) {
        if (!container) return;
        if (!flowchart || !flowchart.nodes || !flowchart.nodes.length) {
            container.innerHTML = "";
            return;
        }
        var nodes = flowchart.nodes;
        var edges = flowchart.edges || [];

        // Order nodes: BFS from the start node (or first node), so the
        // flow reads top-down in execution order.
        var byId = {};
        nodes.forEach(function (n) { byId[n.id] = n; });
        var adj = {};
        edges.forEach(function (e) {
            (adj[e.from] = adj[e.from] || []).push(e.to);
        });
        var start = nodes.find(function (n) { return n.kind === "start"; }) || nodes[0];
        var order = [], seen = {};
        var queue = [start.id];
        seen[start.id] = true;
        while (queue.length) {
            var id = queue.shift();
            order.push(id);
            (adj[id] || []).forEach(function (to) {
                if (!seen[to]) { seen[to] = true; queue.push(to); }
            });
        }
        nodes.forEach(function (n) { if (!seen[n.id]) order.push(n.id); });

        // Geometry: one row per node, in BFS order.
        var rows = {};
        var y = 16;
        order.forEach(function (id) {
            var n = byId[id];
            var lines = wrap(n.label);
            var h = nodeHeight(n.kind, lines);
            rows[id] = { y: y, h: h, lines: lines, kind: n.kind };
            y += h + ROW_GAP;
        });
        var height = y - ROW_GAP + 16;

        var parts = [];
        parts.push('<svg viewBox="0 0 ' + W + ' ' + height + '" width="100%" ' +
            'role="img" aria-label="Flowchart: ' + esc(flowchart.title || "") + '" ' +
            'style="max-width:640px;display:block;margin:0 auto;">');
        parts.push('<defs><marker id="lh-arrow" viewBox="0 0 10 10" refX="9" refY="5" ' +
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">' +
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="#475569"/></marker></defs>');

        // Edges first (under the nodes).
        edges.forEach(function (e) {
            var from = rows[e.from], to = rows[e.to];
            if (!from || !to) return;
            var x1 = CX, y1 = from.y + from.h;
            var x2 = CX, y2 = to.y;
            var d;
            if (to.y === from.y + from.h + ROW_GAP) {
                // Adjacent rows: straight arrow.
                d = "M " + x1 + " " + y1 + " L " + x2 + " " + y2;
            } else {
                // Long jump: route down the side lane.
                var midY = y1 + ROW_GAP / 2;
                d = "M " + x1 + " " + y1 + " L " + x1 + " " + midY +
                    " L " + LANE_X + " " + midY +
                    " L " + LANE_X + " " + (y2 - ROW_GAP / 2) +
                    " L " + x2 + " " + (y2 - ROW_GAP / 2) +
                    " L " + x2 + " " + y2;
            }
            parts.push('<path d="' + d + '" fill="none" stroke="#475569" ' +
                'stroke-width="2" marker-end="url(#lh-arrow)"/>');
            if (e.label) {
                var lx = (to.y === from.y + from.h + ROW_GAP) ? x1 + 10 : LANE_X + 8;
                var ly = (y1 + y2) / 2;
                parts.push('<text x="' + lx + '" y="' + ly + '" font-size="13" ' +
                    'font-weight="700" fill="#b45309">' + esc(e.label) + '</text>');
            }
        });

        // Nodes.
        order.forEach(function (id) {
            var n = byId[id];
            var r = rows[id];
            var x = CX - NODE_W / 2;
            parts.push(shape(n.kind, x, r.y, NODE_W, r.h));
            var cy = r.y + r.h / 2;
            var startY = cy - (r.lines.length - 1) * 9;
            r.lines.forEach(function (line, i) {
                parts.push('<text x="' + CX + '" y="' + (startY + i * 18) + '" ' +
                    'text-anchor="middle" font-size="14" fill="#1e293b">' +
                    esc(line) + '</text>');
            });
        });

        parts.push("</svg>");
        container.innerHTML = parts.join("");
    }

    window.LearnHubFlowchart = { render: render };
})();
