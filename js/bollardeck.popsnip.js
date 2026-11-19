// SPDX-License-Identifier: Apache-2.0
/*
 * bollardeck.popsnip: Pop Snip apps, the third-party apps that live at <name>.popsnip.app. The twin of Python's
 * bollardeck.popsnip.records, held to the same vectors (conformance/popsnip/records.json) byte for byte. No
 * dependencies; runs in a page, a Worker and Node.
 *
 *   var p = bollardeck.popsnip;
 *   p.canonical(record)      Uint8Array: the record minus `signature`, keys sorted at every depth, no spaces, every
 *                            string printable ASCII (0x20-0x7e), every number a safe integer
 *   p.canonicalText(record)  the same, as a string
 *   p.signedMessage(record)  CONTEXT + canonical(record): what an Ed25519 signature over a record covers
 *   p.recordId(record)       Promise of the sha256 of canonical(record), lowercase hex (crypto.subtle)
 *   p.parse(text)            strict JSON, as the Python twin reads it: one object, no repeated key, no fraction or
 *                            exponent (bad_number), nothing JSON.parse would quietly accept and Python refuse
 *   p.check(record, signed)  the record, or throws p.RecordError with the code the Python twin gives
 *                            (signed === false: a record about to be signed, without its signature)
 *   p.rekeyRequest(entry)    what a rotation's old_key_sig covers
 *   p.verify(pub, msg, sig)  Promise of an Ed25519 verdict, by the one equation both twins use (ed25519.json)
 *   p.checkAccept(...)       Promise of the device check's verdict on one release of one app (accept.json): the twin
 *                            of Python's bollardeck.popsnip.accept
 *
 * A verifier never hashes or verifies the bytes it received: it parses them, checks the record, and verifies the
 * signature over CONTEXT + canonical(record) as made here.
 *
 * JSON.parse is not used for records: it keeps the last of two repeated keys and reads 1.0 as 1, where the Python
 * twin refuses both, so the two could disagree about what a signature covers.
 */
