"use strict";
/*
 * Visual-lineage geometry (mirrors openvlharness/studio/geometry.py).
 *
 * A transform maps child-frame pixels to parent-frame pixels:
 *   parent = offset + child * scale     (axis-aligned affine)
 * Crops, resizes, letterbox padding and normalized frames are all of this
 * form, so nested crops compose exactly. Nothing here guesses a frame: every
 * constructor needs explicit sizes, and callers pass null when they are unknown.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.StudioGeometry = api;
})(typeof self !== "undefined" ? self : this, function () {
  const affine = (sx = 1, sy = 1, tx = 0, ty = 0) => ({sx, sy, tx, ty});
  const identity = () => affine();
  const positive = (...values) => values.every((v) => typeof v === "number" && Number.isFinite(v) && v > 0);

  function applyPoint(t, x, y) { return [t.tx + x * t.sx, t.ty + y * t.sy]; }
  function applyBox(t, box) {
    const [x1, y1] = applyPoint(t, box[0], box[1]); const [x2, y2] = applyPoint(t, box[2], box[3]);
    return [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
  }
  /** child->this then this->parent. */
  function then(child, parent) {
    return affine(child.sx * parent.sx, child.sy * parent.sy, parent.tx + child.tx * parent.sx, parent.ty + child.ty * parent.sy);
  }
  function inverse(t) {
    if (!t.sx || !t.sy) throw new Error("Singular transform");
    return affine(1 / t.sx, 1 / t.sy, -t.tx / t.sx, -t.ty / t.sy);
  }
  function compose(chain) { return chain.reduce((acc, step) => then(acc, step), identity()); }

  function cropTransform(cropBox, outputSize) {
    const [l, t, r, b] = cropBox.map(Number); const [w, h] = outputSize.map(Number);
    if (!(r > l && b > t && positive(w, h))) return null;
    return affine((r - l) / w, (b - t) / h, l, t);
  }
  function resizeTransform(childSize, parentSize) {
    if (!positive(...childSize, ...parentSize)) return null;
    return affine(parentSize[0] / childSize[0], parentSize[1] / childSize[1]);
  }
  function letterboxTransform(contentSize, padding, parentSize) {
    const s = resizeTransform(contentSize, parentSize); if (!s) return null;
    return affine(s.sx, s.sy, -padding[0] * s.sx, -padding[1] * s.sy);
  }
  function normalizedTransform(scale, frameSize) {
    if (!positive(scale, ...frameSize)) return null;
    return affine(frameSize[0] / scale, frameSize[1] / scale);
  }
  function clipBox(box, width, height) {
    const c = (v, hi) => Math.max(0, Math.min(hi, v));
    const out = [c(box[0], width), c(box[1], height), c(box[2], width), c(box[3], height)];
    return out[2] > out[0] && out[3] > out[1] ? out : null;
  }

  /** Python's round(): ties go to the even integer (needed to match coerce_xyxy). */
  function roundHalfEven(x) {
    const floor = Math.floor(x); const diff = x - floor;
    if (diff > 0.5) return floor + 1;
    if (diff < 0.5) return floor;
    return floor % 2 === 0 ? floor : floor + 1;
  }
  /** Exact replica of services/tools/image_utils.coerce_xyxy for normalized_xyxy (0-1000). */
  function coerceNormalized(coords, width, height) {
    const clamp = (v) => Math.max(0, Math.min(1000, v));
    let x1 = clamp(coords[0]) / 1000.0 * width; let x2 = clamp(coords[2]) / 1000.0 * width;
    let y1 = clamp(coords[1]) / 1000.0 * height; let y2 = clamp(coords[3]) / 1000.0 * height;
    [x1, x2] = [Math.min(x1, x2), Math.max(x1, x2)]; [y1, y2] = [Math.min(y1, y2), Math.max(y1, y2)];
    const box = [roundHalfEven(x1), roundHalfEven(y1), roundHalfEven(x2), roundHalfEven(y2)];
    return box[2] > box[0] && box[3] > box[1] ? box : null;
  }
  /**
   * Reconstruct a Zoom_In_Tool crop from its recorded arguments (coords + padding on
   * the 0-1000 scale) and the input size; verified only if it reproduces the output size.
   */
  function reconstructZoom(args, inputSize, outputSize) {
    const coords = args?.coords;
    if (!Array.isArray(coords) || coords.length !== 4 || !inputSize || !positive(...inputSize)) return {verified: false, reason: "missing coordinates or input size"};
    const pad = Number(args.padding ?? 50);
    const box = coerceNormalized([coords[0] - pad, coords[1] - pad, coords[2] + pad, coords[3] + pad].map(Number), inputSize[0], inputSize[1]);
    if (!box) return {verified: false, reason: "empty crop"};
    const verified = Boolean(outputSize && outputSize[0] === box[2] - box[0] && outputSize[1] === box[3] - box[1]);
    return {cropBox: box, verified, reason: verified ? null : "reconstructed crop does not match the returned crop size",
      requestedRegion: coords.map(Number), padding: pad};
  }

  return {affine, identity, applyPoint, applyBox, then, inverse, compose, cropTransform, resizeTransform,
    letterboxTransform, normalizedTransform, clipBox, roundHalfEven, coerceNormalized, reconstructZoom};
});
