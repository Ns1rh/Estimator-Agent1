import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const getArg = (name, fallback = "") => {
  const i = args.indexOf(name);
  if (i === -1 || i + 1 >= args.length) return fallback;
  return args[i + 1];
};
const hasArg = (name) => args.includes(name);

const action = getArg("--action", "status");
const port = Number(getArg("--port", "9222"));
const outDir = getArg("--out-dir", path.resolve("outputs", "livecount-control"));
const text = getArg("--text", "");
const value = getArg("--value", "");
const key = getArg("--key", "");
const url = getArg("--url", "");
const seconds = Number(getArg("--seconds", "45"));
const x = Number(getArg("--x", "700"));
const y = Number(getArg("--y", "240"));
const left = Number(getArg("--left", "-820"));
const top = Number(getArg("--top", "-760"));
const radius = Number(getArg("--radius", "8"));
const color = getArg("--color", "#084a91");
const screenRadius = Number(getArg("--screen-radius", "12"));

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} failed: ${res.status} ${res.statusText}`);
  return await res.json();
}

const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function connectToTab() {
  const tabs = await getJson(`http://127.0.0.1:${port}/json`);
  const pageTabs = tabs.filter(t => t.type === "page");
  if (!pageTabs.length) throw new Error(`No controllable browser tabs found on port ${port}. Open launcher option 14 first.`);
  const preferred = pageTabs.find(t => /livecount|trimble/i.test(`${t.title} ${t.url}`)) || pageTabs[0];
  const ws = new WebSocket(preferred.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  let id = 0;
  const pending = new Map();
  ws.addEventListener("message", evt => {
    const msg = JSON.parse(evt.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
      else resolve(msg.result);
    }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const msgId = ++id;
    pending.set(msgId, { resolve, reject });
    ws.send(JSON.stringify({ id: msgId, method, params }));
  });
  return { tab: preferred, ws, send };
}

async function evalJs(send, expression, awaitPromise = true) {
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise,
    returnByValue: true,
    userGesture: true
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Runtime evaluation failed");
  return result.result?.value;
}

function jsString(s) {
  return JSON.stringify(s);
}

function makeId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    const v = c === "x" ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

function findLatestAnnotationContext(outputDir) {
  const files = fs.existsSync(outputDir)
    ? fs.readdirSync(outputDir)
      .filter(name => /^livecount-network-\d+\.json$/.test(name))
      .map(name => path.join(outputDir, name))
      .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs)
    : [];
  for (const file of files) {
    try {
      const data = JSON.parse(fs.readFileSync(file, "utf8"));
      for (const req of data.requests || []) {
        if (!String(req.url || "").includes("services.trimbleplatform.com/annotations/annotations/annotationgroups")) continue;
        if (req.method !== "POST" || !req.bodyPreview) continue;
        const body = JSON.parse(req.bodyPreview);
        const group = body?.[0]?.annotationGroup;
        const ann = group?.annotations?.[0];
        if (group?.drawingId && group?.estimateId && group?.user?.id && ann) {
          return {
            sourceFile: file,
            drawingId: group.drawingId,
            estimateId: group.estimateId,
            user: group.user,
            workspaceId: group.workspaceId || "",
            layerId: ann.layerId || "default",
            styleId: ann.styleId || "default",
            groupType: group.annotations?.[0]?.groupType || "circle",
            strokeWidth: ann.strokeWidth || 3,
          };
        }
      }
    } catch {}
  }
  return null;
}

const snapshotExpression = `(() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const items = [];
  const selector = 'button,a,input,textarea,select,[role="button"],[role="menuitem"],[role="tab"],[aria-label],[title]';
  for (const el of document.querySelectorAll(selector)) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    const label = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.placeholder || '').trim().replace(/\\s+/g, ' ');
    if (!label && !['INPUT','TEXTAREA','SELECT'].includes(el.tagName)) continue;
    items.push({
      tag: el.tagName,
      role: el.getAttribute('role') || '',
      type: el.getAttribute('type') || '',
      label,
      x: Math.round(r.left + r.width / 2),
      y: Math.round(r.top + r.height / 2),
      box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]
    });
    if (items.length >= 250) break;
  }
  return {
    title: document.title,
    url: location.href,
    text: document.body.innerText.slice(0, 6000),
    controls: items
  };
})()`;