(function (root) {
  "use strict";

  var V = 1;
  var CONTEXT = "popsnip/1\n";
  var GENESIS = "0000000000000000000000000000000000000000000000000000000000000000";
  var MAX_INT = 9007199254740991;
  var MAX_VERSION = 2147483647;
  var REKEY_DELAY = 7 * 86400;
  var GROUNDS = ["malware", "legal", "impersonation", "fraud", "key_compromise", "withdrawn_by_developer"];
  var PASS_KINDS = ["standard", "glass_lifetime"];
  var LOG_KINDS = ["popsnip.launch", "popsnip.publish", "popsnip.rekey", "popsnip.rekey-cancel"];
  var MAX_FILES = 4096, MAX_PERMISSIONS = 32, MAX_CSP = 2048, MAX_REVOCATIONS = 100000, MAX_DEPTH = 32;
  var PAGE_SIZE = 256, MAX_PAGES = Math.ceil(MAX_REVOCATIONS / PAGE_SIZE);   // revocation pages (format B)

  function RecordError(code) {
    var e = new Error(code);
    e.name = "RecordError";
    e.code = code;
    Object.setPrototypeOf(e, RecordError.prototype);
    return e;
  }
  RecordError.prototype = Object.create(Error.prototype);
  RecordError.prototype.constructor = RecordError;

  var has = function (o, k) { return Object.prototype.hasOwnProperty.call(o, k); };
  // a plain object only (as JSON makes): a Date, a Map or a class instance is not one, and is refused as bad_number
  var isObj = function (v) {
    if (v === null || typeof v !== "object" || Array.isArray(v)) return false;
    var proto = Object.getPrototypeOf(v);
    return proto === Object.prototype || proto === null;
  };
  var oneOf = function (v, list) { return list.indexOf(v) !== -1; };

  // ── canonical bytes ─────────────────────────────────────────────────────────────────────────────
  var PRINTABLE = /^[\x20-\x7e]*$/;

  function commonGround(value, depth) {
    depth = depth || 1;
    if ((Array.isArray(value) || isObj(value)) && depth > MAX_DEPTH) throw new RecordError("bad_json");
    if (Array.isArray(value)) {
      for (var i = 0; i < value.length; i++) commonGround(value[i], depth + 1);
    } else if (isObj(value)) {
      var keys = Object.keys(value).sort();
      for (var j = 0; j < keys.length; j++) {
        if (!PRINTABLE.test(keys[j])) throw new RecordError("not_ascii");
        commonGround(value[keys[j]], depth + 1);
      }
    } else if (typeof value === "string") {
      if (!PRINTABLE.test(value)) throw new RecordError("not_ascii");
    } else if (value === null || typeof value === "boolean") {
      // fine
    } else if (typeof value === "number") {
      if (!Number.isInteger(value) || Math.abs(value) > MAX_INT) throw new RecordError("bad_number");
    } else {
      throw new RecordError("bad_number");
    }
  }

  function write(value) {
    if (value === null) return "null";
    if (value === true) return "true";
    if (value === false) return "false";
    if (typeof value === "number") return String(value === 0 ? 0 : value);      // -0 prints as 0, as in Python
    if (typeof value === "string") return '"' + value.replace(/[\\"]/g, function (c) { return "\\" + c; }) + '"';
    if (Array.isArray(value)) return "[" + value.map(write).join(",") + "]";
    var keys = Object.keys(value).sort();
    return "{" + keys.map(function (k) { return write(k) + ":" + write(value[k]); }).join(",") + "}";
  }

  function body(record) {
    if (!isObj(record)) throw new RecordError("not_object");
    var out = {};
    Object.keys(record).forEach(function (k) {                // defineProperty: a "__proto__" key stays a key
      if (k !== "signature") Object.defineProperty(out, k, { value: record[k], enumerable: true, writable: true, configurable: true });
    });
    commonGround(out);
    return out;
  }

  function ascii(text) {
    var bytes = new Uint8Array(text.length);
    for (var i = 0; i < text.length; i++) bytes[i] = text.charCodeAt(i);
    return bytes;
  }

  function canonicalText(record) { return write(body(record)); }
  function canonical(record) { return ascii(canonicalText(record)); }
  function signedMessage(record) { return ascii(CONTEXT + canonicalText(record)); }

  function hex(buf) {
    var b = new Uint8Array(buf), s = "";
    for (var i = 0; i < b.length; i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16);
    return s;
  }

  function recordId(record) {
    var bytes = canonical(record);
    var subtle = root.crypto && root.crypto.subtle;
    if (!subtle) return Promise.reject(new Error("recordId needs crypto.subtle (a secure context, or Node 19+)"));
    return subtle.digest("SHA-256", bytes).then(hex);
  }

  // ── strict parsing: the grammar of RFC 8259, refusing what the Python twin refuses ──────────────
  function parse(text) {
    if (text instanceof Uint8Array) {
      // ignoreBOM keeps a leading BOM in the text, so it is refused as Python refuses it
      try { text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(text); }
      catch (e) { throw new RecordError("bad_json"); }
    }
    if (typeof text !== "string") throw new RecordError("bad_json");
    if (tooDeep(text)) throw new RecordError("bad_json");       // first, before anything is parsed, as in Python
    var i = 0, n = text.length;
    function fail() { throw new RecordError("bad_json"); }
    function ws() { while (i < n && (text[i] === " " || text[i] === "\t" || text[i] === "\n" || text[i] === "\r")) i++; }
    function value(depth) {
      ws();
      var c = text[i];
      if (c === "{") return object(depth + 1);
      if (c === "[") return array(depth + 1);
      if (c === '"') return string();
      if (c === "-" || (c >= "0" && c <= "9")) return number();
      if (text.startsWith("true", i)) { i += 4; return true; }
      if (text.startsWith("false", i)) { i += 5; return false; }
      if (text.startsWith("null", i)) { i += 4; return null; }
      return fail();
    }
    function object(depth) {
      i++;
      var pairs = [];
      ws();
      if (text[i] === "}") { i++; return build(pairs); }
      for (;;) {
        ws();
        if (text[i] !== '"') fail();
        var k = string();
        ws();
        if (text[i] !== ":") fail();
        i++;
        pairs.push([k, value(depth)]);
        ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "}") { i++; return build(pairs); }
        fail();
      }
    }
    function build(pairs) {                                   // repeats are found when the object closes, as in Python
      var out = Object.create(null), seen = Object.create(null);
      for (var p = 0; p < pairs.length; p++) {
        if (seen[pairs[p][0]] === true) throw new RecordError("duplicate_key");
        seen[pairs[p][0]] = true;
        out[pairs[p][0]] = pairs[p][1];
      }
      return out;
    }
    function array(depth) {
      i++;
      var out = [];
      ws();
      if (text[i] === "]") { i++; return out; }
      for (;;) {
        out.push(value(depth));
        ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "]") { i++; return out; }
        fail();
      }
    }
    function string() {
      i++;
      var out = "";
      for (;;) {
        if (i >= n) fail();
        var c = text[i], code = text.charCodeAt(i);
        if (c === '"') { i++; return out; }
        if (code < 0x20) fail();
        if (c === "\\") {
          var e = text[i + 1];
          var simple = { '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t" };
          if (has(simple, e)) { out += simple[e]; i += 2; continue; }
          if (e === "u" && /^[0-9a-fA-F]{4}$/.test(text.substr(i + 2, 4))) {
            out += String.fromCharCode(parseInt(text.substr(i + 2, 4), 16));
            i += 6;
            continue;
          }
          fail();
        }
        out += c;
        i++;
      }
    }
    function number() {
      var m = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/.exec(text.slice(i));
      if (!m || m[0] === "-" || m[0].length === 0) fail();
      if (m[2] !== undefined || m[3] !== undefined) throw new RecordError("bad_number");
      i += m[0].length;
      var digits = m[0], mag = digits.replace("-", "");
      // exact, past what a double holds: compared as digits, so a huge number never rounds into range
      if (mag.length > 16 || (mag.length === 16 && mag > "9007199254740991")) return Infinity;   // bad_number later
      return Number(digits);
    }
    var v = value(0);
    ws();
    if (i !== n) fail();
    if (!isObj(v)) throw new RecordError("not_object");
    return plain(v);
  }

  // True when objects and arrays nest more than MAX_DEPTH deep, counted in one pass over the text before it is
  // parsed: outside a string a bracket opens or closes a level and a quote opens a string; inside one a quote closes
  // it and a backslash takes the next character with it. No recursion; the Python twin counts the same way.
  function tooDeep(text) {
    var depth = 0, inString = false;
    for (var k = 0; k < text.length; k++) {
      var c = text[k];
      if (inString) {
        if (c === "\\") k++;
        else if (c === '"') inString = false;
      } else if (c === '"') {
        inString = true;
      } else if (c === "[" || c === "{") {
        if (++depth > MAX_DEPTH) return true;
      } else if (c === "]" || c === "}") {
        depth--;
      }
    }
    return false;
  }

  function plain(v) {                                           // null-prototype objects back to plain ones
    if (Array.isArray(v)) return v.map(plain);
    if (isObj(v)) {
      var out = {};
      Object.keys(v).forEach(function (k) {
        Object.defineProperty(out, k, { value: plain(v[k]), enumerable: true, writable: true, configurable: true });
      });
      return out;
    }
    return v;
  }

  // ── field shapes ────────────────────────────────────────────────────────────────────────────────
  var APP = /^[a-z][a-z0-9-]{1,30}[a-z0-9]$/;
  var ACCOUNT = /^acct_[A-Za-z0-9]{8,40}$/;
  var KID = /^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$/;
  var HEX64 = /^[0-9a-f]{64}$/;
  var B64U = /^[A-Za-z0-9_-]+$/;
  var TIME = /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z$/;
  var SEGMENT = /^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$/;
  var PERMISSION = /^[a-z][a-z0-9-]{0,31}$/;
  var NOTICE = /^https:\/\/popboll\.com\/dev\/notices\/[A-Za-z0-9._-]{1,64}$/;
  var ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

  function isInt(v, lo, hi) { return typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi; }
  function str(re) { return function (v) { return typeof v === "string" && re.test(v); }; }

  function b64uBytes(v, nBytes) {
    if (typeof v !== "string" || v.length !== Math.floor((4 * nBytes + 2) / 3) || !B64U.test(v)) return false;
    var bits = 0, acc = 0, out = 0;
    for (var j = 0; j < v.length; j++) {
      acc = (acc << 6) | ALPHABET.indexOf(v[j]);
      bits += 6;
      if (bits >= 8) { bits -= 8; out++; acc &= (1 << bits) - 1; }
    }
    return out === nBytes && acc === 0;                         // the unused low bits are zero: one spelling only
  }

  // The 8 points of small order, canonically encoded (both signs where x is not 0): computed from the curve in
  // Python (tools/popsnip_vectors.py holds the derivation) and pinned by the vectors.
  var SMALL_ORDER = [
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "0100000000000000000000000000000000000000000000000000000000000000",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f"
  ];
  var CURVE = null;                                             // made on first use: BigInt only where it is needed

  function curve() {
    if (CURVE === null) {
      var B = BigInt, p = B("57896044618658097711785492504343953926634992332820282019728792003956564819949");
      var pow = function (b, e) {
        var r = B(1);
        b %= p;
        while (e > B(0)) {
          if (e & B(1)) r = r * b % p;
          b = b * b % p;
          e >>= B(1);
        }
        return r;
      };
      var d = ((B(-121665) * pow(B(121666), p - B(2))) % p + p) % p;
      CURVE = { B: B, p: p, pow: pow, d: d, i: pow(B(2), (p - B(1)) / B(4)) };
    }
    return CURVE;
  }

  function b64uDecode(v) {
    var out = [], bits = 0, acc = 0;
    for (var j = 0; j < v.length; j++) {
      acc = (acc << 6) | ALPHABET.indexOf(v[j]);
      bits += 6;
      if (bits >= 8) { bits -= 8; out.push((acc >> bits) & 255); acc &= (1 << bits) - 1; }
    }
    return out;
  }

  // A public key that can sign: canonical, on the curve, not of small order (the Python twin's _point)
  function point(v) {
    if (!b64uBytes(v, 32)) return false;
    if (typeof BigInt !== "function") return false;               // fail closed where BigInt is missing
    var bytes = b64uDecode(v), hexs = "";
    for (var j = 0; j < 32; j++) hexs += (bytes[j] < 16 ? "0" : "") + bytes[j].toString(16);
    if (SMALL_ORDER.indexOf(hexs) !== -1) return false;
    var c = curve(), B = c.B, p = c.p, sign = bytes[31] >> 7, y = B(0);
    for (var k = 31; k >= 0; k--) y = (y << B(8)) | B(k === 31 ? bytes[k] & 127 : bytes[k]);
    if (y >= p) return false;                                     // y in its one spelling
    var y2 = y * y % p, x2 = (y2 - B(1) + p) % p * c.pow((c.d * y2 + B(1)) % p, p - B(2)) % p;
    if (x2 === B(0)) return false;                                // x = 0: the identity or its negation (or bad sign)
    var x = c.pow(x2, (p + B(3)) / B(8));
    if ((x * x - x2) % p !== B(0)) x = x * c.i % p;
    return (x * x - x2) % p === B(0);                             // else no point has this y: not on the curve
  }

  function toSeconds(text) {
    var m = TIME.exec(text);
    if (!m) throw new RecordError("bad_time");
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) / 1000;
  }

  function time(v) {
    if (typeof v !== "string") return false;
    var m = TIME.exec(v);
    if (!m) return false;
    var y = +m[1], mo = +m[2], d = +m[3];
    if (y < 1970 || mo < 1 || mo > 12 || +m[4] > 23 || +m[5] > 59 || +m[6] > 59) return false;
    var days = new Date(Date.UTC(y, mo, 0)).getUTCDate();
    return d >= 1 && d <= days;
  }

  function app(v) { return typeof v === "string" && APP.test(v) && v.indexOf("--") === -1; }
  var hex64 = str(HEX64);

  function path(p) {
    if (typeof p !== "string" || p.length < 1 || p.length > 256) return false;
    return p.split("/").every(function (seg) { return SEGMENT.test(seg); });
  }

  function files(v) {
    if (!isObj(v)) return false;
    var names = Object.keys(v);
    if (names.length < 1 || names.length > MAX_FILES) return false;
    var folded = Object.create(null), dirs = Object.create(null);
    for (var j = 0; j < names.length; j++) {
      var p = names[j];
      if (!path(p) || !hex64(v[p]) || folded[p.toLowerCase()] === true) return false;
      folded[p.toLowerCase()] = true;
      var parts = p.toLowerCase().split("/");
      for (var q = 1; q < parts.length; q++) dirs[parts.slice(0, q).join("/")] = true;
    }
    return !Object.keys(dirs).some(function (d) { return folded[d] === true; });
  }

  function permissions(v) {
    if (!Array.isArray(v) || v.length > MAX_PERMISSIONS) return false;
    if (!v.every(function (p) { return typeof p === "string" && PERMISSION.test(p); })) return false;
    for (var j = 1; j < v.length; j++) if (!(v[j - 1] < v[j])) return false;
    return true;
  }

  function target(v) {
    if (!isObj(v)) return false;
    var keys = Object.keys(v);
    if (keys.length !== 1) return false;
    var k = keys[0], x = v[k];
    if (k === "release") return hex64(x);
    if (k === "app") return app(x);
    if (k === "dev_key") return point(x);
    return false;
  }

  var REVOCATION_FIELDS = ["n", "target", "action", "ground", "at", "by", "notice", "after_seq"];

  // a page's entries: 1 to PAGE_SIZE, numbered one after another (where they start is the page's rule)
  function revocationEntries(v) {
    if (!Array.isArray(v) || v.length < 1 || v.length > PAGE_SIZE) return false;
    for (var j = 0; j < v.length; j++) {
      var e = v[j];
      if (!isObj(e)) return false;
      var keys = Object.keys(e);
      if (!keys.every(function (k) { return oneOf(k, REVOCATION_FIELDS); })) return false;
      if (!REVOCATION_FIELDS.every(function (k) { return k === "after_seq" || has(e, k); })) return false;
      if (!isInt(e.n, 1, MAX_REVOCATIONS) || (j > 0 && e.n !== v[j - 1].n + 1) || !target(e.target)) return false;
      if (!oneOf(e.action, ["revoke", "reinstate"]) || !oneOf(e.ground, GROUNDS) || !time(e.at)) return false;
      if (!oneOf(e.by, ["owner", "delegate", "developer"]) || typeof e.notice !== "string" || !NOTICE.test(e.notice)) return false;
      if ((e.by === "developer") !== (e.ground === "withdrawn_by_developer")) return false;
      if (has(e, "after_seq") && !isInt(e.after_seq, 0, MAX_INT)) return false;
    }
    return true;
  }

  function pageIds(v) {
    return Array.isArray(v) && v.length <= MAX_PAGES && v.every(function (x) { return hex64(x); });
  }

  function reaffirmed(v) {
    if (!Array.isArray(v) || v.length < 1 || v.length > MAX_REVOCATIONS) return false;
    var last = 0;
    for (var j = 0; j < v.length; j++) {
      var e = v[j];
      if (!isObj(e)) return false;
      var keys = Object.keys(e).sort();
      if (keys.length !== 2 || keys[0] !== "id" || keys[1] !== "seq") return false;
      if (!isInt(e.seq, 1, MAX_INT) || !hex64(e.id) || e.seq <= last) return false;
      last = e.seq;
    }
    return true;
  }

  var key = point;
  var nonce = function (v) { return b64uBytes(v, 32); };       // 32 random bytes, not a point
  var sig = function (v) { return b64uBytes(v, 64); };
  var seq = function (v) { return isInt(v, 1, MAX_INT); };
  var account = str(ACCOUNT);

  var FIELD_CHECKS = {
    app: app, account: account, from_account: account, to_account: account, kid: str(KID),
    pub: key, dev_key: key, from_key: key, to_key: key, challenge: nonce,
    signature: sig, old_key_sig: sig,
    release0: hex64, manifest: hex64, head_hash: hex64, cancels_id: hex64,
    launched_at: time, published_at: time, requested_at: time, effective_at: time, at: time,
    not_before: time, not_after: time,
    pass_active: function (v) { return v === true; }, pass_kind: function (v) { return oneOf(v, PASS_KINDS); },
    seq: seq, cancels: seq, after_seq: function (v) { return isInt(v, 0, MAX_INT); },
    version: function (v) { return isInt(v, 1, MAX_VERSION); },
    path: function (v) { return oneOf(v, ["old_key", "account_only"]); },
    files: files, permissions: permissions,
    csp: function (v) { return typeof v === "string" && v.length >= 1 && v.length <= MAX_CSP; },
    entries: revocationEntries, reaffirmed: reaffirmed,
    count: function (v) { return isInt(v, 0, MAX_REVOCATIONS); },
    page_size: function (v) { return isInt(v, PAGE_SIZE, PAGE_SIZE); },
    pages: pageIds, page: function (v) { return isInt(v, 0, MAX_PAGES - 1); },
    resigned_after: str(KID),
    prev: hex64
  };
  var KIND_FIELD_CHECKS = { "popsnip.release prev": function (v) { return v === null || hex64(v); } };

  var LOG = ["seq", "prev", "kid", "signature"];
  var KINDS = {
    "popsnip.launch-key": ["release", ["kid", "pub", "not_before", "not_after", "signature"], []],
    "popsnip.launch-key-revoked": ["release", ["kid", "after_seq", "at", "signature"], []],
    "popsnip.reaffirm": ["release", ["kid", "reaffirmed", "at", "signature"], []],
    "popsnip.launch": ["launch", ["app", "account", "dev_key", "release0", "launched_at", "pass_active", "pass_kind"].concat(LOG), []],
    "popsnip.publish": ["launch", ["app", "version", "manifest", "dev_key", "published_at"].concat(LOG), []],
    "popsnip.rekey": ["launch", ["app", "from_key", "to_key", "from_account", "to_account", "path", "requested_at",
      "effective_at", "challenge"].concat(LOG), ["old_key_sig"]],
    "popsnip.rekey-cancel": ["launch", ["app", "cancels", "cancels_id", "requested_at"].concat(LOG), []],
    "popsnip.head": ["launch", ["seq", "head_hash", "at", "kid", "signature"], []],
    // resigned_after: the revoked launch key whose list this index re-signs
    "popsnip.revocations": ["launch", ["seq", "prev", "at", "count", "page_size", "pages", "kid", "signature"], ["resigned_after"]],
    // one page of the list, covered by the index's hash of it (format B): no signature of its own
    "popsnip.revocation-page": ["index", ["page", "entries"], []],
    "popsnip.release": ["dev", ["app", "version", "prev", "files", "permissions", "dev_key", "signature"], ["csp"]],
    "popsnip.key-proof": ["dev", ["account", "dev_key", "challenge", "signature"], []],
    // what an old_key rotation's old key signs (its signature travels as the rotation's old_key_sig)
    "popsnip.rekey-request": ["dev", ["app", "from_key", "to_key", "from_account", "to_account", "path", "challenge"], []]
  };
  var SIGNER = {};
  Object.keys(KINDS).forEach(function (k) { SIGNER[k] = KINDS[k][0]; });
  var TIME_FIELD = { "popsnip.launch": "launched_at", "popsnip.publish": "published_at",
    "popsnip.rekey": "requested_at", "popsnip.rekey-cancel": "requested_at" };

  function rules(r) {
    var kind = r.kind;
    if (has(r, "prev") && kind !== "popsnip.release" && ((r.seq === 1) !== (r.prev === GENESIS))) return "genesis";
    if (kind === "popsnip.release" && ((r.version === 1) !== (r.prev === null))) return "first_release";
    if (kind === "popsnip.launch-key" && toSeconds(r.not_after) <= toSeconds(r.not_before)) return "window";
    if (kind === "popsnip.rekey-request") {
      if (r.path !== "old_key") return "request_path";
      if (r.from_key === r.to_key) return "same_key";
    }
    if (kind === "popsnip.rekey") {
      if (has(r, "old_key_sig") !== (r.path === "old_key")) return "old_key_sig";
      if (r.from_key === r.to_key) return "same_key";
      var delay = toSeconds(r.effective_at) - toSeconds(r.requested_at);
      var waits = r.path === "account_only" || r.from_account !== r.to_account;
      if (delay !== (waits ? REKEY_DELAY : 0)) return "delay";
    }
    if (kind === "popsnip.rekey-cancel" && r.cancels >= r.seq) return "cancels";
    if (kind === "popsnip.revocations" && r.pages.length !== Math.ceil(r.count / r.page_size)) return "pages";
    if (kind === "popsnip.revocations" && has(r, "resigned_after") && r.resigned_after === r.kid) return "resigned_after";
    if (kind === "popsnip.revocation-page" && r.entries[0].n !== r.page * PAGE_SIZE + 1) return "page_numbers";
    return null;
  }

  // signed === false checks a record about to be signed: `signature` is then not required, and refused if present.
  function check(record, signed) {
    if (!isObj(record)) throw new RecordError("not_object");
    commonGround(record);
    var kind = has(record, "kind") ? record.kind : undefined;
    if (typeof kind !== "string" || !has(KINDS, kind)) throw new RecordError("unknown_kind");
    if (!has(record, "v") || !isInt(record.v, V, V)) throw new RecordError("bad_version");
    var spec = KINDS[kind], required = spec[1], optional = spec[2];
    if (signed === false) required = required.filter(function (f) { return f !== "signature"; });
    var fields = Object.keys(record).sort(), j;
    for (j = 0; j < fields.length; j++) {
      var f = fields[j];
      if (f !== "v" && f !== "kind" && !oneOf(f, required) && !oneOf(f, optional)) throw new RecordError("unknown_field:" + f);
    }
    var req = required.slice().sort();
    for (j = 0; j < req.length; j++) if (!has(record, req[j])) throw new RecordError("missing_field:" + req[j]);
    for (j = 0; j < fields.length; j++) {
      var g = fields[j];
      if (g === "v" || g === "kind") continue;
      var fn = KIND_FIELD_CHECKS[kind + " " + g] || FIELD_CHECKS[g];
      if (!fn(record[g])) throw new RecordError("bad_field:" + g);
    }
    var broken = rules(record);
    if (broken) throw new RecordError("rule:" + broken);
    return record;
  }

  function rekeyRequest(entry) {
    var out = { v: V, kind: "popsnip.rekey-request" };
    ["app", "from_key", "to_key", "from_account", "to_account", "path", "challenge"].forEach(function (f) {
      if (!has(entry, f)) throw new RecordError("missing_field:" + f);
      out[f] = entry[f];
    });
    return out;
  }

  // the entries (numbered from 1) as popsnip.revocation-page records, PAGE_SIZE each, the last one short
  function paginate(entries) {
    var out = [];
    for (var k = 0; k < entries.length; k += PAGE_SIZE) {
      out.push(check({ v: V, kind: "popsnip.revocation-page", page: k / PAGE_SIZE, entries: entries.slice(k, k + PAGE_SIZE) }));
    }
    return out;
  }

  // every entry of the list, when the pages are the (checked, signature-verified) index's own: each a checked page
  // whose id is the index's next one, numbered 0, 1, 2..., every page but the last full, `count` in all. A Promise
  // (ids are hashed with crypto.subtle); it rejects with RecordError("rule:list").
  function checkList(index, pages) {
    return Promise.resolve().then(function () {
      check(index);
      if (index.kind !== "popsnip.revocations" || !Array.isArray(pages) || pages.length !== index.pages.length) {
        throw new RecordError("rule:list");
      }
      pages.forEach(function (page, k) {
        try { check(page); } catch (e) { throw new RecordError("rule:list"); }
        var last = k === pages.length - 1;
        if (page.kind !== "popsnip.revocation-page" || page.page !== k || (!last && page.entries.length !== PAGE_SIZE)) {
          throw new RecordError("rule:list");
        }
      });
      return Promise.all(pages.map(recordId));
    }).then(function (ids) {
      var out = [];
      ids.forEach(function (id, k) {
        if (id !== index.pages[k]) throw new RecordError("rule:list");
        out = out.concat(pages[k].entries);
      });
      if (out.length !== index.count) throw new RecordError("rule:list");
      return out;
    });
  }

  // a newer list grows the one held: a higher seq, a count no lower, every held entry first and unchanged, and the
  // held full pages named again by the same ids (both lists checked, their signatures verified); else rule:extends
  function checkExtends(old, oldEntries, nw, newEntries) {
    var full = Math.floor(old.count / PAGE_SIZE);
    var same = oldEntries.length === old.count && newEntries.length >= oldEntries.length &&
      oldEntries.every(function (e, i) { return canonicalText(e) === canonicalText(newEntries[i]); }) &&
      old.pages.slice(0, full).every(function (p, i) { return nw.pages[i] === p; });
    if (nw.seq <= old.seq || nw.count < old.count || !same) throw new RecordError("rule:extends");
  }

  // ── Ed25519 verification: the one equation both twins use (conformance/popsnip/ed25519.json) ────────────────────
  // Cofactorless [S]B == R + [h]A (RFC 8032 section 5.1.7), S below L, A and R canonical points, and an A or R of small
  // order refused: exactly bollardeck.corpus._ed25519 in Python. The platform's own verifier (WebCrypto) is not used:
  // verifiers differ on small and mixed order, and on the cofactor, and a device must give one answer for any record.
  // Verify only, public data only, so not constant time.
  var ED = null;

  function ed() {
    if (ED === null) {
      var c = curve(), B = c.B, p = c.p;
      var md = function (a) { a %= p; return a < B(0) ? a + p : a; };
      var L = (B(1) << B(252)) + B("27742317777372353535851937790883648493");
      var d2 = c.d * B(2) % p;
      var add = function (a, b) {
        var A = md((a[1] - a[0]) * (b[1] - b[0])), Bb = md((a[1] + a[0]) * (b[1] + b[0]));
        var C = md(a[3] * b[3] % p * d2), D = md(B(2) * a[2] * b[2]);
        var E = Bb - A, F = D - C, G = D + C, H = Bb + A;
        return [md(E * F), md(G * H), md(F * G), md(E * H)];
      };
      var mul = function (k, pt) {
        var out = [B(0), B(1), B(1), B(0)];
        while (k > B(0)) {
          if (k & B(1)) out = add(out, pt);
          pt = add(pt, pt);
          k >>= B(1);
        }
        return out;
      };
      var equal = function (a, b) { return md(a[0] * b[2] - b[0] * a[2]) === B(0) && md(a[1] * b[2] - b[1] * a[2]) === B(0); };
      var le = function (bytes) {
        var n = B(0);
        for (var k = bytes.length - 1; k >= 0; k--) n = (n << B(8)) | B(bytes[k]);
        return n;
      };
      var decode = function (raw) {                             // a point from its 32 bytes, or null (the Python _decode)
        var y = le(raw), sign = y >> B(255);
        y &= (B(1) << B(255)) - B(1);
        if (y >= p) return null;
        var x2 = md((y * y - B(1)) * c.pow(md(c.d * y * y + B(1)), p - B(2)));
        var x;
        if (x2 === B(0)) {
          if (sign) return null;
          x = B(0);
        } else {
          x = c.pow(x2, (p + B(3)) / B(8));
          if (md(x * x - x2) !== B(0)) x = x * c.i % p;
          if (md(x * x - x2) !== B(0)) return null;
          if ((x & B(1)) !== sign) x = p - x;
        }
        return [x, y, B(1), x * y % p];
      };
      var gy = B(4) * c.pow(B(5), p - B(2)) % p, gBytes = [];
      for (var k = 0; k < 32; k++) gBytes.push(Number((gy >> B(8 * k)) & B(255)));
      ED = { B: B, L: L, add: add, mul: mul, equal: equal, le: le, decode: decode, G: decode(gBytes),
             I: [B(0), B(1), B(1), B(0)] };
    }
    return ED;
  }

  function isBytes(v) { return v instanceof Uint8Array; }

  // Answers already worked out, by (A, R, S, SHA-512(R || A || M)): the hash fixes the message for that A and R, so a
  // hit is the same question. A device or the app host checks the same log again and again (every app, every new
  // head); with this, a signature costs one SHA-512 after its first check instead of three scalar multiplications.
  // Bounded: past MEMO_MAX answers it starts again. It changes no answer.
  var MEMO_MAX = 65536, memo = new Map();
  function hexOf(b) { var s = ""; for (var i = 0; i < b.length; i++) s += (b[i] < 16 ? "0" : "") + b[i].toString(16); return s; }

  // Promise of true when `signature` (64 bytes) is `publicKey`'s (32 bytes) Ed25519 signature of `message`; all three
  // are Uint8Arrays. Anything else, or no BigInt or crypto.subtle, is false (rejects only when subtle is missing).
  function verify(publicKey, message, signature) {
    // the inputs are read and copied now, at the call: a caller that changes its buffers afterwards changes nothing
    if (!isBytes(publicKey) || !isBytes(message) || !isBytes(signature)) return Promise.resolve(false);
    if (publicKey.length !== 32 || signature.length !== 64 || typeof BigInt !== "function") return Promise.resolve(false);
    var pk = new Uint8Array(publicKey), sg = new Uint8Array(signature);   // copies (a Buffer's slice is a view)
    var buf = new Uint8Array(64 + message.length);
    buf.set(sg.subarray(0, 32), 0);
    buf.set(pk, 32);
    buf.set(message, 64);
    return Promise.resolve().then(function () {
      var subtle = root.crypto && root.crypto.subtle;
      if (!subtle) throw new Error("verify needs crypto.subtle (a secure context, or Node 19+)");
      return subtle.digest("SHA-512", buf).then(function (digest) {
        var d = new Uint8Array(digest), key = hexOf(pk) + hexOf(sg) + hexOf(d);
        if (memo.has(key)) return memo.get(key);
        var e = ed(), a = e.decode(pk), r = e.decode(sg.subarray(0, 32)), s = e.le(sg.subarray(32));
        var ok = false;
        if (a !== null && r !== null && s < e.L) {
          var small = function (pt) { return e.equal(e.mul(e.B(8), pt), e.I); };
          if (!small(a) && !small(r)) {                         // no secret behind them: the identity "signs" anything
            var h = e.le(d) % e.L;
            ok = e.equal(e.mul(s, e.G), e.add(r, e.mul(h, a)));
          }
        }
        if (memo.size >= MEMO_MAX) memo.clear();
        memo.set(key, ok);
        return ok;
      });
    });
  }

  function b64uToBytes(v) { return new Uint8Array(b64uDecode(v)); }

  // ── accept: the device check for a Pop Snip app (the twin of Python's bollardeck.popsnip.accept) ──────────────────
  //   p.checkAccept(app, release, files, log, head, certs, rootRecords, revocations, pinned, heldHead, heldList)
  //     -> Promise of { ok, code, detail }
  // files: { path: Uint8Array }; log: every entry from seq 1 to the head; revocations and heldList: [index, pages] or
  // null; pinned: the release public keys, as Uint8Arrays; heldHead: the head the device already accepted, or null.
  // It reads only its arguments (no environment, storage or network), has no unsigned mode, and has no argument a
  // lapsed pass could change. It never rejects: a malformed argument is the code "malformed". The codes, in the order
  // they are tried, are the Python twin's (its docstring lists them); conformance/popsnip/accept.json holds both.
  function Refused(code, detail) { this.code = code; this.detail = detail || ""; }
  function Malformed(what) { this.what = what; }

  function list(v) { if (!Array.isArray(v)) throw new Malformed("not a list"); return v; }
  function field(o, k) { if (!isObj(o) || !has(o, k)) throw new Malformed("no " + k); return o[k]; }
  function checked(record) { check(record); return record; }      // RecordError passes through (Python: R.RecordError)

  async function signedBy(record, pub) {
    return pub !== null && pub !== undefined && verify(pub, signedMessage(record), b64uToBytes(record.signature));
  }

  async function pinnedRecord(record, kind, pinned) {
    try { check(record); } catch (e) { if (e instanceof RecordError) return null; throw e; }
    if (record.kind !== kind) return null;
    for (var k of list(pinned)) if (await signedBy(record, k)) return record;
    return null;
  }

  async function acceptRoots(certs, rootRecords, pinned) {
    var keys = new Map(), revoked = new Map(), reaffirmed = new Map();
    for (var c of list(certs)) {
      c = await pinnedRecord(c, "popsnip.launch-key", pinned);
      if (c !== null) keys.set(c.kid, [b64uToBytes(c.pub), toSeconds(c.not_before), toSeconds(c.not_after)]);
    }
    for (var rec of list(rootRecords)) {
      var r = await pinnedRecord(rec, "popsnip.launch-key-revoked", pinned);
      if (r !== null) {
        revoked.set(r.kid, Math.min(r.after_seq, revoked.has(r.kid) ? revoked.get(r.kid) : r.after_seq));
        continue;
      }
      var a = await pinnedRecord(rec, "popsnip.reaffirm", pinned);
      if (a === null) throw new Refused("roots", "a root record is malformed or not signed by a pinned release key");
      if (!reaffirmed.has(a.kid)) reaffirmed.set(a.kid, new Map());
      a.reaffirmed.forEach(function (e) { reaffirmed.get(a.kid).set(e.seq, e.id); });
    }
    return { keys: keys, revoked: revoked, reaffirmed: reaffirmed };
  }

  function reaffirmedAs(t, kid, seq) { return t.reaffirmed.has(kid) ? t.reaffirmed.get(kid).get(seq) : undefined; }

  async function acceptLog(log, head, t) {
    try { check(head); } catch (e) { if (e instanceof RecordError) throw new Refused("head", "the head is malformed"); throw e; }
    if (head.kind !== "popsnip.head") throw new Refused("head", "not a head");
    if (!t.keys.has(head.kid)) throw new Refused("cert", "no certificate for the head's key " + head.kid);
    if (!(await signedBy(head, t.keys.get(head.kid)[0]))) throw new Refused("head", "the head's signature does not verify");
    if (t.revoked.has(head.kid) && reaffirmedAs(t, head.kid, head.seq) !== head.head_hash) {
      // ANY head by a root-revoked key, unless the owner reaffirmed that head's seq and head_hash (see the Python twin)
      throw new Refused("launch_key_revoked", "the head is signed by " + head.kid + ", which is revoked");
    }
    var prevId = GENESIS, prevTime = "", ids = [];
    list(log);
    for (var n = 1; n <= log.length; n++) {
      var e = log[n - 1];
      try { check(e); } catch (err) {
        if (err instanceof RecordError) throw new Refused("log", "entry " + n + " is malformed (" + err.code + ")");
        throw err;
      }
      if (!oneOf(e.kind, LOG_KINDS) || e.seq !== n || e.prev !== prevId) {
        throw new Refused("log", "entry " + n + " does not follow the one before");
      }
      var tm = e[TIME_FIELD[e.kind]];
      if (tm < prevTime) throw new Refused("log", "entry " + n + " is earlier than the one before");
      if (!t.keys.has(e.kid)) throw new Refused("cert", "no certificate for key " + e.kid + " (entry " + n + ")");
      var k = t.keys.get(e.kid), at = toSeconds(tm);
      if (!(k[1] <= at && at < k[2]) || !(await signedBy(e, k[0]))) {
        throw new Refused("log", "entry " + n + " is not signed by its key inside its certificate's window");
      }
      var id = await recordId(e);
      if (t.revoked.has(e.kid) && n > t.revoked.get(e.kid) && reaffirmedAs(t, e.kid, n) !== id) {
        throw new Refused("launch_key_revoked", "entry " + n + " is signed by " + e.kid + " after its revocation");
      }
      ids.push(id);
      prevId = id;
      prevTime = tm;
    }
    if (head.seq !== log.length || !log.length || head.head_hash !== ids[ids.length - 1]) {
      throw new Refused("head", "the head does not name the snapshot's last entry");
    }
    return ids;
  }

  // (account, key) for the app at log time `at`, for an entry at position `seq`: the key walk (the `states` vectors)
  function acceptState(entries, ids, app, at, seq) {
    var binding = entries.find(function (e) { return e.kind === "popsnip.launch" && e.app === app; });
    var key = binding.dev_key, account = binding.account;
    var rekeys = new Map();
    entries.forEach(function (e) { if (e.kind === "popsnip.rekey" && e.app === app) rekeys.set(e.seq, e); });
    var cancelled = new Set();                                  // every valid cancel counts, whatever else names the seq
    entries.forEach(function (c) {
      if (c.kind === "popsnip.rekey-cancel" && c.app === app && c.seq < seq) {
        var e = rekeys.get(c.cancels);
        if (e !== undefined && c.cancels_id === ids[e.seq - 1] && c.requested_at < e.effective_at) cancelled.add(e.seq);
      }
    });
    var changes = [];
    rekeys.forEach(function (e, s) { if (s < seq && e.effective_at <= at && !cancelled.has(s)) changes.push(e); });
    changes.sort(function (x, y) {
      return x.effective_at < y.effective_at ? -1 : x.effective_at > y.effective_at ? 1 : x.seq - y.seq;
    });
    changes.forEach(function (e) {
      if (e.from_key === key && e.from_account === account) { key = e.to_key; account = e.to_account; }
    });
    return [account, key];
  }

  async function acceptRekeys(entries, app) {
    var seen = new Set();
    for (var e of entries) {
      if (e.kind !== "popsnip.rekey" || e.app !== app) continue;
      if (seen.has(e.challenge)) throw new Refused("repeated_challenge", "entry " + e.seq + " reuses a rotation challenge");
      seen.add(e.challenge);
      if (e.path === "old_key" &&
          !(await verify(b64uToBytes(e.from_key), signedMessage(rekeyRequest(e)), b64uToBytes(e.old_key_sig)))) {
        throw new Refused("rekey_sig", "entry " + e.seq + "'s old_key_sig is not the old key's");
      }
    }
  }

  function pair(v) { if (!Array.isArray(v) || v.length !== 2) throw new Malformed("not a pair"); return v; }

  async function acceptList(revocations, t) {
    if (revocations === null || revocations === undefined) return [];
    var index = pair(revocations)[0], pages = revocations[1];
    try { check(index); } catch (e) {
      if (e instanceof RecordError) throw new Refused("list_signature", "the list's index is malformed");
      throw e;
    }
    if (index.kind !== "popsnip.revocations" || !t.keys.has(index.kid) || !(await signedBy(index, t.keys.get(index.kid)[0]))) {
      throw new Refused("list_signature", "the list's index is not signed by a certified key");
    }
    if (t.revoked.has(index.kid)) {
      throw new Refused("list_key_revoked", "the list's newest index is signed by a revoked key; wait for its re-sign");
    }
    try { return await checkList(index, pages); } catch (e) {
      if (e instanceof RecordError) throw new Refused("list_pages", "the list's pages are not its index's");
      throw e;
    }
  }

  async function acceptHeldList(heldList, index, entries) {
    if (heldList === null || heldList === undefined) return;
    var hIndex = pair(heldList)[0];
    check(hIndex);
    var hEntries = await checkList(hIndex, heldList[1]);
    if (index === null) throw new Refused("list_rollback", "the device holds a list, and none was given");
    if (index.seq === hIndex.seq) {
      if ((await recordId(index)) !== (await recordId(hIndex))) {
        throw new Refused("list_rollback", "another list at the seq the device holds");
      }
      return;
    }
    try { checkExtends(hIndex, hEntries, index, entries); } catch (e) {
      if (e instanceof RecordError) throw new Refused("list_rollback", "the list does not extend the one the device holds");
      throw e;
    }
  }

  async function sha256Hex(bytes) {
    var subtle = root.crypto && root.crypto.subtle;
    if (!subtle) throw new Error("checkAccept needs crypto.subtle (a secure context, or Node 19+)");
    return hex(await subtle.digest("SHA-256", bytes));
  }

  async function acceptSteps(app, release, files, log, head, certs, rootRecords, revocations, pinned, heldHead, heldList) {
    var t = await acceptRoots(certs, rootRecords, pinned);
    var ids = await acceptLog(log, head, t);
    if (heldHead !== null && heldHead !== undefined) {
      checked(heldHead);
      var h = field(heldHead, "seq");                          // head_hash is read only when the seqs allow it,
      if (head.seq < h || ids[h - 1] !== field(heldHead, "head_hash")) {   // as Python reads it
        throw new Refused("rollback", "the log does not extend the head the device holds (seq " + h + ")");
      }
    }
    if (!log.some(function (e) { return e.kind === "popsnip.launch" && e.app === app; })) {
      throw new Refused("no_binding", app + " was never launched");
    }
    await acceptRekeys(log, app);
    try { check(release); } catch (e) {
      if (e instanceof RecordError) throw new Refused("release_signature", "the release is malformed (" + e.code + ")");
      throw e;
    }
    var rid = await recordId(release);
    var pub = log.find(function (e) {
      return e.kind === "popsnip.publish" && e.app === app && e.manifest === rid && release.kind === "popsnip.release" &&
        release.app === app;
    });
    if (pub === undefined) throw new Refused("not_published", "this release of " + app + " is not in the log");
    if (pub.version !== release.version) throw new Refused("version", "the log publishes it as version " + pub.version);
    var key = acceptState(log, ids, app, pub.published_at, pub.seq)[1];
    if (release.dev_key !== key || pub.dev_key !== key) {
      throw new Refused("wrong_key", "the app's key at entry " + pub.seq + " is another");
    }
    if (!(await signedBy(release, b64uToBytes(release.dev_key)))) {
      throw new Refused("release_signature", "the developer's signature does not verify");
    }
    if (!isObj(files)) throw new Malformed("files are not a mapping");
    var want = release.files, paths = Object.keys(files), wanted = Object.keys(want);
    if (paths.length !== wanted.length || !paths.every(function (q) { return has(want, q); })) {
      throw new Refused("files", "the files are not exactly the release's");
    }
    for (var q of wanted) {
      if (!isBytes(files[q])) throw new Malformed("a file is not bytes");
      if ((await sha256Hex(files[q])) !== want[q]) throw new Refused("files", "the files are not exactly the release's");
    }
    var listed = await acceptList(revocations, t);
    await acceptHeldList(heldList, revocations !== null && revocations !== undefined ? revocations[0] : null, listed);
    var latest = new Map();
    listed.forEach(function (e) {
      var kind = Object.keys(e.target)[0];
      latest.set(kind + " " + e.target[kind], e);
    });
    var targets = [["revoked_release", "release " + rid], ["revoked_app", "app " + app],
                   ["revoked_key", "dev_key " + release.dev_key]];
    for (var x of targets) {
      var e = latest.get(x[1]);
      if (e === undefined || e.action !== "revoke") continue;
      if (x[0] === "revoked_key" && has(e, "after_seq") && pub.seq <= e.after_seq) continue;   // before the theft
      throw new Refused(x[0], x[0] + " (" + e.ground + ", " + e.notice + ")");
    }
  }

  function checkAccept(app, release, files, log, head, certs, rootRecords, revocations, pinned, heldHead, heldList) {
    return Promise.resolve()
      .then(function () {
        return acceptSteps(app, release, files, log, head, certs, rootRecords, revocations, pinned, heldHead, heldList);
      })
      .then(function () { return { ok: true, code: null, detail: "accepted" }; }, function (e) {
        if (e instanceof Refused) return { ok: false, code: e.code, detail: e.detail };
        if (e instanceof Malformed || e instanceof RecordError || e instanceof TypeError || e instanceof RangeError) {
          return { ok: false, code: "malformed", detail: "an argument is not the shape the check needs" };
        }
        throw e;                                                  // no crypto.subtle: not a verdict
      });
  }

  var api = {
    V: V, CONTEXT: CONTEXT, GENESIS: GENESIS, MAX_INT: MAX_INT, REKEY_DELAY: REKEY_DELAY, GROUNDS: GROUNDS,
    PASS_KINDS: PASS_KINDS, LOG_KINDS: LOG_KINDS, SMALL_ORDER: SMALL_ORDER.slice(), isPublicKey: point, KINDS: Object.keys(KINDS), SIGNER: SIGNER, TIME_FIELD: TIME_FIELD,
    RecordError: RecordError, canonical: canonical, canonicalText: canonicalText, signedMessage: signedMessage,
    recordId: recordId, parse: parse, check: check, rekeyRequest: rekeyRequest, toSeconds: toSeconds,
    PAGE_SIZE: PAGE_SIZE, paginate: paginate, checkList: checkList, checkExtends: checkExtends,
    verify: verify, checkAccept: checkAccept
  };

  var bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var ns = bollardeck.popsnip || (bollardeck.popsnip = {});
  Object.keys(api).forEach(function (k) { ns[k] = api[k]; });
  (bollardeck.parts || (bollardeck.parts = {})).popsnip = true;
  if (typeof module === "object" && module.exports) module.exports = ns;
})(typeof globalThis !== "undefined" ? globalThis : this);
