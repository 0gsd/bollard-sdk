// SPDX-License-Identifier: Apache-2.0
/*
 * bollardeck.matrix: the frame engine of the device's 13 x 8 LED matrix and its three RGB LEDs.
 *
 * A pure engine: every frame is a function of its arguments, with no clock, no DOM and no canvas,
 * so a page calls it from its own render loop and Node runs it in tests. The optional canvas
 * renderer is bollardeck.matrix.canvas, in bollardeck.dom.js.
 *
 * The device runs the same engine in Python (bollardeck.matrix): conformance/matrix/ holds
 * inputs with the frames that engine makes for them, and tests/js/ requires this file to make
 * the same bytes. Arithmetic is kept to what IEEE doubles do identically in both
 * languages (+ - * / floor sqrt and 32-bit integer hashing; a fixed polynomial for sine).
 *
 * A frame is {pixels: [104 x 0..255, row-major, 13 wide, row 0 at the top],
 *             rgb: [[r, g, b] LED1, [r, g, b] LED3, [r, g, b] LED4]}.
 *
 *   film(song, tMs, calm)             the making-of film at film time tMs; song carries
 *                                     drama.shots, song_id (or title) and bpm
 *   playback(song, posS, calm)        playback at posS seconds: song.notes are
 *                                     [t, dur, channel, pitch, velocity], with song.parts and bpm
 *   idle(tMs, calm, temperament)      the breathing heart, shaped by an optional temperament
 *   corpus(tMs, level, bands, calm)   a spinning record and a five-bar level meter
 *   glyph(name, tMs, calm)            one of GLYPHS: boot, low_battery, update, composing, heart
 *   dj(seg, posS, tMs, calm)          two platters, crossfader, key, judges, riser and drop for a
 *                                     mix segment, posS seconds into it; tMs is the scene clock
 *   text(text, tMs, loop, priority, ttlMs, calm)   5 x 7 text: centred if it fits, else scrolled
 *   premiere(number, tMs, opened, calm, tier)      a series box waiting, or bursting open
 *   tone(frame, tone)                 a brightness curve and RGB tint applied to any frame
 *   toHex(frame), fromHex(hex), toBytes(frame), ascii(frame)
 *
 * calm = true on any of them is reduced motion: shots hold still, no flashes, no breathing.
 * Numbers may arrive as decimal strings; text must be a string. Anything malformed is read as
 * absent, never thrown. conformance/matrix/ pins it.
 */