const storageExpression = `(() => {
  const scrub = (v) => {
    if (v == null) return v;
    const s = String(v);
    if (s.length > 80 || /token|bearer|jwt|auth|session|password/i.test(s)) return '<redacted>';
    return s;
  };
  return {
    localStorage: Object.fromEntries(Object.keys(localStorage).map(k => [k, scrub(localStorage.getItem(k))])),
    sessionStorage: Object.fromEntries(Object.keys(sessionStorage).map(k => [k, scrub(sessionStorage.getItem(k))])),
    cookies: document.cookie ? '<redacted>' : ''
  };
})()`;

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const { tab, ws, send } = await connectToTab();
  await send("Runtime.enable");
  await send("Page.enable");

  if (action === "status") {
    console.log(JSON.stringify({ ok: true, title: tab.title, url: tab.url, port }, null, 2));
  } else if (action === "back") {
    await send("Runtime.evaluate", { expression: "history.back()", awaitPromise: false });
    await wait(2500);
    const now = await evalJs(send, `({ title: document.title, url: location.href })`);
    console.log(JSON.stringify({ ok: true, action: "back", ...now }, null, 2));
  } else if (action === "goto") {
    if (!url) throw new Error("Pass --url with action goto.");
    await send("Page.navigate", { url });
    await wait(4000);
    const now = await evalJs(send, `({ title: document.title, url: location.href })`);
    console.log(JSON.stringify({ ok: true, action: "goto", ...now }, null, 2));
  } else if (action === "snapshot") {
    const snap = await evalJs(send, snapshotExpression);
    const file = path.join(outDir, `livecount-snapshot-${Date.now()}.json`);
    fs.writeFileSync(file, JSON.stringify(snap, null, 2), "utf8");
    console.log(`Snapshot saved: ${file}`);
    console.log(`Title: ${snap.title}`);
    console.log(`URL: ${snap.url}`);
    console.log(`Visible controls: ${snap.controls.length}`);
  } else if (action === "screenshot") {
    const result = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    const file = path.join(outDir, `livecount-screenshot-${Date.now()}.png`);
    fs.writeFileSync(file, Buffer.from(result.data, "base64"));
    console.log(`Screenshot saved: ${file}`);
  } else if (action === "inspect-storage") {
    const storage = await evalJs(send, storageExpression);
    const file = path.join(outDir, `livecount-storage-${Date.now()}.json`);
    fs.writeFileSync(file, JSON.stringify(storage, null, 2), "utf8");
    console.log(`Storage summary saved: ${file}`);
    console.log(JSON.stringify(storage, null, 2));
  } else if (action === "inspect-auth-shape") {
    const shape = await evalJs(send, `(() => {
      const raw = localStorage.getItem("mepauthenticate");
      const summarize = (value, depth = 0) => {
        if (value == null) return { type: "null" };
        if (Array.isArray(value)) return { type: "array", length: value.length, sample: depth < 2 ? value.slice(0, 3).map(v => summarize(v, depth + 1)) : [] };
        if (typeof value === "object") return {
          type: "object",
          keys: Object.keys(value),
          fields: Object.fromEntries(Object.entries(value).map(([k, v]) => [k, Array.isArray(v) ? "array" : typeof v])),
          children: depth < 2 ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, summarize(v, depth + 1)])) : {}
        };
        return { type: typeof value, length: String(value).length };
      };
      try {
        return { exists: Boolean(raw), parsed: summarize(JSON.parse(raw)) };
      } catch {
        return { exists: Boolean(raw), rawType: typeof raw, rawLength: raw ? raw.length : 0 };
      }
    })()`);
    const file = path.join(outDir, `livecount-auth-shape-${Date.now()}.json`);
    fs.writeFileSync(file, JSON.stringify(shape, null, 2), "utf8");
    console.log(`Auth shape saved: ${file}`);
    console.log(JSON.stringify(shape, null, 2));
  } else if (action === "inspect-app-data") {
    const appData = await evalJs(send, `(() => {
      const keys = ["estimates", "projects", "drawings", "styles", "layers", "symbolPoints", "scales", "applicationSettings"];
      const summarize = (value, depth = 0) => {
        if (value == null) return { type: "null" };
        if (Array.isArray(value)) {
          return {
            type: "array",
            length: value.length,
            sample: depth < 3 ? value.slice(0, 5).map(v => summarize(v, depth + 1)) : []
          };
        }
        if (typeof value === "object") {
          const keys = Object.keys(value);
          const preview = {};
          for (const [k, v] of Object.entries(value).slice(0, 80)) {
            if (/token|auth|password|email/i.test(k)) {
              preview[k] = "<redacted>";
            } else if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
              preview[k] = v;
            }
          }
          return {
            type: "object",
            keys,
            preview,
            children: depth < 2 ? Object.fromEntries(Object.entries(value).slice(0, 30).map(([k, v]) => [k, summarize(v, depth + 1)])) : {}
          };
        }
        if (typeof value === "string") return { type: "string", length: value.length, preview: value.length < 120 ? value : value.slice(0, 120) + "..." };
        return { type: typeof value, value };
      };
      const output = {};
      for (const key of keys) {
        const raw = localStorage.getItem(key);
        if (!raw) { output[key] = { exists: false }; continue; }
        try { output[key] = { exists: true, parsed: summarize(JSON.parse(raw)) }; }
        catch { output[key] = { exists: true, rawLength: raw.length, rawPreview: raw.slice(0, 200) }; }
      }
      return output;
    })()`);
    const file = path.join(outDir, `livecount-app-data-${Date.now()}.json`);
    fs.writeFileSync(file, JSON.stringify(appData, null, 2), "utf8");
    console.log(`App data summary saved: ${file}`);
    console.log(JSON.stringify(appData, null, 2).slice(0, 6000));
  } else if (action === "search-source") {
    const terms = (text || "takeoff,quantity,assembly,item,count,estimateItem,catalog").split(",").map(s => s.trim()).filter(Boolean);
    const results = await evalJs(send, `(async () => {
      const wanted = ${jsString(JSON.stringify(terms))};
      const terms = JSON.parse(wanted);
      const srcs = [...document.scripts].map(s => s.src).filter(Boolean).filter(src => src.startsWith(location.origin));
      const out = [];
      for (const src of srcs.slice(0, 80)) {
        try {
          const body = await fetch(src, { credentials: 'include' }).then(r => r.ok ? r.text() : '');
          const lower = body.toLowerCase();
          const hitTerms = terms.filter(t => lower.includes(t.toLowerCase()));
          if (!hitTerms.length) continue;
          const snippets = {};
          for (const term of hitTerms.slice(0, 12)) {
            const idx = lower.indexOf(term.toLowerCase());
            snippets[term] = idx >= 0 ? body.slice(Math.max(0, idx - 160), idx + 260) : '';
          }
          out.push({ src, length: body.length, hitTerms, snippets });
        } catch (e) {
          out.push({ src, error: String(e) });
        }
      }
      return { url: location.href, scriptCount: srcs.length, results: out };
    })()`);
    const file = path.join(outDir, `livecount-source-search-${Date.now()}.json`);
    fs.writeFileSync(file, JSON.stringify(results, null, 2), "utf8");
    console.log(`Source search saved: ${file}`);
    console.log(JSON.stringify({
      url: results.url,
      scriptCount: results.scriptCount,
      hits: results.results.map(r => ({ src: r.src, hitTerms: r.hitTerms, length: r.length, error: r.error }))
    }, null, 2));
  } else if (action === "inspect-browser-storage") {
    const storage = await evalJs(send, `(async () => {
      const safe = (v) => {
        if (v == null) return v;
        const s = String(v);
        if (s.length > 160 || /token|bearer|jwt|auth|session|password/i.test(s)) return '<redacted>';
        return s;
      };
      const local = Object.fromEntries(Object.keys(localStorage).map(k => [k, { length: localStorage.getItem(k)?.length || 0, preview: safe(localStorage.getItem(k)) }]));
      let dbs = [];
      if (indexedDB.databases) {
        dbs = await indexedDB.databases();
      }
      const opfs = [];
      async function walk(dir, prefix = '', depth = 0) {
        if (depth > 4) return;
        for await (const [name, handle] of dir.entries()) {
          const item = { path: prefix + name, kind: handle.kind };
          if (handle.kind === 'file') {
            try {
              const file = await handle.getFile();
              item.size = file.size;
              if (/items\\.json$|metadata\\.json$|takeoff|estimate/i.test(name) && file.size < 2000000) {
                item.preview = safe(await file.text());
              }
            } catch (e) { item.error = String(e); }
          }
          opfs.push(item);
          if (handle.kind === 'directory') {
            await walk(handle, prefix + name + '/', depth + 1);
          }
        }
      }
      try {
        if (navigator.storage?.getDirectory) await walk(await navigator.storage.getDirectory());
      } catch (e) {
        opfs.push({ error: String(e) });
      }
      return { url: location.href, localStorage: local, indexedDB: dbs, opfs };
    })()`, true);
    const file = path.join(outDir, `livecount-browser-storage-${Date.now()}.json`);
    fs.writeFileSync(file, JSON.stringify(storage, null, 2), "utf8");
    console.log(`Browser storage inventory saved: ${file}`);
    console.log(JSON.stringify({
      url: storage.url,
      localStorageKeys: Object.keys(storage.localStorage || {}),
      indexedDB: storage.indexedDB,
      opfsCount: storage.opfs?.length,
      likelyFiles: (storage.opfs || []).filter(x => /items\\.json|metadata\\.json|takeoff|estimate/i.test(x.path)).slice(0, 20)
    }, null, 2));
  } else if (action === "click-text" || action === "click-any-text" || action === "double-click-text") {
    if (!text) throw new Error("Pass --text with visible button/link/control text to click.");
    const clicked = await evalJs(send, `(() => {
      const needle = ${jsString(text)}.toLowerCase();
      const action = ${jsString(action)};
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const selector = action === 'click-text'
        ? 'button,a,[role="button"],[role="menuitem"],[role="tab"],input,[aria-label],[title]'
        : 'button,a,[role="button"],[role="menuitem"],[role="tab"],input,[aria-label],[title],div,td,span';
      const candidates = [...document.querySelectorAll(selector)].filter(visible).map(el => {
        const label = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.placeholder || '').trim().replace(/\\s+/g, ' ');
        return { el, label };
      }).filter(x => x.label.toLowerCase().includes(needle));
      if (!candidates.length) return { ok: false, reason: 'no match' };
      const target = candidates.sort((a, b) => a.label.length - b.label.length)[0].el;
      target.scrollIntoView({ block: 'center', inline: 'center' });
      target.click();
      if (action === 'double-click-text') {
        target.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true, view: window }));
      }
      return { ok: true, label: candidates[0].label, action };
    })()`);
    console.log(JSON.stringify(clicked, null, 2));
  } else if (action === "type") {
    if (!value) throw new Error("Pass --value with text to type.");
    const selectorText = text;
    const typed = await evalJs(send, `(() => {
      const value = ${jsString(value)};
      const hint = ${jsString(selectorText)}.toLowerCase();
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      let fields = [...document.querySelectorAll('input:not([type=hidden]), textarea, [contenteditable=true]')].filter(visible);
      if (hint) {
        fields = fields.filter(el => {
          const label = (el.placeholder || el.getAttribute('aria-label') || el.getAttribute('title') || el.name || el.id || '').toLowerCase();
          return label.includes(hint);
        });
      }
      if (!fields.length) return { ok: false, reason: 'no input field match' };
      const el = fields[0];
      el.focus();
      if ('value' in el) {
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        el.innerText = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return { ok: true, field: el.placeholder || el.getAttribute('aria-label') || el.name || el.id || el.tagName };
    })()`);
    console.log(JSON.stringify(typed, null, 2));
  } else if (action === "upload-file") {
    if (!value) throw new Error("Pass --value with an absolute local file path to upload.");
    const abs = path.resolve(value);
    if (!fs.existsSync(abs)) throw new Error(`Upload file does not exist: ${abs}`);
    const doc = await send("DOM.getDocument", { depth: -1, pierce: true });
    const found = await send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: "input[type=file]" });
    if (!found.nodeId) throw new Error("No input[type=file] found on the current page.");
    await send("DOM.setFileInputFiles", { nodeId: found.nodeId, files: [abs] });
    await wait(2000);
    console.log(JSON.stringify({ ok: true, uploaded: abs }, null, 2));
  } else if (action === "press") {
    if (!key) throw new Error("Pass --key, e.g. Enter, Escape, Tab.");
    await send("Input.dispatchKeyEvent", { type: "keyDown", key });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key });
    console.log(`Pressed key: ${key}`);
  } else if (action === "click-xy") {
    await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
    await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
    console.log(`Clicked (${x}, ${y})`);
  } else if (action === "ui-place-circle") {
    // Select circle tool from the current LiveCount toolbar, then drag a small circle on the canvas.
    await send("Input.dispatchMouseEvent", { type: "mousePressed", x: 990, y: 103, button: "left", clickCount: 1 });
    await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: 990, y: 103, button: "left", clickCount: 1 });
    await new Promise(resolve => setTimeout(resolve, 500));
    await send("Input.dispatchMouseEvent", { type: "mousePressed", x: x - screenRadius, y, button: "left", clickCount: 1 });
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: x + screenRadius, y, button: "left" });
    await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: x + screenRadius, y, button: "left", clickCount: 1 });
    console.log(`Placed LiveCount circle via UI near (${x}, ${y}) with screen radius ${screenRadius}`);
  } else if (action === "api-place-circle") {
    const context = findLatestAnnotationContext(outDir);
    if (!context) {
      throw new Error(`No prior annotation API context found in ${outDir}. Run record-network/record-click once first.`);
    }
    const groupId = makeId();
    const annotationId = makeId();
    const diameter = radius * 2;
    const payload = [{
      annotationGroup: {
        detailScaleMultiplier: null,
        drawingId: context.drawingId,
        estimateId: context.estimateId,
        id: groupId,
        user: context.user,
        workspaceId: context.workspaceId,
        annotations: [{
          angle: 0,
          area: 0,
          baseFill: color,
          baseStroke: color,
          baseVertexStroke: color,
          drawingId: context.drawingId,
          groupId,
          groupType: "circle",
          height: diameter,
          hidden: false,
          id: annotationId,
          isIsometric: false,
          layerId: context.layerId,
          left,
          length: 0.006,
          locked: false,
          opacity: 1,
          originX: "center",
          originY: "center",
          radius,
          rawLength: radius * 6.28,
          scaleX: 1,
          scaleY: 1,
          strokeWidth: context.strokeWidth,
          styleId: context.styleId,
          top,
          type: "circle",
          version: 1,
          visible: true,
          width: diameter
        }]
      },
      actionType: "createGroup",
      crudOperation: "save"
    }];
    const response = await evalJs(send, `(() => {
      const auth = JSON.parse(localStorage.getItem("mepauthenticate") || "{}");
      const accessToken = auth?.token?.accessToken || auth?.token?.jwt || "";
      const headers = { "content-type": "application/json" };
      if (accessToken) headers.authorization = "Bearer " + accessToken;
      return fetch("https://services.trimbleplatform.com/annotations/annotations/annotationgroups", {
      method: "POST",
      credentials: "include",
      mode: "cors",
      headers,
      body: ${jsString(JSON.stringify(payload))}
      }).then(async r => ({ ok: r.ok, status: r.status, text: await r.text() }));
    })()`);
    const stamp = Date.now();
    const file = path.join(outDir, `livecount-api-place-circle-${stamp}.json`);
    fs.writeFileSync(file, JSON.stringify({ context, payload, response }, null, 2), "utf8");
    console.log(`Place-circle API result saved: ${file}`);
    console.log(JSON.stringify(response, null, 2));
  } else if (action === "record-network" || action === "record-click") {
    await send("Network.enable", { maxPostDataSize: 200000 });
    const requests = new Map();
    const interesting = [];
    const startedAt = new Date().toISOString();

    ws.addEventListener("message", evt => {
      const msg = JSON.parse(evt.data);
      if (msg.method === "Network.requestWillBeSent") {
        const req = msg.params.request || {};
        const url = req.url || "";
        const method = req.method || "";
        const type = msg.params.type || "";
        const isApiLike = /api|graphql|takeoff|count|measurement|annotation|document|sheet|job|project|doxel|mark|symbol/i.test(url);
        const hasBody = Boolean(req.postData);
        const item = {
          requestId: msg.params.requestId,
          timestamp: msg.params.timestamp,
          type,
          method,
          url,
          hasBody,
          headers: req.headers || {},
          postDataPreview: hasBody ? String(req.postData).slice(0, 4000) : "",
          initiatorType: msg.params.initiator?.type || "",
        };
        requests.set(msg.params.requestId, item);
        if (isApiLike || hasBody || !/\.(png|jpg|jpeg|gif|svg|css|js|woff|ico)(\?|$)/i.test(url)) {
          interesting.push(item);
        }
      }
      if (msg.method === "Network.responseReceived") {
        const item = requests.get(msg.params.requestId);
        if (item) {
          item.status = msg.params.response?.status;
          item.mimeType = msg.params.response?.mimeType || "";
        }
      }
    });

    console.log(`Recording LiveCount network traffic for ${seconds} seconds.`);
    if (action === "record-click") {
      console.log(`I will place one test click at screen coordinate (${x}, ${y}) after 3 seconds.`);
      await new Promise(resolve => setTimeout(resolve, 3000));
      await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
      await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
      console.log("Placed one test click. Waiting for network saves...");
      await new Promise(resolve => setTimeout(resolve, Math.max(1, seconds - 3) * 1000));
    } else {
      console.log("During this time, manually place ONE simple mark in LiveCount, then wait for this script to finish.");
      await new Promise(resolve => setTimeout(resolve, seconds * 1000));
    }

    const endedAt = new Date().toISOString();
    const sanitized = interesting
      .filter(item => !/browser\.events\.data\.microsoft|google-analytics|googletagmanager|doubleclick|favicon/i.test(item.url))
      .map(item => {
        let parsedBody = null;
        if (item.postDataPreview) {
          try { parsedBody = JSON.parse(item.postDataPreview); } catch {}
        }
        return {
          type: item.type,
          method: item.method,
          status: item.status,
          mimeType: item.mimeType,
          url: item.url.replace(/([?&](?:token|access_token|id_token|auth|authorization|code|state|session|sig|signature)=)[^&]+/ig, "$1<redacted>"),
          hasBody: item.hasBody,
          headers: Object.fromEntries(Object.entries(item.headers || {}).map(([k, v]) => [
            k,
            /authorization|token|cookie|session|password/i.test(k) ? "<redacted>" : String(v).slice(0, 500)
          ])),
          bodyPreview: item.postDataPreview
            ? item.postDataPreview.replace(/("(?:token|access_token|id_token|auth|authorization|password|session|cookie)"\s*:\s*")[^"]+"/ig, '$1<redacted>"')
            : "",
          bodyKeys: parsedBody && typeof parsedBody === "object" && !Array.isArray(parsedBody) ? Object.keys(parsedBody).slice(0, 50) : [],
          initiatorType: item.initiatorType,
        };
      });

    const stamp = Date.now();
    const jsonFile = path.join(outDir, `livecount-network-${stamp}.json`);
    const mdFile = path.join(outDir, `livecount-network-summary-${stamp}.md`);
    fs.writeFileSync(jsonFile, JSON.stringify({ startedAt, endedAt, tab: { title: tab.title, url: tab.url }, requests: sanitized }, null, 2), "utf8");
    fs.writeFileSync(mdFile, [
      "# LiveCount network capture summary",
      "",
      `Started: ${startedAt}`,
      `Ended: ${endedAt}`,
      `Tab: ${tab.title}`,
      `URL: ${tab.url}`,
      "",
      "## Candidate API calls",
      "",
      ...sanitized.slice(0, 80).map((item, idx) => {
        const lines = [
          `### ${idx + 1}. ${item.method} ${item.status ?? ""}`,
          "",
          `URL: \`${item.url}\``,
          "",
          `Type: ${item.type || ""}`,
          `MIME: ${item.mimeType || ""}`,
          `Has body: ${item.hasBody}`,
        ];
        if (item.bodyKeys.length) lines.push(`Body keys: ${item.bodyKeys.join(", ")}`);
        if (item.bodyPreview) {
          lines.push("", "Body preview:", "```json", item.bodyPreview, "```");
        }
        lines.push("");
        return lines.filter(Boolean).join("\n");
      }),
      "",
      "## How to interpret",
      "",
      "Look for a POST/PATCH/PUT request that appears right after the manual mark was placed. The most useful calls usually mention takeoff, measurement, annotation, item, sheet, job, project, or similar words.",
    ].join("\n"), "utf8");
    console.log(`Network JSON saved: ${jsonFile}`);
    console.log(`Network summary saved: ${mdFile}`);
  } else {
    throw new Error(`Unknown action: ${action}`);
  }

  ws.close();
}

main().catch(err => {
  console.error(`ERROR: ${err.message}`);
  process.exit(1);
});
