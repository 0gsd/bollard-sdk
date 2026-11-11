// SPDX-License-Identifier: Apache-2.0
/*
 * bollardeck.schema: check a document against one of the platform's JSON Schemas.
 *
 *   var problems = bollardeck.schema.validate("licence", block);   // [] when the block is fine
 *   problems.forEach(function (p) { console.log(p.pointer, p.message); });   // "/scope", "must be ..."
 *
 * The twin of python/bollardeck/schema.py: the same keywords, the same refusals, and the same
 * verdict on every vector in conformance/index.json (tests/js/schema.test.js runs them all, and
 * tests/test_js.py compares where each problem is reported with the Python validator's answer).
 *
 * The schemas are the files under schema/ in the SDK repository (JSON Schema draft 2020-12). They
 * reach a page as bollardeck.schemas, from js/bollardeck.schemas.js, which
 * tools/generate.py writes: no fetch is needed. A page that fetched newer ones itself
 * hands them over with use({name: schema, ...}). names() lists what is loaded.
 *
 * This is a small validator. It implements exactly the keywords in KEYWORDS, which are the ones
 * the SDK's schemas use, and it REFUSES a schema that uses any other keyword (it throws
 * UnsupportedSchema): a keyword it skipped would be a rule it silently did not enforce. `format`
 * is not implemented and is refused; the schemas use `pattern`.
 *
 * As in the Python validator: true and false are never numbers, 1 and 1.0 are the same number,
 * and a string's length is counted in characters (code points), not UTF-16 units. `pattern` is
 * compiled with the "u" flag.
 */
