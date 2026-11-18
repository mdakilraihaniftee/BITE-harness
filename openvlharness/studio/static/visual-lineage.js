"use strict";
/*
 * Visual lineage from the visible event prefix: which image each tool call
 * actually processed and produced, and how derived images relate to their
 * parents (original -> crop -> nested crop ...).
 *
 * Links come only from recorded data: the image registry IDs a call consumed
 * (capability image-resolution record) and produced (registry entries created
 * by the call, or the result's image handle), the artifact extracted from the
 * same event, the run's input-image aliases, and geometry recorded by the
 * capability or reconstructed with the tool's own crop rule and verified
 * against the returned crop size. Registry IDs are scoped to the agent's
 * question memory (image_scope, or the recorded initial-inventory boundary for
 * older runs). Nothing is matched by file name, tool name, or time.
 */
(function (root, factory) {
  const api = factory(root.StudioGeometry || (typeof require === "function" ? require("./geometry.js") : null));
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioLineage = api;
})(typeof self !== "undefined" ? self : this, function (G) {
  const REGISTRY_ID = /^(input_image|tool_generated_image)_\d+$/;
  const isInput = (id) => /^input_image_\d+$/.test(id || "");

  function buildLineage(events, {artifacts = {}, aliases = {}} = {}) {
    const images = new Map(); const invocations = new Map(); const byEvent = new Map();
    const scopeOf = new Map(); const legacyCounter = new Map();
    const keyFor = (agent, scope, id) => (isInput(id) ? `input|${id}` : `${agent}|${scope}|${id}`);
    const artifactSize = (id) => { const a = artifacts[id]; return a && a.width > 0 && a.height > 0 ? [Number(a.width), Number(a.height)] : null; };

    const ensureImage = (agent, scope, id) => {
      const key = keyFor(agent, scope, id);
      if (!images.has(key)) {
        const artifactId = isInput(id) ? aliases[id] || null : null;
        const size = artifactId ? artifactSize(artifactId) : null;
        images.set(key, {key, registryId: id, agent: isInput(id) ? null : agent, scope: isInput(id) ? null : scope,
          artifactId, width: size?.[0] ?? null, height: size?.[1] ?? null, kind: isInput(id) ? "input" : "unknown",
          parentKey: null, toParent: null, relation: null, verified: false, producer: null, consumers: [], note: null});
      }
      return images.get(key);
    };
    const setSize = (node, width, height) => { if (!node.width && width > 0 && height > 0) { node.width = width; node.height = height; } };

    for (const event of events) {
      const p = event.payload || {};
      const agent = event.agent_id; const type = event.event_type;
      // Each agent phase is a new question memory (fresh registry). Recorded boundaries:
      // the initial inventory read, and for older runs the worker phase-start events.
      if ((type === "MEMORY_READ" && p.read_kind === "initial_inventory") || type === "WORKER_STARTED" || type === "PEER_REVIEW_STARTED") {
        const n = (legacyCounter.get(agent) || 0) + 1; legacyCounter.set(agent, n);
        scopeOf.set(agent, p.image_scope || `L${n}`);
        continue;
      }
      if (!["TOOL_CALL_REQUESTED", "TOOL_CALL_STARTED", "TOOL_CALL_COMPLETED", "TOOL_CALL_FAILED", "TOOL_CALL_CANCELLED"].includes(type)) continue;
      const scope = p.image_scope || scopeOf.get(agent) || "L0";
      // Owner-qualified, like the story: concurrent calls never share a key.
      const key = `${agent}|${p.invocation_id ? `inv:${p.invocation_id}` : event.activity?.correlation_id || `call:${p.tool_call_id}:${event.event_id}`}`;
      let inv = invocations.get(key);
      if (!inv) {
        inv = {key, agent, scope, tool: event.tool_name, status: "requested", requestEventId: null, resultEventId: null,
          arguments: null, inputKeys: [], outputKeys: [], inputSource: null, roi: null, detections: null, error: null, notes: []};
        invocations.set(key, inv);
      }
      byEvent.set(event.event_id, key);
      if (type === "TOOL_CALL_REQUESTED") {
        inv.requestEventId = event.event_id; inv.arguments = p.arguments || {};
        const preview = (p.visual_inputs || []).filter((i) => i.registry_id).map((i) => ({id: i.registry_id, w: i.width, h: i.height}));
        // Older runs: only an argument that is literally a registry ID is shown before the result.
        if (!p.visual_inputs) for (const [k, v] of Object.entries(inv.arguments)) if (/image.*_id$/i.test(k) && REGISTRY_ID.test(v || "")) preview.push({id: v});
        for (const item of preview) {
          const node = ensureImage(agent, scope, item.id); setSize(node, item.w, item.h);
          if (!inv.inputKeys.includes(node.key)) inv.inputKeys.push(node.key);
        }
        inv.inputSource = p.visual_inputs ? "registry_alias_preview" : (preview.length ? "argument" : null);
        // The selected region is known from the request itself (0-1000 coords on the input);
        // the executed crop boundary is added only once the result verifies it.
        const first = images.get(inv.inputKeys[0]); const coords = inv.arguments?.coords;
        if (/zoom|crop/i.test(event.tool_name || "") && first?.width && Array.isArray(coords) && coords.length === 4) {
          inv.roi = {frameKey: first.key, cropBox: null, requested: [coords[0] / 1000 * first.width, coords[1] / 1000 * first.height, coords[2] / 1000 * first.width, coords[3] / 1000 * first.height],
            verified: false, method: "requested", reason: "The tool has not returned yet.", padding: Number(inv.arguments?.padding ?? 50)};
        }
        continue;
      }
      if (type === "TOOL_CALL_STARTED") { inv.status = "running"; continue; }
      inv.resultEventId = event.event_id;
      inv.status = type === "TOOL_CALL_COMPLETED" ? "completed" : "failed";
      if (type !== "TOOL_CALL_COMPLETED") inv.error = p.error?.message || p.error || "failed";
      const visual = p.visual || null;
      const recordedInputs = visual?.inputs?.length ? visual.inputs.map((i) => ({id: i.registry_id, w: i.width, h: i.height}))
        : ((p.meta?.image_resolution?.rewrites) || []).filter((r) => r.image_ref).map((r) => ({id: r.image_ref}));
      if (recordedInputs.length) {
        inv.inputKeys = []; inv.inputSource = "capability";
        for (const item of recordedInputs) {
          const node = ensureImage(agent, scope, item.id); setSize(node, item.w, item.h);
          inv.inputKeys.push(node.key);
        }
      }
      for (const k of inv.inputKeys) { const node = images.get(k); if (node && !node.consumers.includes(key)) node.consumers.push(key); }
      if (type !== "TOOL_CALL_COMPLETED") continue;

      // ---- outputs: registry entry created by the call + its artifact from this event
      const canonical = p.canonical_result || {};
      let outputs = [];
      if (visual?.outputs?.length) {
        outputs = visual.outputs.map((o) => ({id: o.registry_id, artifactId: o.image?.artifact_ref || null, w: o.width, h: o.height}));
      } else {
        const ids = [canonical.image, canonical.rendered_image].filter((v) => typeof v === "string" && REGISTRY_ID.test(v));
        const refs = (event.artifact_refs || []).filter((id) => artifacts[id]?.artifact_type !== "source_image");
        outputs = ids.map((id) => ({id, artifactId: ids.length === 1 && refs.length === 1 ? refs[0] : null}));
        if (ids.length && ids.length !== refs.length) inv.notes.push("Output image could not be matched to a stored artifact unambiguously.");
      }
      const input = images.get(inv.inputKeys[0]) || null;
      const transform = visual?.transform || null;
      for (const out of outputs) {
        if (!out.id) continue;
        let node = ensureImage(agent, scope, out.id);
        if (node.producer && node.producer !== key) {
          // A registry ID produced again means the registry was reset without a recorded
          // boundary: never reuse the earlier image; open a new scope for this agent.
          const fresh = `${scope}#${key}`; scopeOf.set(agent, fresh);
          node = ensureImage(agent, fresh, out.id);
          node.note = "Registry scope inferred from a reused image ID.";
        }
        node.artifactId = node.artifactId || out.artifactId;
        const size = out.artifactId ? artifactSize(out.artifactId) : null;
        setSize(node, out.w || size?.[0], out.h || size?.[1]);
        node.producer = key; node.parentKey = input?.key || null;
        inv.outputKeys.push(node.key);
      }

      const tool = String(event.tool_name || "");
      // ---- Zoom / crop: recorded geometry, or reconstruction verified against the crop size
      if (/zoom|crop/i.test(tool) && inv.outputKeys.length && input) {
        const out = images.get(inv.outputKeys[0]);
        let crop = null; let verified = false; let method = null; let reason = null;
        if (transform?.type === "crop" && Array.isArray(transform.crop_box)) {
          crop = transform.crop_box; verified = Boolean(transform.verified); method = "recorded"; reason = transform.reason || null;
        } else {
          const rebuilt = G.reconstructZoom(inv.arguments, input.width ? [input.width, input.height] : null, out.width ? [out.width, out.height] : null);
          crop = rebuilt.cropBox || null; verified = rebuilt.verified; method = "reconstructed"; reason = rebuilt.reason;
        }
        const coords = inv.arguments?.coords;
        const requested = Array.isArray(coords) && coords.length === 4 && input.width
          ? [coords[0] / 1000 * input.width, coords[1] / 1000 * input.height, coords[2] / 1000 * input.width, coords[3] / 1000 * input.height] : null;
        inv.roi = {frameKey: input.key, cropBox: crop, requested, verified, method, reason, padding: Number(inv.arguments?.padding ?? 50)};
        if (crop && verified && out.width) {
          out.toParent = G.cropTransform(crop, [out.width, out.height]); out.relation = "crop"; out.kind = "crop"; out.verified = true;
        } else { out.kind = "crop"; out.note = reason || "Crop geometry unavailable."; }
      }
      // ---- Detection / grounding: boxes in the processed image's pixels
      const boxes = Array.isArray(canonical.boxes) ? canonical.boxes : null;
      if (boxes && !/zoom|crop/i.test(tool)) {
        const size = Array.isArray(canonical.size) && canonical.size.length === 2 ? [Number(canonical.size[1]), Number(canonical.size[0])] : null;
        let system = "unknown"; let toInput = null;
        if (input && size && input.width) {
          if (size[0] === input.width && size[1] === input.height) { system = "input_pixels"; toInput = G.identity(); }
          else { system = "resized_pixels"; toInput = G.resizeTransform(size, [input.width, input.height]); }
        }
        inv.detections = {frameKey: input?.key || null, boxes, scores: canonical.scores || [], labels: canonical.labels || [], frameSize: size, system, toInput,
          reason: !input ? "Box alignment unavailable: the processed image was not recorded." : !size ? "Box alignment unavailable: missing transform metadata." : null};
        for (const k of inv.outputKeys) {
          const out = images.get(k);
          if (input && out.width && out.width === input.width && out.height === input.height) { out.toParent = G.identity(); out.relation = "annotation"; out.kind = "annotation"; out.verified = true; }
          else out.kind = "annotation";
        }
      } else if (!/zoom|crop/i.test(tool)) {
        for (const k of inv.outputKeys) {
          const out = images.get(k);
          const same = input && out.width && out.width === input.width && out.height === input.height;
          out.kind = /depth/i.test(tool) ? "visualization" : "output";
          if (same && (transform?.same_frame || /depth/i.test(tool))) { out.toParent = G.identity(); out.relation = "same_frame"; out.verified = true; }
        }
      }
    }

    /** Transform from an image's pixels to its root original image, if every link is verified. */
    function chainToRoot(key) {
      const chain = []; let node = images.get(key); let transform = G.identity(); let guard = 0;
      while (node && node.parentKey && guard < 16) {
        if (!node.toParent) return {complete: false, rootKey: null, chain, reason: node.note || `No verified geometry links ${node.registryId} to its parent.`};
        transform = G.then(transform, node.toParent); chain.push(node.key); node = images.get(node.parentKey); guard += 1;
      }
      if (!node) return {complete: false, rootKey: null, chain, reason: "Parent image not recorded."};
      return {complete: node.kind === "input", rootKey: node.key, chain, transform, reason: node.kind === "input" ? null : "Lineage does not reach an original input image."};
    }

    return {images, invocations, byEvent, chainToRoot};
  }

  return {buildLineage};
});
