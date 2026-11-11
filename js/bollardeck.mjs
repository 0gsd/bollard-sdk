// SPDX-License-Identifier: Apache-2.0
// ES module entry: the same object bollardeck.js defines, whole, with its parts as named exports.
//   import bollardeck, { schema, cues, matrix, constants } from "./bollardeck.mjs";
import "./bollardeck.js";
import "./bollardeck.schemas.js";
import "./bollardeck.schema.js";
import "./bollardeck.cues.js";
import "./bollardeck.matrix.js";
import "./bollardeck.gestures.js";
import "./bollardeck.keymap.js";
import "./bollardeck.corpus.js";
import "./bollardeck.dom.js";

const bollardeck = globalThis.bollardeck;
export default bollardeck;
export const version = bollardeck.version;
export const speaks = bollardeck.speaks;
export const minBollawax = bollardeck.minBollawax;
export const constants = bollardeck.constants;
export const schemas = bollardeck.schemas;
export const schema = bollardeck.schema;
export const cues = bollardeck.cues;
export const matrix = bollardeck.matrix;
export const gestures = bollardeck.gestures;
export const keymap = bollardeck.keymap;
export const corpus = bollardeck.corpus;