(function (root) {
  "use strict";

  var DIALECT = "https://json-schema.org/draft/2020-12/schema";
  // Keywords that say nothing about validity.
  var ANNOTATIONS = ["$schema", "$id", "$comment", "title", "description", "examples", "default"];
  // Keywords that hold schemas: one, a list of them, or a mapping of them.
  var ONE = ["additionalProperties", "items", "not", "if", "then"];
  var LIST = ["allOf", "anyOf", "prefixItems"];
  var MAP = ["properties", "$defs"];
  // Every keyword this validator enforces.
  var KEYWORDS = [
    "$ref", "$defs", "type", "enum", "const",
    "minimum", "maximum", "exclusiveMinimum",
    "minLength", "pattern",
    "items", "prefixItems", "minItems", "maxItems",
    "properties", "required", "additionalProperties", "minProperties",
    "allOf", "anyOf", "not", "if", "then"
  ];
  var TYPES = ["null", "boolean", "object", "array", "number", "integer", "string"];

  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function isObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
  function isNumber(v) { return typeof v === "number" && isFinite(v); }

  // A schema uses something this validator does not implement, or is not a schema at all.
  function UnsupportedSchema(message) {
    this.name = "UnsupportedSchema";
    this.message = message;
    if (Error.captureStackTrace) Error.captureStackTrace(this, UnsupportedSchema);
    else this.stack = (new Error(message)).stack;
  }
  UnsupportedSchema.prototype = Object.create(Error.prototype);
  UnsupportedSchema.prototype.constructor = UnsupportedSchema;

  // One thing wrong with a document. `pointer` is an RFC 6901 JSON pointer into the document
  // ("" is the document itself); `keyword` is the schema keyword that refused it.
  function Problem(pointer, message, keyword) {
    this.pointer = pointer;
    this.message = message;
    this.keyword = keyword;
  }
  Problem.prototype.toString = function () { return "#" + this.pointer + ": " + this.message; };

  // ── the schemas ────────────────────────────────────────────────────────────────────────

  var bollardeck;                 // set at the bottom of this file
  var supplied = null;            // what use() was given, if anything
  var parsed = null, byId = null;

  function loadAll() {
    if (parsed) return;
    var source = supplied || bollardeck.schemas;
    if (!isObject(source)) {
      throw new Error("bollardeck.schema: no schemas loaded; load bollardeck.schemas.js or call schema.use({...})");
    }
    var ids = Object.create(null), all = Object.create(null);
    Object.keys(source).forEach(function (name) {
      check(source[name], name);
      ids[source[name].$id] = source[name];
      all[name] = source[name];
    });
    parsed = all;
    byId = ids;
  }

  // Validate against these schemas ({name: schema}) from now on, not the ones that came with
  // the SDK. Every one of them is checked first; a schema this validator cannot enforce throws.
  function use(schemas) {
    if (!isObject(schemas)) throw new TypeError("schema.use takes an object of schemas by name");
    var kept = [supplied, parsed, byId];
    supplied = schemas;
    parsed = byId = null;
    try { loadAll(); } catch (e) { supplied = kept[0]; parsed = kept[1]; byId = kept[2]; throw e; }
  }

  // The schema names validate() takes, e.g. "corpus-manifest", "licence".
  function names() {
    loadAll();
    return Object.keys(parsed).sort();
  }

  // The schema called `name`, checked. Treat it as read-only.
  function load(name) {
    loadAll();
    if (!has(parsed, name)) {
      throw new RangeError("no schema called " + JSON.stringify(name) + " (known: " + Object.keys(parsed).sort().join(", ") + ")");
    }
    return parsed[name];
  }

  function escape(token) { return String(token).replace(/~/g, "~0").replace(/\//g, "~1"); }

  function subschemas(node, path, out) {
    out.push([path, node]);
    if (!isObject(node)) return out;
    Object.keys(node).forEach(function (key) {
      var value = node[key], here = path + "/" + key;
      if (ONE.indexOf(key) >= 0) subschemas(value, here, out);
      else if (LIST.indexOf(key) >= 0 && Array.isArray(value)) {
        value.forEach(function (sub, i) { subschemas(sub, here + "/" + i, out); });
      } else if (MAP.indexOf(key) >= 0 && isObject(value)) {
        Object.keys(value).forEach(function (name) { subschemas(value[name], here + "/" + escape(name), out); });
      }
    });
    return out;
  }

  var regexes = Object.create(null);
  function regex(pattern) {
    if (typeof pattern !== "string") throw new TypeError("a pattern must be a string");
    if (!regexes[pattern]) regexes[pattern] = new RegExp(pattern, "u");
    return regexes[pattern];
  }

  // Throws UnsupportedSchema unless every keyword in `schema` is one this validator implements
  // and is well formed enough to enforce.
  function check(schema, where) {
    where = where === undefined ? "schema" : where;
    if (!isObject(schema) || typeof schema.$id !== "string") {
      throw new UnsupportedSchema(where + ": a schema document must be an object with an $id");
    }
    if (schema.$schema !== DIALECT) throw new UnsupportedSchema(where + ": $schema must be " + DIALECT);
    subschemas(schema, "", []).forEach(function (entry) {
      var path = entry[0], node = entry[1];
      if (typeof node === "boolean") return;
      if (!isObject(node)) throw new UnsupportedSchema(where + "#" + path + ": a schema must be an object or a boolean");
      var unknown = Object.keys(node).filter(function (k) { return KEYWORDS.indexOf(k) < 0 && ANNOTATIONS.indexOf(k) < 0; }).sort();
      if (unknown.length) throw new UnsupportedSchema(where + "#" + path + ": keyword(s) not implemented: " + unknown.join(", "));
      if (path && has(node, "$id")) throw new UnsupportedSchema(where + "#" + path + ": $id inside a schema is not implemented");
      var types = has(node, "type") ? (Array.isArray(node.type) ? node.type : [node.type]) : [];
      types.forEach(function (t) {
        if (TYPES.indexOf(t) < 0) throw new UnsupportedSchema(where + "#" + path + ": unknown type " + JSON.stringify(t));
      });
      if (has(node, "pattern")) {
        try { regex(node.pattern); } catch (e) {
          throw new UnsupportedSchema(where + "#" + path + ": pattern does not compile: " + e.message);
        }
      }
      if (has(node, "then") && !has(node, "if")) throw new UnsupportedSchema(where + "#" + path + ": then without if");
    });
  }

  // ── validating ─────────────────────────────────────────────────────────────────────────

  function resolvePointer(rootSchema, pointer, where) {
    var node = rootSchema;
    (pointer ? pointer.split("/").slice(1) : []).forEach(function (raw) {
      var token = raw.replace(/~1/g, "/").replace(/~0/g, "~");
      if (!isObject(node) || !has(node, token)) throw new UnsupportedSchema(where + ": nothing at #" + pointer);
      node = node[token];
    });
    return node;
  }

  function absolute(url, base) {
    if (typeof URL === "function") {
      try { return new URL(url, base).href; } catch (e) { /* fall through to the plain join */ }
    }
    return /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url) ? url : base.replace(/[^\/]*$/, "") + url;
  }

  // [schema, its root document] for a $ref seen inside `rootSchema`.
  function resolveRef(ref, rootSchema) {
    var cut = String(ref).indexOf("#");
    var url = cut < 0 ? String(ref) : ref.slice(0, cut), fragment = cut < 0 ? "" : ref.slice(cut + 1);
    var base = String(rootSchema.$id).replace(/#.*$/, "");
    var target = url === "" ? base : absolute(url, base);
    if (!byId || !has(byId, target)) throw new UnsupportedSchema("$ref " + JSON.stringify(ref) + ": no schema with $id " + target);
    if (fragment && fragment.charAt(0) !== "/") {
      throw new UnsupportedSchema("$ref " + JSON.stringify(ref) + ": only JSON pointer fragments are implemented");
    }
    return [resolvePointer(byId[target], fragment, target), byId[target]];
  }

  function isType(v, t) {
    if (t === "null") return v === null;
    if (t === "boolean") return typeof v === "boolean";
    if (t === "object") return isObject(v);
    if (t === "array") return Array.isArray(v);
    if (t === "string") return typeof v === "string";
    if (t === "number") return isNumber(v);
    return isNumber(v) && Math.floor(v) === v;            // integer: 1.0 counts
  }

  // JSON equality: true is not 1, and key order does not matter.
  function same(a, b) {
    if (Array.isArray(a) || Array.isArray(b)) {
      return Array.isArray(a) && Array.isArray(b) && a.length === b.length &&
        a.every(function (x, i) { return same(x, b[i]); });
    }
    if (isObject(a) || isObject(b)) {
      if (!isObject(a) || !isObject(b)) return false;
      var ka = Object.keys(a), kb = Object.keys(b);
      return ka.length === kb.length && ka.every(function (k) { return has(b, k) && same(a[k], b[k]); });
    }
    return a === b;
  }

  function dump(v) {
    if (Array.isArray(v)) return "[" + v.map(dump).join(", ") + "]";
    if (isObject(v)) {
      return "{" + Object.keys(v).sort().map(function (k) { return JSON.stringify(k) + ": " + dump(v[k]); }).join(", ") + "}";
    }
    var text = JSON.stringify(v);
    return text === undefined ? String(v) : text;
  }
  function show(v) {
    var text = dump(v);
    return text.length <= 60 ? text : text.slice(0, 57) + "...";
  }

  function codePoints(s) {
    var n = 0;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c >= 0xD800 && c <= 0xDBFF && i + 1 < s.length) {
        var d = s.charCodeAt(i + 1);
        if (d >= 0xDC00 && d <= 0xDFFF) i++;
      }
      n++;
    }
    return n;
  }

  function passes(schema, value, rootSchema) {
    var found = [];
    checkValue(schema, value, "", rootSchema, found);
    return !found.length;
  }

  function checkValue(schema, value, at, rootSchema, out) {
    if (schema === true) return;
    if (schema === false) { out.push(new Problem(at, "is not allowed here", "false")); return; }

    function bad(keyword, message, where) {
      out.push(new Problem(where === undefined ? at : where, message, keyword));
    }
    var i;

    if (has(schema, "$ref")) {
      var target = resolveRef(schema.$ref, rootSchema);
      checkValue(target[0], value, at, target[1], out);
    }

    if (has(schema, "type")) {
      var types = Array.isArray(schema.type) ? schema.type : [schema.type];
      if (!types.some(function (t) { return isType(value, t); })) {
        bad("type", "must be " + types.join(" or ") + ", not " + show(value));
        return;                     // the rest would only repeat the same mistake
      }
    }
    if (has(schema, "enum") && !schema.enum.some(function (e) { return same(value, e); })) {
      bad("enum", "must be one of " + schema.enum.map(show).join(", ") + ", not " + show(value));
    }
    if (has(schema, "const") && !same(value, schema.const)) {
      bad("const", "must be " + show(schema.const) + ", not " + show(value));
    }

    if (isNumber(value)) {
      if (has(schema, "minimum") && value < schema.minimum) bad("minimum", "must be at least " + schema.minimum + ", not " + show(value));
      if (has(schema, "maximum") && value > schema.maximum) bad("maximum", "must be at most " + schema.maximum + ", not " + show(value));
      if (has(schema, "exclusiveMinimum") && value <= schema.exclusiveMinimum) {
        bad("exclusiveMinimum", "must be more than " + schema.exclusiveMinimum + ", not " + show(value));
      }
    }

    if (typeof value === "string") {
      if (has(schema, "minLength") && codePoints(value) < schema.minLength) {
        bad("minLength", "must be at least " + schema.minLength + " character(s) long");
      }
      if (has(schema, "pattern") && !regex(schema.pattern).test(value)) {
        bad("pattern", show(value) + " does not match " + schema.pattern);
      }
    }

    if (Array.isArray(value)) {
      if (has(schema, "minItems") && value.length < schema.minItems) {
        bad("minItems", "must have at least " + schema.minItems + " item(s), not " + value.length);
      }
      if (has(schema, "maxItems") && value.length > schema.maxItems) {
        bad("maxItems", "must have at most " + schema.maxItems + " item(s), not " + value.length);
      }
      var prefix = has(schema, "prefixItems") ? schema.prefixItems : [];
      for (i = 0; i < value.length; i++) {
        if (i < prefix.length) checkValue(prefix[i], value[i], at + "/" + i, rootSchema, out);
        else if (has(schema, "items")) checkValue(schema.items, value[i], at + "/" + i, rootSchema, out);
      }
    }

    if (isObject(value)) {
      var props = has(schema, "properties") ? schema.properties : {};
      (has(schema, "required") ? schema.required : []).forEach(function (key) {
        if (!has(value, key)) bad("required", "is missing " + JSON.stringify(key));
      });
      var keys = Object.keys(value);
      if (has(schema, "minProperties") && keys.length < schema.minProperties) {
        bad("minProperties", "must have at least " + schema.minProperties + " member(s)");
      }
      keys.forEach(function (key) {
        var here = at + "/" + escape(key);
        if (has(props, key)) checkValue(props[key], value[key], here, rootSchema, out);
        else if (has(schema, "additionalProperties")) {
          if (schema.additionalProperties === false) bad("additionalProperties", "is not a known member", here);
          else checkValue(schema.additionalProperties, value[key], here, rootSchema, out);
        }
      });
    }

    (has(schema, "allOf") ? schema.allOf : []).forEach(function (sub) { checkValue(sub, value, at, rootSchema, out); });
    if (has(schema, "anyOf")) {
      var tries = [], fits = false;
      for (i = 0; i < schema.anyOf.length && !fits; i++) {
        var found = [];
        checkValue(schema.anyOf[i], value, at, rootSchema, found);
        if (found.length) tries.push(found); else fits = true;
      }
      if (!fits) {
        bad("anyOf", "fits none of the " + schema.anyOf.length + " allowed shapes");
        // Add the nearest miss: a shape the value got inside of says more than one it is not.
        var shallow = ["type", "const", "enum", "not"], best = null, bestKey = null;
        tries.forEach(function (attempt) {
          var key = [attempt.some(function (p) { return p.pointer === at && shallow.indexOf(p.keyword) >= 0; }) ? 1 : 0, attempt.length];
          if (best === null || key[0] < bestKey[0] || (key[0] === bestKey[0] && key[1] < bestKey[1])) { best = attempt; bestKey = key; }
        });
        if (best) best.forEach(function (p) { out.push(p); });
      }
    }
    if (has(schema, "not") && passes(schema.not, value, rootSchema)) bad("not", "must not be " + show(value));
    if (has(schema, "if") && has(schema, "then") && passes(schema.if, value, rootSchema)) {
      checkValue(schema.then, value, at, rootSchema, out);
    }
  }

  // Every problem with `value` as a document of the schema `name` ([] when it is fine).
  // `name` may point inside a schema: "cue#/$defs/cue" checks one cue, not a cue list.
  function validate(name, value) {
    name = String(name);
    var cut = name.indexOf("#");
    var fragment = cut < 0 ? "" : name.slice(cut + 1);
    name = cut < 0 ? name : name.slice(0, cut);
    var rootSchema = load(name);
    var problems = [];
    checkValue(resolvePointer(rootSchema, fragment, name), value, "", rootSchema, problems);
    return problems;
  }

  function isValid(name, value) { return !validate(name, value).length; }

  var api = {
    DIALECT: DIALECT, KEYWORDS: KEYWORDS, ANNOTATIONS: ANNOTATIONS, TYPES: TYPES,
    UnsupportedSchema: UnsupportedSchema, Problem: Problem,
    names: names, load: load, use: use, check: check, validate: validate, isValid: isValid
  };

  bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var schema = bollardeck.schema || (bollardeck.schema = {});
  Object.keys(api).forEach(function (k) { schema[k] = api[k]; });
  (bollardeck.parts || (bollardeck.parts = {})).schema = true;
  if (typeof module === "object" && module.exports) module.exports = schema;
})(typeof globalThis !== "undefined" ? globalThis : this);
