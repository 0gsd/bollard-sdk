// SPDX-License-Identifier: Apache-2.0
// Shared by the tests in this folder: the repository's paths, its JSON files and the binding.
"use strict";
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const JS = path.join(ROOT, "js");
const CONFORMANCE = path.join(ROOT, "conformance");
const PARTS = ["schemas", "schema", "cues", "matrix", "gestures", "keymap", "corpus", "help", "popsnip", "dom"];

function readJson(...parts) {
  return JSON.parse(fs.readFileSync(path.join(...parts), "utf8"));
}

function jsonFiles(dir) {
  return fs.readdirSync(dir).filter((f) => f.endsWith(".json")).sort().map((f) => path.join(dir, f));
}

module.exports = { ROOT, JS, CONFORMANCE, PARTS, readJson, jsonFiles, bollardeck: require(path.join(JS, "bollardeck.js")) };