(function (root) {
  "use strict";
  var W = 13, H = 8, N = 104, FRAME_BYTES = 113, TICK_MS = 90;
  var PI = 3.141592653589793, TAU = 6.283185307179586;

  var PALETTE = {
    1: [0xFF, 0x2A, 0x85], 2: [0xFF, 0x77, 0xFF], 3: [0x00, 0x55, 0xFF], 4: [0x00, 0xE5, 0xFF],
    5: [0xFF, 0xE6, 0x00], 6: [0xFF, 0x55, 0x00], 7: [0xB3, 0x66, 0xFF], 8: [0xFF, 0xCC, 0x00],
    9: [0x33, 0xFF, 0xCC], 10: [0xFF, 0xFF, 0xFF], 11: [0xFF, 0x88, 0x44], 12: [0x44, 0xFF, 0x66],
    13: [0x77, 0x88, 0xFF], 14: [0xFF, 0xAA, 0x33], 15: [0x00, 0xFF, 0xAA], 16: [0xFF, 0x00, 0x44]
  };
  var COLS = [[3], [10], [4], [11], [5], [6], [1], [2], [7, 13], [8, 12], [9, 14], [15], [16]];
  var CH_COL = {};
  COLS.forEach(function (g, c) { g.forEach(function (ch) { CH_COL[ch] = c; }); });
  var KICK = [35, 36], SNARE = [37, 38, 39, 40];
  var JUDGE_THRESHOLDS = [0.78, 0.72, 0.74, 0.75, 0.72, 0.70, 0.78];
  var KIND_RGB = {
    __proto__: null,
    JAM: [0, 120, 255], VOTE: [255, 190, 0], LOCK: [0, 255, 90], DUEL: [255, 42, 133],
    TRIBUNAL: [255, 120, 0], CROSS: [255, 30, 40], LIBRARY: [255, 160, 60],
    MUTATION: [179, 102, 255], LEITMOTIF: [255, 42, 133], TITLE_CARD: [200, 200, 255],
    MOVEMENT_CARD: [255, 210, 63], PAN: [0, 229, 255], CREDITS: [220, 220, 255],
    INTERMISSION: [200, 0, 30], OVERDUB: [180, 100, 255]
  };
  var DEFAULT_RGB = [120, 120, 255];

  var FONT_SRC = "A25755B65656C34443D65556E74647F74644G34553H55755I72227J11152K55655L44447M57755" +
    "N65555O25552P65644Q25563R65655S34216T72222U55557V55552W55775X55255Y55222Z71247" +
    "075557126227261247361216455711574616634757771122875757975716" +
    ".00002,00024:02020!22202?61202-00700'22000/11244&25253+02720#57575(12221)42224*05250";
  var FONT = Object.create(null);
  for (var fi = 0; fi < FONT_SRC.length; fi += 6) {
    FONT[FONT_SRC.charAt(fi)] = FONT_SRC.substr(fi + 1, 5).split("").map(Number);
  }

  var HEART = [[3, 1], [4, 1], [8, 1], [9, 1],
    [2, 2], [3, 2], [4, 2], [5, 2], [7, 2], [8, 2], [9, 2], [10, 2],
    [2, 3], [3, 3], [4, 3], [5, 3], [6, 3], [7, 3], [8, 3], [9, 3], [10, 3],
    [3, 4], [4, 4], [5, 4], [6, 4], [7, 4], [8, 4], [9, 4],
    [4, 5], [5, 5], [6, 5], [7, 5], [8, 5],
    [5, 6], [6, 6], [7, 6],
    [6, 7]];
  var CHECK = [[2, 4], [3, 5], [4, 6], [5, 5], [6, 4], [7, 3], [8, 2], [9, 1], [10, 0]];
  var FIGURE = [[1, 0], [0, 1], [1, 1], [2, 1], [1, 2], [0, 3], [2, 3], [0, 4], [2, 4]];
  var NOTE_GLYPH = [[2, 0], [2, 1], [2, 2], [2, 3], [0, 3], [1, 3], [0, 4], [1, 4]];
  var DEFAULT_TEAMS = [[1, 3, 5, 10], [2, 4, 8, 12], [6, 7, 11, 15], [9, 13, 14, 16]];
  var GLYPHS = ["boot", "low_battery", "update", "composing", "heart"];

  // ── deterministic helpers (the same as in bollardeck.matrix) ────────────────────────────────

  function mix(x) {
    x = x >>> 0;
    x = (x ^ (x >>> 16)) >>> 0;
    x = Math.imul(x, 0x7feb352d) >>> 0;
    x = (x ^ (x >>> 15)) >>> 0;
    x = Math.imul(x, 0x846ca68b) >>> 0;
    x = (x ^ (x >>> 16)) >>> 0;
    return x;
  }

  function h32() {
    var h = 0x811c9dc5;
    for (var i = 0; i < arguments.length; i++) h = Math.imul((h ^ (arguments[i] >>> 0)) >>> 0, 0x01000193) >>> 0;
    return mix(h);
  }

  var encoder = typeof TextEncoder !== "undefined" ? new TextEncoder() : null;
  function utf8(s) {
    if (encoder) return encoder.encode(s);
    var b = unescape(encodeURIComponent(s)), out = [];
    for (var i = 0; i < b.length; i++) out.push(b.charCodeAt(i));
    return out;
  }

  function strSeed(s) {
    var h = 0x811c9dc5, bytes = utf8(String(s));
    for (var i = 0; i < bytes.length; i++) h = Math.imul((h ^ bytes[i]) >>> 0, 0x01000193) >>> 0;
    return mix(h);
  }

  function songSeed(song) { return strSeed(or(or(song.song_id, song.title), "")); }

  // A number the way the device reads one (Python's float()): numbers
  // and booleans as they are, and a string only when it is a plain decimal ("12", " 3.5 ", "1e3",
  // "1_000"). Not "0x10", which JavaScript alone would read as 16. Anything else is `d`.
  // Python strips two different sets: float() the ASCII blanks and the non-ASCII spaces, str.strip()
  // those and the four separators U+001C to U+001F.
  var SPACES = "\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
  var FLOAT_WS = "[\\t-\\r " + SPACES + "]*", STRIP_WS = "[\\t-\\r\\x1c-\\x20" + SPACES + "]*";
  var FLOAT_RE = new RegExp("^" + FLOAT_WS + "([+-]?(\\d+(_\\d+)*\\.?(\\d+(_\\d+)*)?|\\.\\d+(_\\d+)*)([eE][+-]?\\d+(_\\d+)*)?)" + FLOAT_WS + "$");
  var STRIP_RE = new RegExp("^" + STRIP_WS + "|" + STRIP_WS + "$", "g");
  function num(v, d) {
    var x;
    if (typeof v === "number") x = v;
    else if (typeof v === "boolean") x = v ? 1 : 0;
    else if (typeof v === "string" && FLOAT_RE.test(v)) x = +FLOAT_RE.exec(v)[1].replace(/_/g, "");
    else return d;
    return isFinite(x) ? x : d;
  }
  function int_(v) { return Math.floor(num(v, 0)); }
  function truthy(v) {
    if (Array.isArray(v)) return v.length > 0;
    if (v && typeof v === "object") return Object.keys(v).length > 0;
    return !!v;
  }
  function or(v, d) { return truthy(v) ? v : d; }
  function obj(v) { return (v && typeof v === "object" && !Array.isArray(v)) ? v : {}; }
  function list(v) { return Array.isArray(v) ? v : []; }
  function mod(a, n) { return a - n * Math.floor(a / n); }
  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
  function clamp01(x) { return x < 0 ? 0 : (x > 1 ? 1 : x); }
  function smooth(x) { x = clamp01(x); return x * x * (3 - 2 * x); }

  function sin(x) {
    x = x - TAU * Math.floor(x / TAU + 0.5);
    if (x > PI / 2) x = PI - x;
    else if (x < -PI / 2) x = -PI - x;
    var x2 = x * x;
    return x * (1 + x2 * (-1 / 6 + x2 * (1 / 120 + x2 * (-1 / 5040 + x2 * (1 / 362880)))));
  }
  function cos(x) { return sin(x + PI / 2); }

  function breath(t, period) {
    var p = mod(t, period), half = period / 2;
    return smooth(p < half ? p / half : (period - p) / half);
  }

  function scale(rgb, v) {
    v = clamp(v, 0, 255);
    return [Math.floor(rgb[0] * v / 255), Math.floor(rgb[1] * v / 255), Math.floor(rgb[2] * v / 255)];
  }

  function px(buf, x, y, v) {
    x = Math.floor(x);
    y = Math.floor(y);
    if (v <= 0 || x < 0 || x >= W || y < 0 || y >= H) return;
    v = Math.floor(v);
    if (v > 255) v = 255;
    var i = y * W + x;
    if (v > buf[i]) buf[i] = v;
  }

  function asc(s) {
    var out = "", chars = Array.from(String(or(s, "")));
    for (var i = 0; i < chars.length; i++) {
      var ch = chars[i], o = ch.codePointAt(0);
      if (o >= 97 && o <= 122) ch = String.fromCharCode(o - 32);
      if (FONT[ch]) out += ch;
      else if (ch === "…") out += "...";
      else if (ch === "·" || ch === "–" || ch === "—") out += "-";
      else out += " ";
    }
    return out.replace(/^ +| +$/g, "");
  }

  function text(buf, s, x0, y0, v) {
    for (var i = 0; i < s.length; i++) {
      var g = FONT[s.charAt(i)];
      if (!g) continue;
      for (var r = 0; r < 5; r++) {
        for (var c = 0; c < 3; c++) if (g[r] & (4 >> c)) px(buf, x0 + i * 4 + c, y0 + r, v);
      }
    }
  }

  function scroll(buf, s, lt, dur, y0, v, minPps, maxPps) {
    if (minPps === undefined) minPps = 12;
    if (maxPps === undefined) maxPps = 36;
    if (!s) return;
    dur = Math.max(1, dur);
    var travel = W + s.length * 4 - 1;
    if (travel * 1000 / dur > maxPps) {
      var maxLen = Math.floor((Math.floor(dur * maxPps / 1000) - W + 1) / 4);
      s = s.slice(0, Math.max(1, maxLen));
      travel = W + s.length * 4 - 1;
    }
    var off;
    if (travel * 1000 / dur < minPps) off = mod(Math.floor(lt * minPps / 1000), travel);
    else off = Math.floor(lt * travel / dur);
    text(buf, s, W - off, y0, v);
  }

  function sprite(buf, pts, x0, y0, v) {
    for (var i = 0; i < pts.length; i++) px(buf, x0 + pts[i][0], y0 + pts[i][1], v);
  }

  function firstChar(s) {
    for (var i = 0; i < s.length; i++) if (s.charAt(i) !== " ") return s.charAt(i);
    return "?";
  }

  function notes2(v) {
    var out = [];
    list(v).forEach(function (n) { if (Array.isArray(n) && n.length >= 2) out.push([int_(n[0]), int_(n[1])]); });
    return out;
  }

  function pal(ch) { return PALETTE[ch] || DEFAULT_RGB; }
  function has(arr, x) { return arr.indexOf(x) >= 0; }
  function zeros() { var b = new Array(N); for (var i = 0; i < N; i++) b[i] = 0; return b; }
  function frame(buf, rgb) { return { pixels: buf, rgb: rgb }; }

  // ── the film ──────────────────────────────────────────────────────────────────────────────

  function rJam(buf, shot, lt, dur, cx) {
    var a = obj(shot.actors);
    var chans = list(a.channels).map(int_);
    if (!chans.length) { chans = []; for (var q = 1; q <= 16; q++) chans.push(q); }
    var study = int_(a.study);
    var benched = list(a.benched).map(int_);
    var bi = cx.beat_i, ph = cx.beat_ph;
    for (var c = 0; c < W; c++) {
      var group = COLS[c];
      var on = group.filter(function (ch) { return has(chans, ch); });
      if (on.length) {
        var target = 3 + h32(cx.seed, 11, on[0], bi) % 5;
        if (bi % 4 === 0) target += 1;
        var hgt = clamp(target - Math.floor(ph * 3), 1, 8);
        for (var k = 0; k < hgt; k++) px(buf, c, 7 - k, k === hgt - 1 ? 255 : 150);
      } else if (has(group, study)) {
        if (Math.floor(cx.tick / 6) % 2 === 0) px(buf, c, 0, 90);
      } else if (group.filter(function (ch) { return has(benched, ch); }).length) {
        px(buf, c, 7, 40);
      }
    }
    var c3 = chans[0];
    var c4 = chans.length > 1 ? chans[1] : chans[0];
    return [scale(pal(c3), 200), scale(pal(c4), 120 + Math.floor(135 * (1 - ph)))];
  }

  function rVote(buf, shot, lt, dur, cx) {
    var d = obj(shot.data), j, k;
    var scores = list(d.scores).map(function (x) { return num(x, 0); }).slice(0, 7);
    while (scores.length < 7) scores.push(0);
    var lamps = list(d.lamps).map(int_).slice(0, 7);
    while (lamps.length < 7) lamps.push(0);
    if (!scores.some(function (s) { return s > 0; })) {
      scores = [];
      for (j = 0; j < 7; j++) scores.push(lamps[j] ? JUDGE_THRESHOLDS[j] + 0.08 : JUDGE_THRESHOLDS[j] - 0.22);
    }
    var rise = smooth(lt / Math.max(1, dur * 0.45));
    var verdict = lt >= dur * 0.55;
    var yes = 0;
    for (j = 0; j < 7; j++) {
      var x = 2 * j;
      var ty = 8 - Math.floor(JUDGE_THRESHOLDS[j] * 8 + 0.5);
      px(buf, x, ty, 70);
      if (j < 6) px(buf, x + 1, ty, 45);
      var hgt = Math.floor(clamp01(scores[j]) * 8 * rise + 0.5);
      var val = 160;
      if (lamps[j]) yes += 1;
      if (verdict) val = lamps[j] ? 255 : ((cx.calm || cx.tick % 4 < 2) ? 90 : 40);
      for (k = 0; k < hgt; k++) px(buf, x, 7 - k, k === hgt - 1 ? val : val * 0.7);
    }
    return [scale([0, 255, 90], yes * 36), scale([255, 30, 40], (7 - yes) * 36)];
  }

  function rLock(buf, shot, lt, dur, cx) {
    var x, y, k;
    if (lt < 400) {
      var r = lt / 400 * 8;
      var fade = 255 - lt / 400 * 120;
      for (y = 0; y < H; y++) {
        for (x = 0; x < W; x++) {
          var dx2 = 2 * x - 12, dy2 = 2 * y - 7;
          var dist = Math.sqrt(dx2 * dx2 + dy2 * dy2) / 2;
          if (Math.abs(dist - r) < 0.75) px(buf, x, y, fade);
        }
      }
    }
    if (lt >= 250) {
      var n = Math.floor((lt - 250) / 45) + 1;
      for (k = 0; k < CHECK.length; k++) {
        if (k < n) {
          px(buf, CHECK[k][0], CHECK[k][1], 255);
          px(buf, CHECK[k][0], CHECK[k][1] + 1, 70);
        }
      }
      if (n > CHECK.length && !cx.calm) {
        for (var j = 0; j < 4; j++) {
          var hh = h32(cx.seed, 31, j, Math.floor(cx.tick / 2));
          if (hh % 3 === 0) px(buf, (hh >>> 4) % W, (hh >>> 8) % H, 140);
        }
      }
    }
    return [scale([0, 255, 90], 255), scale([0, 255, 90], 140)];
  }

  function rDuel(buf, shot, lt, dur, cx) {
    var a = obj(shot.actors), d = obj(shot.data);
    var lead = int_(a.lead) || 1;
    var rival = int_(a.rival) || 2;
    var ln = notes2(d.lead_notes), rn = notes2(d.rival_notes);
    var winner = int_(d.winner);
    var q = dur / 4;
    var end = lt >= dur * 0.82;
    var k = Math.min(3, Math.floor(lt / q));
    var pt = lt - k * q;
    var leadPlaying = k % 2 === 0;
    var hopL = 0, hopR = 0, i;
    if (!end) {
      var now = leadPlaying ? ln : rn;
      if (now.length) {
        var lo = now[0][1], hi = now[0][1];
        for (i = 1; i < now.length; i++) { if (now[i][1] < lo) lo = now[i][1]; if (now[i][1] > hi) hi = now[i][1]; }
        for (i = 0; i < now.length; i++) {
          var n = now[i];
          var nt = n[0] / 32 * q * 0.7;
          var age = pt - nt;
          if (age < 0 || age >= 700) continue;
          var y = 6 - Math.floor((n[1] - lo) * 5 / Math.max(1, hi - lo));
          var step = Math.floor(age / 100);
          var x = leadPlaying ? 3 + step : 9 - step;
          px(buf, x, y, 255);
          if (step > 0) px(buf, leadPlaying ? x - 1 : x + 1, y, 90);
          if (age < 120) { if (leadPlaying) hopL = 1; else hopR = 1; }
        }
      }
    }
    var valL = leadPlaying ? 220 : 140;
    var valR = leadPlaying ? 140 : 220;
    if (end) {
      var winL = winner === lead;
      var blink = cx.calm || cx.tick % 4 < 2;
      valL = winL ? (blink ? 255 : 160) : 50;
      valR = winL ? 50 : (blink ? 255 : 160);
    }
    sprite(buf, FIGURE, 0, 3 - hopL, valL);
    sprite(buf, FIGURE, 10, 3 - hopR, valR);
    return [scale(pal(lead), valL), scale(pal(rival), valR)];
  }

  function rTribunal(buf, shot, lt, dur, cx) {
    var d = obj(shot.data);
    var ang = 0.6, hit = -1, last = 0, x, y, k;
    [0.25, 0.47, 0.69].forEach(function (f) {
      var ts = dur * f;
      last = ts;
      if (ts - 160 <= lt && lt < ts) ang = 0.6 * (ts - lt) / 160;
      else if (ts <= lt && lt < ts + 140) ang = 0;
      else if (ts + 140 <= lt && lt < ts + 400) ang = 0.6 * (lt - ts - 140) / 260;
      if (0 <= lt - ts && lt - ts < 250) hit = lt - ts;
    });
    var ca = cos(ang), sa = sin(ang);
    for (y = 0; y < H; y++) {
      for (x = 0; x < W; x++) {
        var vx = x - 1, vy = y - 4;
        var s = vx * ca - vy * sa;
        var perp = vx * sa + vy * ca;
        if (s >= 6 && s <= 8 && perp >= -2 && perp <= 2) px(buf, x, y, 240);
        else if (s >= 0 && s <= 6 && perp >= -0.5 && perp <= 0.5) px(buf, x, y, 170);
      }
    }
    for (x = 6; x < 11; x++) px(buf, x, 7, hit >= 0 ? 255 : 110);
    if (hit >= 0 && !cx.calm) {
      for (k = 1; k < 4; k++) {
        if (hit >= (k - 1) * 60) {
          px(buf, 6 - k, 7, 200 - k * 50);
          px(buf, 10 + k, 7, 200 - k * 50);
        }
      }
    }
    var lock = String(or(d.majority, "")) === "LOCK";
    if (lt >= last + 300 && (cx.calm || cx.tick % 4 < 3)) {
      var pts = lock ? [[0, 1], [1, 2], [2, 1], [3, 0]] : [[0, 0], [2, 0], [1, 1], [0, 2], [2, 2]];
      sprite(buf, pts, 0, 0, 255);
    }
    return [scale([255, 210, 63], hit >= 0 ? 220 : 90), scale(lock ? [0, 255, 90] : [255, 30, 40], 150)];
  }

  function rCross(buf, shot, lt, dur, cx) {
    var a = obj(shot.actors), d = obj(shot.data);
    var musician = int_(a.musician) || 1;
    var benched = String(or(d.verdict, "")) === "BENCHED";
    var qd = dur * 0.78 / 3;
    for (var x = 0; x < 4; x++) px(buf, x, 5, 90);
    sprite(buf, FIGURE, 0, 0, 200);
    var mv = 200, my = 3;
    if (lt < dur * 0.78) {
      var i = Math.min(2, Math.floor(lt / qd));
      var u = (lt - i * qd) / qd;
      if (u < 0.75) text(buf, "?", 3 + Math.floor(u * 5), 1, 220);
      if (u >= 0.7 && u < 0.85) mv = 255;
    } else {
      var e = (lt - dur * 0.78) / Math.max(1, dur * 0.22);
      if (benched) {
        my = 3 + Math.floor(clamp01(e) * 5);
        mv = 200 - clamp01(e) * 140;
      } else if (cx.calm || cx.tick % 4 < 2) {
        text(buf, "!", 6, 1, 255);
      }
    }
    sprite(buf, FIGURE, 10, my, mv);
    return [scale([255, 210, 63], 200), scale(pal(musician), mv)];
  }

  function rLibrary(buf, shot, lt, dur, cx) {
    var a = obj(shot.actors), d = obj(shot.data), x, y;
    var w = Math.floor(smooth(lt / Math.max(1, dur * 0.25)) * 5 + 0.5);
    for (y = 2; y < 7; y++) px(buf, 6, y, 200);
    if (w === 0) {
      for (y = 2; y < 7; y++) {
        for (x = 4; x < 9; x++) if (y === 2 || y === 6 || x === 4 || x === 8) px(buf, x, y, 150);
      }
    } else {
      for (y = 2; y < 7; y++) {
        for (x = 6 - w; x < 7 + w; x++) {
          if (x === 6) continue;
          if (y === 2 || y === 6 || x === 6 - w || x === 6 + w) px(buf, x, y, 150);
          else if ((y === 3 || y === 5) && (x + y) % 2 === 0) px(buf, x, y, 50);
        }
      }
      if (w === 5 && lt >= dur * 0.35) {
        var fp = mod(lt - dur * 0.35, 1100);
        if (fp < 450) {
          var fx = 11 - Math.floor(fp / 450 * 11);
          for (y = 2; y < 7; y++) px(buf, fx, y, 230);
        }
      }
    }
    var cur16 = mod(Math.floor(cx.t * cx.bpm / 15000), 16);
    list(d.steps).map(int_).slice(0, 8).forEach(function (st) {
      px(buf, Math.floor(mod(st, 16) * 13 / 16), 7, mod(st, 16) === cur16 ? 255 : 110);
    });
    var musician = int_(a.musician) || 1;
    return [scale(pal(musician), 200), scale([255, 160, 60], 120)];
  }

  function rMutation(buf, shot, lt, dur, cx) {
    var a = obj(shot.actors);
    var judge = String(or(a.who, "")) === "judge";
    var ch = judge ? 17 + int_(a.judge) : (int_(a.channel) || 1);
    var oc = firstChar(asc(a.old)), nc = firstChar(asc(a["new"]));
    var p = lt / Math.max(1, dur);
    var tick = cx.tick;
    var dens = clamp01(1 - Math.abs(p - 0.5) * 2.5);
    if (cx.calm) dens = 0;
    var letter = p < 0.5 ? oc : nc;
    var drop = dens * 160;
    var g = FONT[letter], r, c, i;
    if (g) {
      for (r = 0; r < 5; r++) {
        var shift = (dens > 0.2 && h32(cx.seed, 43, ch, tick, r) % 7 === 0) ? 1 : 0;
        for (c = 0; c < 3; c++) {
          if (g[r] & (4 >> c)) {
            if (drop === 0 || h32(cx.seed, 41, ch, tick, r * 3 + c) % 256 >= drop) px(buf, 5 + c + shift, 1 + r, p >= 0.8 ? 255 : 200);
          }
        }
      }
    }
    if (dens > 0) {
      for (i = 0; i < N; i++) {
        var hh = h32(cx.seed, 47, ch, tick, i);
        if (hh % 256 < dens * 90) px(buf, i % W, Math.floor(i / W), 40 + (hh >>> 8) % 160);
      }
    }
    var col = judge ? [255, 210, 63] : pal(ch);
    var out3 = scale(col, 220);
    var out4 = scale(col, 60 + Math.floor(dens * 195));
    if (cx.calm) return [out3, out4];
    return [out3, out4, scale(pal(1 + h32(cx.seed, 53, tick) % 16), 200)];
  }

  function rLeitmotif(buf, shot, lt, dur, cx) {
    var d = obj(shot.data), i, x;
    var steps = list(d.steps).map(int_).slice(0, 8);
    var rels = list(d.rels).map(int_).slice(0, 8);
    var n = Math.min(steps.length, rels.length);
    if (n < 2) {
      steps = [0, 2, 4, 6, 8, 10, 12, 14];
      rels = [0, 4, 7, 9, 7, 4, 2, 0];
      n = 8;
    }
    var xs = [], ys = [], lo = rels[0], hi = rels[0];
    for (i = 0; i < n; i++) {
      xs.push(clamp(Math.floor(mod(steps[i], 16) * 12 / 15), 0, 12));
      if (rels[i] < lo) lo = rels[i];
      if (rels[i] > hi) hi = rels[i];
    }
    for (i = 0; i < n; i++) ys.push(6 - Math.floor((rels[i] - lo) * 5 / Math.max(1, hi - lo)));
    var cycle = Math.max(1, dur / 2);
    var hx = Math.floor(mod(lt, cycle) / cycle * 13);
    for (i = 0; i < n; i++) px(buf, xs[i], ys[i], 60);
    for (i = 0; i < n - 1; i++) {
      var x0 = xs[i], x1 = xs[i + 1];
      if (x0 === x1) continue;
      for (x = Math.min(x0, x1); x < Math.max(x0, x1) + 1; x++) {
        if (x <= hx) px(buf, x, ys[i] + Math.floor((ys[i + 1] - ys[i]) * (x - x0) / (x1 - x0) + 0.5), 110);
      }
    }
    for (i = 0; i < n; i++) if (xs[i] <= hx) px(buf, xs[i], ys[i], 255);
    px(buf, hx, 0, 60);
    px(buf, hx, 7, 60);
    return [scale(pal(1), 220), scale(pal(2), 90)];
  }

  function stars(buf, cx, count) {
    for (var j = 0; j < count; j++) {
      var hh = h32(cx.seed, 61, j);
      var tw = (cx.tick + j * 3) % 8;
      px(buf, hh % W, j % 2 === 0 ? 0 : 7, tw < 2 ? 200 : 60);
    }
  }

  function rTitle(buf, shot, lt, dur, cx) {
    scroll(buf, asc(shot.title), lt, dur, 1, 255);
    stars(buf, cx, 5);
    return [scale(pal(1), 140), scale(pal(2), 140)];
  }

  function rMovement(buf, shot, lt, dur, cx) {
    var d = obj(shot.data);
    var s = asc(d.numeral) || String(int_(shot.movement));
    var tw = s.length * 4 - 1;
    if (tw <= W) text(buf, s, Math.floor((W - tw) / 2), 1, 255 * Math.min(1, lt / 300));
    else scroll(buf, s, lt, dur, 1, 255);
    var bpm = num(d.bpm, 0) || cx.bpm;
    var b = lt * bpm / 60000;
    var bi = Math.floor(b);
    var m = mod(bi, 24);
    px(buf, m <= 12 ? m : 24 - m, 7, b - bi < 0.3 ? 220 : 90);
    var mv = int_(shot.movement);
    return [scale(pal(1 + mod(mv, 16)), 180), scale([255, 210, 63], 120)];
  }

  function rPan(buf, shot, lt, dur, cx) {
    var a = obj(shot.actors), d = obj(shot.data), x, y;
    var teams = list(a.teams).filter(function (t) { return t && typeof t === "object" && !Array.isArray(t); })
      .map(function (t) { return list(t.members).map(int_).slice(0, 4); }).slice(0, 4);
    if (!teams.length) teams = DEFAULT_TEAMS.map(function (t) { return t.slice(); });
    var fr = clamp(int_(d.from), 0, 3);
    var to = clamp(int_(d.to), 0, 3);
    var u = smooth((lt / Math.max(1, dur) - 0.15) / 0.7);
    var vx = Math.floor((fr * 8 - 3) + (to * 8 - fr * 8) * u + 0.5);
    var offs = [1, 2, 4, 5];
    for (var s = 0; s < teams.length; s++) {
      var base = s * 8 - vx;
      for (y = 3; y < 8; y++) { px(buf, base, y, 70); px(buf, base + 6, y, 70); }
      for (x = 0; x < 7; x++) px(buf, base + x, 7, 70);
      for (var m = 0; m < teams[s].length; m++) {
        var ch = teams[s][m];
        var hop = (h32(cx.seed, 71, ch, cx.beat_i) % 3 === 0 && cx.beat_ph < 0.5) ? 1 : 0;
        x = base + offs[m];
        px(buf, x, 4 - hop, 255);
        px(buf, x, 5 - hop, 170);
        px(buf, x, 6 - hop, 120);
      }
    }
    return [scale([0, 229, 255], 160), scale([0, 85, 255], 160)];
  }

  function rIntermission(buf, shot, lt, dur, cx) {
    var p = lt / Math.max(1, dur), c, x, y;
    if (p < 0.2) c = smooth(p / 0.2);
    else if (p > 0.85) c = 1 - smooth((p - 0.85) / 0.15);
    else c = 1;
    var w = Math.floor(c * 7 + 0.5);
    var sway = Math.floor(lt / 500);
    for (x = 0; x < w; x++) {
      var v = (x + sway) % 2 === 0 ? 150 : 85;
      for (y = 1; y < 8; y++) { px(buf, x, y, v); px(buf, 12 - x, y, v); }
    }
    for (x = 0; x < W; x++) px(buf, x, 0, 220);
    return [scale([200, 0, 30], 200), scale([255, 210, 63], 80)];
  }

  function rCredits(buf, shot, lt, dur, cx) {
    var d = obj(shot.data), parts = [];
    list(d.lines).forEach(function (ln) {
      if (Array.isArray(ln) && ln.length >= 2 && ["h", "g", "t"].indexOf(String(ln[0])) >= 0) {
        var s = asc(ln[1]);
        if (s) parts.push(s);
      }
    });
    var t = parts.join("   ") || asc(shot.title) || "THE END";
    scroll(buf, t, lt, dur, 1, 255, 12, 40);
    var tick = cx.tick;
    for (var x = 0; x < W; x++) {
      if (mod(x + tick, 4) === 0) px(buf, x, 7, 60);
      if (mod(x - tick, 4) === 0) px(buf, x, 0, 60);
    }
    return [scale([220, 220, 255], 120), scale([255, 210, 63], 120)];
  }

  function rOverdub(buf, shot, lt, dur, cx) {
    var d = obj(shot.data);
    var props = list(d.proposals).filter(function (p) { return p && typeof p === "object" && !Array.isArray(p); }).slice(0, 6);
    if (!props.length) props = [{ m_yes: 8, m_total: 16, j_yes: 4, j_total: 7, passed: true }];
    var n = props.length;
    var slot = Math.max(1, dur / n);
    var i = Math.min(n - 1, Math.floor(lt / slot));
    var u = (lt - i * slot) / slot;
    var pr = props[i];
    var my = num(pr.m_yes, 0);
    var mt = Math.max(1, num(pr.m_total, 16));
    var jy = num(pr.j_yes, 0);
    var jt = Math.max(1, num(pr.j_total, 7));
    var grow = smooth(u / 0.5);
    var mw = Math.floor(my * 13 / mt * grow + 0.5);
    var jw = Math.floor(jy * 13 / jt * grow + 0.5);
    var passed = truthy(pr.passed);
    var val = 200;
    if (u >= 0.6) val = passed ? ((cx.calm || cx.tick % 3 !== 0) ? 255 : 120) : 60;
    for (var x = 0; x < W; x++) {
      if (x % 2 === 0) px(buf, x, 2, 40);
      if (x < mw) { px(buf, x, 0, val); px(buf, x, 1, val); }
      if (x < jw) { px(buf, x, 4, val); px(buf, x, 5, val); }
    }
    for (var k = 0; k < n; k++) px(buf, k * 2, 7, k === i ? 255 : 60);
    return [scale(passed ? [0, 255, 90] : [255, 30, 40], 60 + Math.floor(u * 195)), scale([180, 100, 255], 120)];
  }

  function rDefault(buf, shot, lt, dur, cx) {
    for (var j = 0; j < 6; j++) {
      var hh = h32(cx.seed, 91, j, Math.floor(cx.tick / 3));
      px(buf, hh % W, (hh >>> 8) % H, 120);
    }
    return null;
  }

  var RENDERERS = {
    __proto__: null,
    JAM: rJam, VOTE: rVote, LOCK: rLock, DUEL: rDuel, TRIBUNAL: rTribunal, CROSS: rCross,
    LIBRARY: rLibrary, MUTATION: rMutation, LEITMOTIF: rLeitmotif, TITLE_CARD: rTitle,
    MOVEMENT_CARD: rMovement, PAN: rPan, INTERMISSION: rIntermission, CREDITS: rCredits, OVERDUB: rOverdub
  };

  function shotAt(starts, t) {
    var lo = 0, hi = starts.length - 1;
    while (lo < hi) {
      var mid = (lo + hi + 1) >> 1;
      if (starts[mid] <= t) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  var reels = typeof WeakMap !== "undefined" ? new WeakMap() : null;
  function filmReel(song) {
    var raw = list(obj(obj(song).drama).shots);
    if (reels && reels.has(raw)) return reels.get(raw);
    var shots = raw.filter(function (s) { return s && typeof s === "object" && !Array.isArray(s); });
    var starts = [], acc = 0;
    for (var k = 0; k < shots.length; k++) { starts.push(acc); acc += Math.max(0, num(shots[k].duration_ms, 0)); }
    var out = { shots: shots, starts: starts, total: Math.max(1, acc) };
    if (reels) reels.set(raw, out);
    return out;
  }

  function film(song, tMs, calm) {
    song = obj(song);
    var reel = filmReel(song);
    if (!reel.shots.length) return idle(tMs, calm);
    var t = Math.floor(num(tMs, 0));
    t = Math.max(0, Math.min(t, reel.total - 1));
    var i = shotAt(reel.starts, t);
    var shot = reel.shots[i];
    var dur = Math.max(1, num(shot.duration_ms, 0));
    var lt = t - reel.starts[i];
    if (calm) lt = Math.floor(dur * 0.6);
    var tt = reel.starts[i] + lt;
    var bpm = num(song.bpm, 0) || 120;
    var b = tt * bpm / 60000;
    var bi = Math.floor(b);
    var cx = { seed: songSeed(song), bpm: bpm, t: tt, tick: Math.floor(tt / TICK_MS), beat_i: bi, beat_ph: b - bi,
      calm: !!calm, index: i };
    var buf = zeros();
    var kind = String(or(shot.kind, ""));
    var leds = (RENDERERS[kind] || rDefault)(buf, shot, lt, dur, cx);
    var col = KIND_RGB[kind] || DEFAULT_RGB;
    var led1 = scale(col, calm ? 180 : 90 + Math.floor(165 * (1 - cx.beat_ph)));
    if (!leds) leds = [scale(col, 60), scale(col, 60)];
    if (leds.length > 2) led1 = leds[2];
    return frame(buf, [led1, leds[0], leds[1]]);
  }

  // ── playback ──────────────────────────────────────────────────────────────────────────────

  var noteCache = typeof WeakMap !== "undefined" ? new WeakMap() : null;
  function cleanNotes(song) {
    var raw = list(song.notes);
    if (noteCache && noteCache.has(raw)) return noteCache.get(raw);
    var clean = [];
    raw.forEach(function (n) {
      if (Array.isArray(n) && n.length >= 5) clean.push([num(n[0], 0), num(n[1], 0), int_(n[2]), int_(n[3]), int_(n[4])]);
    });
    clean.sort(function (a, b) { return a[0] - b[0]; });
    var out = { notes: clean, times: clean.map(function (n) { return n[0]; }) };
    if (noteCache) noteCache.set(raw, out);
    return out;
  }

  function upper(a, x) {
    var lo = 0, hi = a.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (x < a[mid]) hi = mid; else lo = mid + 1; }
    return lo;
  }

  function playback(song, posS, calm) {
    song = obj(song);
    var cn = cleanNotes(song), notes = cn.notes, times = cn.times;
    var pos = Math.max(0, num(posS, 0));
    var seed = songSeed(song);
    var bpm = num(song.bpm, 0) || 120;
    var lv = [], c, k, x, y;
    for (c = 0; c < W; c++) lv.push(0);
    var kick = 0, snare = 0, snareT = 0;
    var i = upper(times, pos) - 1;
    var scanned = 0;
    while (i >= 0 && scanned < 600) {
      var n = notes[i];
      var dt = pos - n[0];
      if (dt > 4.0) break;
      scanned += 1;
      i -= 1;
      c = CH_COL[n[2]];
      if (c === undefined) continue;
      var vel = n[4] / 127;
      var e = 0;
      if (dt < 0.45) e = vel * (1 - dt / 0.45);
      if (dt < n[1] && vel * 0.45 > e) e = vel * 0.45;
      if (e > lv[c]) lv[c] = e;
      if (n[2] === 10) {
        if (has(KICK, n[3]) && dt < 0.16 && 1 - dt / 0.16 > kick) kick = 1 - dt / 0.16;
        if (has(SNARE, n[3]) && dt < 0.2 && 1 - dt / 0.2 > snare) { snare = 1 - dt / 0.2; snareT = n[0]; }
      }
    }
    var buf = zeros();
    var loud = 0;
    for (c = 0; c < W; c++) {
      if (lv[c] > lv[loud]) loud = c;
      var hgt = Math.floor(Math.min(1, lv[c]) * 7 + 0.5);
      for (k = 0; k < hgt; k++) px(buf, c, 6 - k, k === hgt - 1 ? 255 : 150);
    }
    if (!calm && kick > 0) {
      for (y = 0; y < 7; y++) for (x = 0; x < W; x++) px(buf, x, y, 70 * kick);
    }
    if (!calm && snare > 0) {
      var st = Math.floor(snareT * 1000 + 0.5);
      for (var j = 0; j < 8; j++) {
        var hh = h32(seed, 77, st, j);
        px(buf, hh % W, (hh >>> 8) % 7, 220 * snare);
      }
    }
    var t0 = 0, t1 = num(song.duration, 0);
    var parts = list(song.parts);
    for (var pi = 0; pi < parts.length; pi++) {
      var p = parts[pi];
      if (p && typeof p === "object" && !Array.isArray(p)) {
        var a = num(p.t0, 0), b = num(p.t1, 0);
        if (b > a && a <= pos && pos < b) { t0 = a; t1 = b; break; }
      }
    }
    if (t1 <= t0) t1 = t0 + 1;
    var frac = clamp01((pos - t0) / (t1 - t0));
    var head = Math.min(12, Math.floor(frac * 13));
    var beat = pos * bpm / 60;
    var ph = beat - Math.floor(beat);
    for (x = 0; x < W; x++) {
      if (x < head) px(buf, x, 7, 110);
      else if (x === head) px(buf, x, 7, 255);
      else if (!calm) px(buf, x, 7, 60 * (1 - ph));
    }
    var led1 = scale(pal(1), calm ? 180 : Math.floor(60 + 195 * (1 - ph)));
    var led3 = scale(pal(COLS[loud][0]), Math.floor(255 * Math.min(1, lv[loud])));
    var led4 = calm ? [0, 0, 0] : scale([255, 255, 255], Math.floor(255 * Math.max(kick, snare)));
    return frame(buf, [led1, led3, led4]);
  }

  // ── idle, CORPUS mode and glyphs ──────────────────────────────────────────────────────────

  function idle(tMs, calm, temper) {
    var t = Math.floor(num(tMs, 0));
    if (isObj(temper) && truthy(temper)) return idleTempered(t, calm, temper);     // {} is no temperament
    var s = calm ? 1 : breath(t, 4000);
    var level = calm ? 200 : 50 + Math.floor(205 * s);
    var buf = zeros();
    sprite(buf, HEART, 0, 0, level);
    return frame(buf, [[0, 0, Math.floor(48 * s)], [0, 0, 0], [0, 0, 0]]);
  }

  // ── palettes: the idle temperament and the tone curve ────────────────────────────────────
  function temperS(shape, t, period, x) {
    if (shape === "pulse") {
      var u = mod(t, period) / period;
      var a = clamp01(1 - Math.abs(u - 0.06) / 0.06);
      var b = clamp01(1 - Math.abs(u - 0.24) / 0.06);
      return smooth(Math.max(a, b * 0.7));
    }
    if (shape === "flicker") return 0.55 + 0.45 * ((h32(Math.floor(t / TICK_MS), 0x51ce) & 255) / 255);
    if (shape === "tide") return breath(t + x * period / 26, period);
    if (shape === "sparkle") return 0.5 + 0.5 * breath(t, period);
    return breath(t, period);
  }

  function idleTempered(t, calm, temper) {
    var shape = String(or(temper.shape, "breath"));
    // A member that is absent takes its default; one that is there and null reads as 0, as on the device.
    var period = Math.max(1000, int_(temper.period !== undefined ? temper.period : 4000));
    var floor = clamp(int_(temper.floor !== undefined ? temper.floor : 50), 0, 255);
    var span = clamp(int_(temper.span !== undefined ? temper.span : 205), 0, 255 - floor);
    var src = list(temper.rgb).concat([0, 0, 0]), rgb = [];
    for (var j = 0; j < 3; j++) rgb.push(clamp(int_(src[j]), 0, 255));
    var buf = zeros();
    var s0 = calm ? 1 : temperS(shape, t, period, 6);
    for (var i = 0; i < HEART.length; i++) {
      var p = HEART[i];
      var s = (calm || shape !== "tide") ? s0 : temperS(shape, t, period, p[0]);
      px(buf, p[0], p[1], calm ? 200 : floor + Math.floor(span * s));
    }
    if (shape === "sparkle" && !calm) {
      var slot = Math.floor(t / (period / 8));
      for (var k = 0; k < 2; k++) {
        var hh = h32(slot, k, 0x5ba2);
        px(buf, hh % W, (hh >>> 8) % H, 255);
      }
    }
    return frame(buf, [[Math.floor(rgb[0] * s0), Math.floor(rgb[1] * s0), Math.floor(rgb[2] * s0)], [0, 0, 0], [0, 0, 0]]);
  }

  function toneFrame(fr, tone) {
    if (!fr || !isObj(tone)) return fr;
    var lut = tone.lut, pixels = fr.pixels.slice(), i;
    if (Array.isArray(lut) && lut.length === 256) for (i = 0; i < pixels.length; i++) pixels[i] = clamp(int_(lut[pixels[i]]), 0, 255);
    var k = clamp(int_(tone.mix || 0), 0, 256);
    var src = list(tone.tint).concat([0, 0, 0]), tint = [];
    for (i = 0; i < 3; i++) tint.push(clamp(int_(src[i]), 0, 255));
    var rgb = fr.rgb.map(function (led) {
      var m = Math.max(led[0], led[1], led[2]);
      if (!k || !m) return [led[0], led[1], led[2]];
      return [0, 1, 2].map(function (c) {
        var tr = Math.floor(tint[c] * m / 255);
        return led[c] + Math.floor((tr - led[c]) * k / 256);
      });
    });
    return frame(pixels, rgb);
  }

  function corpus(tMs, level, bands, calm) {
    var t = Math.floor(num(tMs, 0));
    var lvl = clamp(Math.floor(num(level, 0)), 0, 255);
    var buf = zeros(), x, y, j, k, v;
    var ang = calm ? 0 : t * TAU / 1800;
    var ca = cos(ang), sa = sin(ang);
    for (y = 0; y < H; y++) {
      for (x = 0; x < 7; x++) {
        var dx = x - 3, dy = y - 3.5;
        var d2 = dx * dx + dy * dy;
        if (d2 > 12.96) continue;
        v = 70;
        if (d2 < 0.8) v = 160;
        else if (dx * ca + dy * sa > 0.5 && Math.abs(dy * ca - dx * sa) < 0.6) v = 230;
        px(buf, x, y, v);
      }
    }
    var groups = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11], [12, 13, 14, 15]];
    var bl = (Array.isArray(bands) ? bands : []).map(function (b) { return clamp(Math.floor(num(b, 0)), 0, 255); });
    for (k = 0; k < 5; k++) {
      if (bl.length) {
        v = 0;
        for (var gi = 0; gi < groups[k].length; gi++) { j = groups[k][gi]; if (j < bl.length && bl[j] > v) v = bl[j]; }
      } else {
        v = lvl * (160 + h32(91, k, calm ? 0 : Math.floor(t / 120)) % 96) / 255;
      }
      var hgt = clamp(Math.floor(v * 8 / 255 + 0.5), 0, 8);
      for (j = 0; j < hgt; j++) px(buf, 8 + k, 7 - j, j === hgt - 1 ? 255 : 150);
    }
    return frame(buf, [[0, Math.floor(lvl * 0.3), lvl], scale([0, 229, 255], lvl), [0, 0, 0]]);
  }

  function glyph(name, tMs, calm) {
    var t = Math.floor(num(tMs, 0));
    name = String(or(name, ""));
    if (name === "heart") return idle(t, calm);
    var buf = zeros(), led1 = [0, 0, 0], led3 = [0, 0, 0], x, y, k;
    if (name === "boot") {
      var p = calm ? 2399 : mod(t, 2400);
      if (p < 700) {
        var c = Math.floor(p / 50);
        for (x = 0; x < W; x++) {
          var age = c - x;
          if (age >= 0 && age < 4) for (y = 0; y < H; y++) px(buf, x, y, 255 - age * 60);
        }
      } else {
        text(buf, "PB", 3, 1, 255);
        for (k = 0; k < Math.min(W, Math.floor((p - 700) / 130)); k++) px(buf, k, 7, 120);
      }
      led1 = [0, 0, 200];
      led3 = [0, 80, 200];
    } else if (name === "low_battery") {
      var on = calm || mod(Math.floor(t / 500), 2) === 0;
      for (x = 1; x < 11; x++) { px(buf, x, 2, 200); px(buf, x, 5, 200); }
      for (y = 2; y < 6; y++) { px(buf, 1, y, 200); px(buf, 10, y, 200); }
      px(buf, 11, 3, 200);
      px(buf, 11, 4, 200);
      if (on) [2, 3].forEach(function (xx) { px(buf, xx, 3, 255); px(buf, xx, 4, 255); });
      led1 = [on ? 200 : 40, 0, 0];
    } else if (name === "update") {
      var off = calm ? 0 : mod(Math.floor(t / 150), 3);
      for (y = 0; y < 3; y++) px(buf, 6, y + off, 255);
      for (x = 4; x < 9; x++) px(buf, x, 3 + off, 255);
      for (x = 5; x < 8; x++) px(buf, x, 4 + off, 255);
      for (x = 2; x < 11; x++) px(buf, x, 7, 150);
      px(buf, 2, 6, 150);
      px(buf, 10, 6, 150);
      led1 = scale([0, 160, 255], 120 + off * 60);
    } else if (name === "composing") {
      var kk = calm ? -1 : mod(Math.floor(t / 300), 3);
      for (var j = 0; j < 3; j++) sprite(buf, NOTE_GLYPH, j * 5, 2 - (j === kk ? 1 : 0), j === kk ? 255 : (calm ? 200 : 120));
      led1 = scale([0, 120, 255], calm ? 200 : 90 + Math.floor(165 * breath(t, 1800)));
    } else {
      return idle(t, calm);
    }
    return frame(buf, [led1, led3, [0, 0, 0]]);
  }

  // ── DJ mode (DJ Popstal Bollfish): a frame for one segment of a set ────────────────────────
  // row 0 the key / judges' scores / influencer comets; rows 1-6 the platters A (x 0-5) and
  // B (x 7-12) spinning one turn per bar on the segment's beat clock, the master meter (and
  // the riser) in column 6; row 7 the crossfader; a drop flashes everything.

  var DJ_DECK_RGB = { A: [255, 42, 133], B: [0, 229, 255] };
  var DJ_JUDGE_RGB = { __proto__: null, camelot: [255, 210, 63], groove: [255, 42, 133], segue: [0, 229, 255],
    weird: [179, 102, 255], floor: [0, 255, 90] };
  var DJ_KEY_RGB = [
    [255, 0, 64], [255, 80, 0], [255, 170, 0], [230, 230, 0], [130, 255, 0], [0, 255, 60],
    [0, 255, 170], [0, 200, 255], [0, 110, 255], [60, 0, 255], [160, 0, 255], [255, 0, 200]];
  var DJ_PLATTERS = [["A", 0, 2.5], ["B", 7, 9.5]];
  var DJ_PULL_MS = 700, DJ_JUDGE_MS = 1400, DJ_REVEAL_MS = 300, DJ_DROP_MS = 350;
  var DJ_KEY_GHOST_MS = 500, DJ_TUG_MS = 600;

  function isObj(v) { return !!(v && typeof v === "object" && !Array.isArray(v)); }
  function str_(v) { return String(v === null || v === undefined ? "" : v); }
  function own(o, k) { return Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined; }

  function djCamelot(v) {
    if (typeof v !== "string") return [0, ""];        // a key is a string like "8A"
    var s = v.replace(STRIP_RE, "");
    if (s.length < 2 || s.length > 3) return [0, ""];
    var letter = s.charAt(s.length - 1);
    if (letter === "a" || letter === "b") letter = String.fromCharCode(letter.charCodeAt(0) - 32);
    if (letter !== "A" && letter !== "B") return [0, ""];
    var digits = s.slice(0, s.length - 1);
    for (var i = 0; i < digits.length; i++) if ("0123456789".indexOf(digits.charAt(i)) < 0) return [0, ""];
    var n = parseInt(digits, 10);
    return (n >= 1 && n <= 12) ? [n, letter] : [0, ""];
  }

  function djTempo(seg) {
    var tp = obj(seg.tempo);
    var b0 = num(tp.bpm_start, 0) || num(tp.bpm_end, 0) || 120;
    var b1 = num(tp.bpm_end, 0) || b0;
    var ln = num(seg.duration, 0);
    var beats = num(tp.beats, 0);
    if (ln <= 0 && beats > 0) ln = 120 * beats / (b0 + b1);
    return [b0, b1, ln];
  }

  function djBeat(seg, posS) {
    var tm = djTempo(obj(seg)), b0 = tm[0], b1 = tm[1], ln = tm[2];
    var t = num(posS, 0);
    if (ln <= 0 || t <= 0) return t * b0 / 60;
    if (t >= ln) return (b0 * ln + (b1 - b0) * ln / 2) / 60 + (t - ln) * b1 / 60;
    return (b0 * t + (b1 - b0) * t * t / (2 * ln)) / 60;
  }

  function djU(ev, pos) {
    var dur = num(ev.dur, 0);
    if (dur <= 0) return 1;
    return clamp01((pos - num(ev.t, 0)) / dur);
  }

  function djSide(v) {
    var s = str_(v);
    return s === "A" ? 0 : (s === "B" ? 1 : -1);
  }

  function djLatest(evs, kind, pos) {
    var out = [];
    for (var k = 0; k < evs.length; k++) {
      var ev = evs[k];
      if (isObj(ev) && ev.type === kind && num(ev.t, 0) <= pos) out.push([k, ev]);
    }
    return out;
  }

  function djLast(found) {
    var best = null;
    for (var i = 0; i < found.length; i++) {
      var ev = found[i][1];
      if (best === null || num(ev.t, 0) >= num(best.t, 0)) best = ev;
    }
    return best;
  }

  function djCrossfader(seg, posS, loaded) {
    seg = obj(seg);
    var pos = num(posS, 0);
    var fx = list(seg.fx);
    var first = null, a, b;
    for (var i = 0; i < fx.length; i++) {
      var ev = fx[i];
      if (isObj(ev) && ev.type === "crossfade") {
        if (first === null || num(ev.t, 0) < num(first.t, 0)) first = ev;
      }
    }
    var cur = djLast(djLatest(fx, "crossfade", pos));
    if (cur === null && first !== null) {
      a = djSide(first.from);
      b = djSide(first.to);
      return a >= 0 ? a : (b >= 0 ? 1 - b : 0);
    }
    if (cur === null) {
      var ld = loaded || {};
      if (ld.A && !ld.B) return 0;
      if (ld.B && !ld.A) return 1;
      return 0.5;
    }
    a = djSide(cur.from);
    b = djSide(cur.to);
    if (a < 0) a = b >= 0 ? 1 - b : 0;
    if (b < 0) b = 1 - a;
    var u = str_(or(cur.curve, "")) === "cut" ? 1 : djU(cur, pos);
    return a + (b - a) * u;
  }

  function djGain(pts, pos) {
    pts = list(pts).filter(function (p) { return Array.isArray(p) && p.length >= 2; });
    if (!pts.length) return 1;
    if (pos <= num(pts[0][0], 0)) return clamp01(num(pts[0][1], 1));
    for (var i = 1; i < pts.length; i++) {
      var t1 = num(pts[i][0], 0);
      if (pos < t1) {
        var t0 = num(pts[i - 1][0], 0);
        var g0 = num(pts[i - 1][1], 1);
        var g1 = num(pts[i][1], 1);
        if (t1 <= t0) return clamp01(g1);
        return clamp01(g0 + (g1 - g0) * (pos - t0) / (t1 - t0));
      }
    }
    return clamp01(num(pts[pts.length - 1][1], 1));
  }

  function djEnv(fx, kind, target, pos) {
    var found = djLatest(fx, kind, pos).filter(function (f) { return str_(or(f[1].target, "")) === target; });
    var cur = djLast(found);
    if (cur === null) return -1;
    var u = djU(cur, pos);
    if (str_(or(cur.shape, "")) === "exp") u = u * u;
    var a = num(cur.from, 1);
    var b = num(cur.to, 1);
    return clamp01(a + (b - a) * u);
  }

  var djCache = typeof WeakMap !== "undefined" ? new WeakMap() : null;
  function djNotes(seg) {
    var raw = list(seg.notes);
    if (djCache && djCache.has(raw)) return djCache.get(raw);
    var clean = [];
    raw.forEach(function (n) {
      if (Array.isArray(n) && n.length >= 5) {
        clean.push([num(n[0], 0), num(n[1], 0), int_(n[2]), int_(n[3]), int_(n[4]),
          n.length > 5 ? int_(n[5]) : -1]);
      }
    });
    clean.sort(function (a, b) { return a[0] - b[0]; });
    var out = { notes: clean, times: clean.map(function (n) { return n[0]; }) };
    if (djCache) djCache.set(raw, out);
    return out;
  }

  function djDeckOf(v, lay) {
    var s = str_(v);
    if (s === "A" || s === "deck:A") return "A";
    if (s === "B" || s === "deck:B") return "B";
    if (s === "master") return "*";
    if (s.slice(0, 6) === "layer:") {
      var ly = own(lay, int_(s.slice(6)));
      return ly ? ly[0] : "";
    }
    return "";
  }

  function djFrame(seg, posS, tMs, calm) {
    seg = obj(seg);
    var pos = num(posS, 0);
    var tick = Math.floor(num(tMs, 0) / TICK_MS);
    var seed = strSeed(or(seg.id, ""));
    var fx = list(seg.fx);
    var show = list(seg.show);
    var layers = list(seg.layers);
    var lay = {};
    var loaded = { A: false, B: false };
    var k, d, i, x, y, ev, age, found;
    for (k = 0; k < layers.length; k++) {
      var lyr = layers[k];
      if (!isObj(lyr)) continue;
      var li = (lyr.i !== null && lyr.i !== undefined) ? int_(lyr.i) : k;
      d = str_(or(lyr.deck, "")) === "B" ? "B" : "A";
      lay[li] = [d, djGain(lyr.gain, pos)];
      loaded[d] = true;
    }
    list(seg.decks).forEach(function (dk) {
      if (isObj(dk)) {
        var dd = str_(or(dk.deck, ""));
        if (dd === "A" || dd === "B") loaded[dd] = true;
      }
    });
    // what each deck sounds like now (as playback reads its notes)
    var cn = djNotes(seg), notes = cn.notes, times = cn.times;
    var act = { A: 0, B: 0 };
    i = upper(times, pos) - 1;
    var scanned = 0;
    while (i >= 0 && scanned < 600) {
      var n = notes[i];
      var dt = pos - n[0];
      if (dt > 4.0) break;
      scanned += 1;
      i -= 1;
      var vel = n[4] / 127;
      var e = 0;
      if (dt < 0.45) e = vel * (1 - dt / 0.45);
      if (dt < n[1] && vel * 0.45 > e) e = vel * 0.45;
      if (e <= 0) continue;
      var ly = own(lay, n[5]);
      d = ly ? ly[0] : "A";
      var g = ly ? ly[1] : 1;
      loaded[d] = true;
      if (e * g > act[d]) act[d] = e * g;
    }
    var xf = clamp01(djCrossfader(seg, pos, loaded));
    var xg = { A: clamp01(cos(xf * PI / 2)), B: clamp01(sin(xf * PI / 2)) };
    var mf = djEnv(fx, "filter", "master", pos);
    var mg = djEnv(fx, "gain", "master", pos);
    var aud = {};
    ["A", "B"].forEach(function (dd) {
      var f = djEnv(fx, "filter", "deck:" + dd, pos);
      var gg = djEnv(fx, "gain", "deck:" + dd, pos);
      var a = Math.min(1, act[dd]) * xg[dd];
      if (f >= 0) a = a * (0.35 + 0.65 * f);
      if (gg >= 0) a = a * gg;
      if (mf >= 0) a = a * (0.35 + 0.65 * mf);
      if (mg >= 0) a = a * mg;
      aud[dd] = a;
    });
    var beat = djBeat(seg, pos);
    var bi = Math.floor(beat);
    var ph = beat - bi;
    // a stutter on a deck repeats the last 1/rate bar: its stripe jumps back
    var stut = { A: null, B: null };
    djLatest(fx, "stutter", pos).forEach(function (f) {
      var sev = f[1];
      if (pos >= num(sev.t, 0) + num(sev.dur, 0)) return;
      var sd = djDeckOf(sev.target, lay);
      ["A", "B"].forEach(function (name) {
        if (sd === name || sd === "*") {
          if (stut[name] === null || num(sev.t, 0) >= num(stut[name].t, 0)) stut[name] = sev;
        }
      });
    });
    var buf = zeros();
    for (var pi = 0; pi < DJ_PLATTERS.length; pi++) {
      var name = DJ_PLATTERS[pi][0], x0 = DJ_PLATTERS[pi][1], cx = DJ_PLATTERS[pi][2];
      var a = aud[name];
      var on = loaded[name];
      var b = beat;
      var st = stut[name];
      if (st !== null) {
        var bt = djBeat(seg, num(st.t, 0));
        var rep = 4 / clamp(num(st.rate, 8), 2, 64);
        b = bt + mod(beat - bt, rep);
      }
      var ang = calm ? -PI / 2 : b * TAU / 4 - PI / 2;
      var ca = cos(ang);
      var sa = sin(ang);
      var vinyl, rim, stripe, label;
      if (on) {
        vinyl = 22 + Math.floor(50 * a);
        rim = 40 + Math.floor(120 * a);
        stripe = 120 + Math.floor(135 * a);
        label = calm ? 150 : (a > 0.05 ? 70 + Math.floor(185 * (1 - ph)) : 70);
        if (st !== null && !calm && mod(tick, 2) === 0) rim = rim + 60;
      } else {
        vinyl = 12; rim = 22; stripe = 0; label = 30;
      }
      for (y = 1; y < 7; y++) {
        for (x = x0; x < x0 + 6; x++) {
          var dx = x - cx;
          var dy = y - 3.5;
          var d2 = dx * dx + dy * dy;
          if (d2 > 8.5) continue;
          var v;
          if (d2 < 1) v = label;
          else if (on && dx * ca + dy * sa > 0.5 && Math.abs(dy * ca - dx * sa) < 0.75) v = stripe;
          else if (d2 > 6) v = rim;
          else v = vinyl;
          px(buf, x, y, v);
        }
      }
    }
    // the master meter between the platters, and the riser filling it
    var level = Math.min(1, Math.max(aud.A, aud.B));
    var hgt = Math.floor(level * 6 + 0.5);
    for (y = 1; y < 7; y++) px(buf, 6, y, 10);
    for (k = 0; k < hgt; k++) px(buf, 6, 6 - k, k === hgt - 1 ? 255 : 110);
    var riser = -1;
    djLatest(fx, "riser", pos).forEach(function (f) {
      if (pos < num(f[1].t, 0) + num(f[1].dur, 0)) riser = djU(f[1], pos);
    });
    if (riser >= 0) {
      var rh = Math.min(6, 1 + Math.floor(riser * 6));
      for (k = 0; k < rh; k++) {
        var top = k === rh - 1;
        px(buf, 6, 6 - k, top ? ((calm || mod(tick, 2) === 0) ? 255 : 160) : 200);
      }
    }
    // the crossfader on the bottom row
    var down = mod(bi, 4) === 0;
    var track = calm ? 16 : 16 + Math.floor((down ? 60 : 30) * (1 - ph));
    for (x = 0; x < W; x++) px(buf, x, 7, track);
    var knob = 1 + Math.floor(xf * 10 + 0.5);
    px(buf, knob - 1, 7, 150);
    px(buf, knob, 7, 255);
    px(buf, knob + 1, 7, 150);
    // the key on the top row (a ghost of the old one just after a change)
    var key = obj(seg.key);
    var kc0 = djCamelot(or(key.from, key.to)), kn = kc0[0], kl = kc0[1];
    var kev = djLast(djLatest(show, "key", pos));
    if (kev !== null) {
      var c2 = djCamelot(kev.to);
      if (c2[0]) {
        if (!calm && pos - num(kev.t, 0) < DJ_KEY_GHOST_MS / 1000) {
          var c1 = djCamelot(kev.from);
          if (c1[0]) px(buf, c1[0] - 1, 0, 90);
        }
        kn = c2[0];
        kl = c2[1];
      }
    }
    if (kn) px(buf, kn - 1, 0, kl === "B" ? 255 : 170);
    // a judge holds up a score: the whole row, shrinking to the score
    var jud = null;
    djLatest(show, "judge", pos).forEach(function (f) {
      if (pos - num(f[1].t, 0) < DJ_JUDGE_MS / 1000) jud = f[1];
    });
    if (jud !== null) {
      age = (pos - num(jud.t, 0)) * 1000;
      var w = Math.floor(clamp01(num(jud.score, 0)) * 13 + 0.5);
      if (!calm && age < DJ_REVEAL_MS) w = 13 - Math.floor((13 - w) * age / DJ_REVEAL_MS);
      for (x = 0; x < w; x++) px(buf, x, 0, 230);
    }
    if (!calm) {
      // an influencer tugs a choice: a comet along the top row
      found = djLatest(show, "tug", pos);
      for (i = 0; i < found.length; i++) {
        k = found[i][0];
        ev = found[i][1];
        age = (pos - num(ev.t, 0)) * 1000;
        if (age >= DJ_TUG_MS) continue;
        x = Math.floor(age * 13 / DJ_TUG_MS);
        if (h32(seed, 131, k) % 2 === 1) {
          px(buf, 12 - x, 0, 220);
          px(buf, 13 - x, 0, 90);
        } else {
          px(buf, x, 0, 220);
          px(buf, x - 1, 0, 90);
        }
      }
      // a sniplet leaves its shelf: sparkles over the deck that pulled it
      found = djLatest(show, "pull", pos);
      for (i = 0; i < found.length; i++) {
        k = found[i][0];
        ev = found[i][1];
        age = (pos - num(ev.t, 0)) * 1000;
        if (age >= DJ_PULL_MS) continue;
        d = djDeckOf(ev.deck, lay);
        if (d === "" && ev.layer !== null && ev.layer !== undefined) d = djDeckOf("layer:" + String(int_(ev.layer)), lay);
        var px0 = d === "B" ? 7 : 0;
        for (var j = 0; j < 5; j++) {
          var hh = h32(seed, 101, k, j, tick);
          px(buf, px0 + hh % 6, 1 + (hh >>> 8) % 6, ((hh >>> 16) % 3 ? 250 : 130) * (1 - age / DJ_PULL_MS));
        }
      }
    }
    // the drop lands: a flash
    var flash = 0;
    if (!calm) {
      djLatest(fx, "drop", pos).forEach(function (f) {
        var fa = (pos - num(f[1].t, 0) - num(f[1].dur, 0)) * 1000;
        if (fa >= 0 && fa < DJ_DROP_MS) flash = 1 - fa / DJ_DROP_MS;
      });
      if (flash > 0) {
        for (var p = 0; p < N; p++) px(buf, p % W, Math.floor(p / W), 255 * flash);
      }
    }
    // LEDs
    var led1;
    if (kn) {
      var kc = DJ_KEY_RGB[kn - 1];
      var m = kl === "B" ? 1 : 0.6;
      led1 = scale(kc, (calm ? 180 : 60 + 195 * (1 - ph)) * m);
    } else {
      led1 = scale(DEFAULT_RGB, 60);
    }
    if (jud !== null) led1 = scale(own(DJ_JUDGE_RGB, str_(or(jud.judge, ""))) || [255, 210, 63], 220);
    if (riser >= 0) led1 = scale([255, 255, 255], 60 + 195 * riser);
    var led3 = loaded.A ? scale(DJ_DECK_RGB.A, 20 + 235 * aud.A) : [0, 0, 0];
    var led4 = loaded.B ? scale(DJ_DECK_RGB.B, 20 + 235 * aud.B) : [0, 0, 0];
    if (flash > 0) {
      var white = scale([255, 255, 255], 255 * flash);
      led1 = white; led3 = white; led4 = white;
    }
    return frame(buf, [led1, led3, led4]);
  }

  // ── text overlays (pairing codes, jam words) ─────────────────────────────────────────────
  var FONT57_SRC =
    "00E11131519110E1040C040404040E20E11010204081F31F02040201110E402060A121F0202" +
    "51F101E0101110E60608101E11110E71F01020408080880E11110E11110E90E11110F01020C" +
    "A0E1111111F1111B1E11111E11111EC0E11101010110ED1C12111111121CE1F10101E10101F" +
    "F1F10101E101010G0E11101711110FH1111111F111111I0E04040404040EJ0702020202120C" +
    "K11121418141211L1010101010101FM111B1515111111N11111915131111O0E11111111110E" +
    "P1E11111E101010Q0E11111115120DR1E11111E141211S0F10100E01011ET1F040404040404" +
    "U1111111111110EV11111111110A04W1111111515150AX11110A040A1111Y1111110A040404" +
    "Z1F01020408101F-0000001F000000?0E110102040004!04040404040004.00000000000C0C" +
    ":000C0C000C0C00'0C040800000000/00010204081000+0004041F040400#0A0A1F0A1F0A0A" +
    "*0004150E150400,000000000C0408&0C12140815120D(02040808080402)08040202020408";
  var FONT57 = Object.create(null);
  for (var fj = 0; fj < FONT57_SRC.length; fj += 15) {
    var rows57 = [];
    for (var rk = 0; rk < 7; rk++) rows57.push(parseInt(FONT57_SRC.substr(fj + 1 + 2 * rk, 2), 16));
    FONT57[FONT57_SRC.charAt(fj)] = rows57;
  }
  var TEXT_PPS = 10, TEXT_GAP = 7, TEXT_HOLD_MS = 2500, TEXT_PAGE_MS = 1500;
  var OVERLAY_RGB = { __proto__: null, pairing: [0, 229, 255], jam: [255, 42, 133], premiere: [255, 210, 63], notice: [255, 210, 63] };

  function text57(buf, s, x0, y0, v) {
    for (var i = 0; i < s.length; i++) {
      var g = FONT57[s.charAt(i)];
      if (!g) continue;
      for (var r = 0; r < 7; r++) for (var c = 0; c < 5; c++) if (g[r] & (16 >> c)) px(buf, x0 + i * 6 + c, y0 + r, v);
    }
  }

  function textPassMs(text) {
    var s = asc(text), tw = s.length * 6 - 1;
    if (!s || tw <= W) return TEXT_HOLD_MS;
    return Math.floor((W + tw) * 1000 / TEXT_PPS);
  }

  function textFrame(text, tMs, loop, priority, ttlMs, calm) {
    if (loop === undefined) loop = true;
    if (priority === undefined) priority = "pairing";
    var s = asc(text);
    var t = Math.max(0, Math.floor(num(tMs, 0)));
    var buf = zeros(), x;
    var tw = s.length * 6 - 1;
    if (s && tw <= W) {
      text57(buf, s, Math.floor((W - tw) / 2), 0, 255);
    } else if (s && calm) {
      var pages = Math.floor((s.length + 1) / 2);
      var k = Math.floor(t / TEXT_PAGE_MS);
      k = loop ? mod(k, pages) : Math.min(pages - 1, k);
      var chunk = s.slice(k * 2, k * 2 + 2);
      text57(buf, chunk, Math.floor((W - (chunk.length * 6 - 1)) / 2), 0, 255);
    } else if (s) {
      var base = W - Math.floor(t * TEXT_PPS / 1000);
      if (loop) {
        var period = tw + TEXT_GAP;
        if (base < 0) base = mod(base, period) - period;
        for (x = base; x < W; x += period) {
          text57(buf, s, x, 0, 255);
          px(buf, x + tw + Math.floor(TEXT_GAP / 2) + 1, 3, 120);
        }
      } else {
        text57(buf, s, base, 0, 255);
      }
    }
    var ttl = num(ttlMs, 0);
    if (ttl > 0) {
      var lit = Math.ceil(clamp01(1 - t / ttl) * W);
      for (x = 0; x < lit; x++) px(buf, x, 7, 70);
    }
    var col = OVERLAY_RGB[String(or(priority, ""))] || [220, 220, 255];
    var pulse = calm ? 200 : 90 + Math.floor(165 * breath(t, 1600));
    return frame(buf, [scale(col, pulse), scale(col, 60), [0, 0, 0]]);
  }

  // ── the Series Premiere: the box, then the burst ──────────────────────────────────────────
  var PREMIERE_PERIOD_MS = 3200, PREMIERE_OPEN_MS = 2600, PREMIERE_RGB = [255, 210, 63];
  var PREMIERE_TIER_RGB = { __proto__: null, common: [154, 154, 184], uncommon: [111, 232, 154], rare: [125, 234, 242], epic: [192, 140, 255],
                            legendary: [255, 228, 92], secret: [255, 107, 154] };

  function premiereBox(buf, dx, lid, v) {
    var x, y;
    for (x = 3; x < 10; x++) { px(buf, x + dx, 4, v); px(buf, x + dx, 7, v); }
    for (y = 5; y < 7; y++) { px(buf, 3 + dx, y, v); px(buf, 9 + dx, y, v); }
    for (y = 4; y < 8; y++) px(buf, 6 + dx, y, 255);
    for (x = 2; x < 11; x++) px(buf, x + dx, 3 - lid, v);
    px(buf, 5 + dx, 2 - lid, 180);
    px(buf, 7 + dx, 2 - lid, 180);
  }

  function premiereFrame(number, tMs, opened, calm, tier) {
    var t = Math.max(0, Math.floor(num(tMs, 0)));
    var n = Math.max(1, int_(number));
    var label = asc("S" + String(n));
    var tw = label.length * 4 - 1;
    var buf = zeros(), led1, led3 = [0, 0, 0];
    var tierRgb = PREMIERE_TIER_RGB[String(or(tier, ""))] || PREMIERE_TIER_RGB.legendary;
    if (!opened) {
      var p, showBox;
      if (calm) { showBox = mod(Math.floor(t / 1600), 2) === 0; p = 0; }
      else { p = mod(t, PREMIERE_PERIOD_MS); showBox = p < 2000; }
      if (showBox) {
        var dx = 0;
        if (!calm && 1200 <= p) dx = mod(Math.floor(p / 100), 2) === 0 ? 1 : -1;
        premiereBox(buf, dx, 0, 200);
        if (!calm) {
          var k = h32(n, Math.floor(p / 150)) % 5;
          px(buf, 4 + k, 0 + mod(Math.floor(p / 300), 2), 140);
        }
      } else {
        text(buf, label, Math.floor((W - tw) / 2), 1, 255);
      }
      var pulse = calm ? 200 : 90 + Math.floor(165 * breath(t, 1600));
      led1 = scale(PREMIERE_RGB, pulse);
    } else {
      var lt = t;
      if (calm) {
        if (lt < 1300) premiereBox(buf, 0, 3, 200);
        else text(buf, label, Math.floor((W - tw) / 2), 1, 255);
        led3 = scale(tierRgb, 160);
      } else if (lt < 600) {
        premiereBox(buf, 0, Math.floor(lt / 150), 220);
      } else if (lt < 1800) {
        var u = (lt - 600) / 1200, r = 1 + u * 6;
        for (var i = 0; i < 12; i++) {
          var a = i * TAU / 12;
          px(buf, 6 + cos(a) * r, 3.5 + sin(a) * r * 0.6, 255 - Math.floor(180 * u));
        }
        premiereBox(buf, 0, 3, 120 - Math.floor(80 * u));
        led3 = scale(tierRgb, 255 - Math.floor(120 * u));
      } else {
        text(buf, label, Math.floor((W - tw) / 2), 1, 255);
        led3 = scale(tierRgb, 120);
      }
      led1 = scale(PREMIERE_RGB, lt < 1800 && !calm ? 255 : 200);
    }
    return frame(buf, [led1, led3, [0, 0, 0]]);
  }

  var RAMP = ".:-+*#";
  function ascii(fr) {
    var rows = [];
    for (var y = 0; y < H; y++) {
      var row = "";
      for (var x = 0; x < W; x++) {
        var v = fr.pixels[y * W + x];
        row += v === 0 ? RAMP.charAt(0) : RAMP.charAt(1 + Math.floor((v - 1) * 5 / 255));
      }
      rows.push(row);
    }
    return rows.join("\n");
  }

  function toHex(fr) {
    var out = "", all = fr.pixels.concat(fr.rgb[0], fr.rgb[1], fr.rgb[2]);
    for (var i = 0; i < all.length; i++) out += (all[i] < 16 ? "0" : "") + (all[i] & 255).toString(16);
    return out;
  }

  function toBytes(fr) {
    var out = typeof Uint8Array !== "undefined" ? new Uint8Array(FRAME_BYTES) : new Array(FRAME_BYTES), i;
    for (i = 0; i < N; i++) out[i] = fr.pixels[i] & 255;
    for (i = 0; i < 9; i++) out[N + i] = fr.rgb[Math.floor(i / 3)][i % 3] & 255;
    return out;
  }

  function fromHex(hex) {
    hex = String(hex);
    if (!/^[0-9a-fA-F]*$/.test(hex) || hex.length !== FRAME_BYTES * 2) {
      throw new RangeError("a matrix frame is " + (FRAME_BYTES * 2) + " hex digits");
    }
    var b = [];
    for (var i = 0; i < hex.length; i += 2) b.push(parseInt(hex.substr(i, 2), 16));
    return frame(b.slice(0, N), [b.slice(N, N + 3), b.slice(N + 3, N + 6), b.slice(N + 6, N + 9)]);
  }

  var api = {
    W: W, H: H, N: N, FRAME_BYTES: FRAME_BYTES, TICK_MS: TICK_MS, GLYPHS: GLYPHS, COLS: COLS, PALETTE: PALETTE,
    film: film, playback: playback, idle: idle, corpus: corpus, glyph: glyph, tone: toneFrame,
    dj: djFrame, djBeat: djBeat, djCrossfader: djCrossfader, djCamelot: djCamelot,
    text: textFrame, textPassMs: textPassMs, premiere: premiereFrame, PREMIERE_PERIOD_MS: PREMIERE_PERIOD_MS,
    PREMIERE_OPEN_MS: PREMIERE_OPEN_MS,
    filmReel: filmReel, songSeed: songSeed, strSeed: strSeed,
    ascii: ascii, toHex: toHex, fromHex: fromHex, toBytes: toBytes
  };

  // Join the bollardeck object: the one already there, else bollardeck.js's under require(), else one made here
  // (when this file is loaded first or alone).
  var bollardeck = (typeof root.bollardeck === "object" && root.bollardeck) ||
    ((typeof module === "object" && module.exports && typeof require === "function") ? require("./bollardeck.js") : (root.bollardeck = {}));
  var matrix = bollardeck.matrix || (bollardeck.matrix = {});
  Object.keys(api).forEach(function (k) { matrix[k] = api[k]; });
  (bollardeck.parts || (bollardeck.parts = {})).matrix = true;
  if (typeof module === "object" && module.exports) module.exports = matrix;
})(typeof globalThis !== "undefined" ? globalThis : this);
