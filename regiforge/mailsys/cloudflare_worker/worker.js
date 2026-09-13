/**
 * Cloudflare Email Worker: NVIDIA 验证码实时提取 + chatgpt2apiEditV141 兼容
 * - email handler: 收邮件 → 提码(NVIDIA) → 存原始邮件(全部) → 写 DO + KV
 * - fetch handler:
 *   - 原有: ?token=&key= 秒级读 NVIDIA 验证码
 *   - 新增: POST /admin/new_address  创建邮箱
 *   - 新增: GET  /admin/address      查已有邮箱
 *   - 新增: GET  /admin/show_password/{id}  取 JWT
 *   - 新增: GET  /api/mails           查收邮件
 * Email Routing: catch-all *@zhoushu.kdns.fr → 发到此 Worker
 */

// ===== Durable Object: 强一致存储 =====
export class NvidiaCodeStore {
  constructor(state, env) {
    this.state = state;
    this.codes = new Map();       // 验证码: key=email → val=JSON
    this.mailboxes = new Map();   // 邮箱注册: key=address → val=JSON
    this.mails = new Map();       // 邮件存储: key="mail:{address}" → Map<mailId, mailObj>
  }

  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === "POST" && path === "/store") {
      // 存验证码: body={key, val}
      try {
        const { key, val } = await request.json();
        if (key && val) {
          this.codes.set(key.toLowerCase(), val);
          setTimeout(() => this.codes.delete(key.toLowerCase()), 300000);
        }
        return new Response("ok", { status: 200 });
      } catch (e) {
        return new Response("err: " + e.message, { status: 500 });
      }
    }

    if (request.method === "POST" && path === "/register_mailbox") {
      // 注册邮箱: body={address, id, name, created_at}
      try {
        const data = await request.json();
        const addr = (data.address || "").toLowerCase();
        if (addr) {
          this.mailboxes.set(addr, JSON.stringify(data));
        }
        return new Response("ok", { status: 200 });
      } catch (e) {
        return new Response("err: " + e.message, { status: 500 });
      }
    }

    if (request.method === "POST" && path === "/store_mail") {
      // 存原始邮件: body={address, mailObj}
      try {
        const { address, mailObj } = await request.json();
        const addr = (address || "").toLowerCase();
        if (addr && mailObj) {
          const mapKey = "mail:" + addr;
          if (!this.mails.has(mapKey)) this.mails.set(mapKey, new Map());
          const mailId = mailObj.id || crypto.randomUUID();
          mailObj.id = mailId;
          this.mails.get(mapKey).set(mailId, JSON.stringify(mailObj));
          // 30 分钟后清理
          setTimeout(() => {
            if (this.mails.has(mapKey)) {
              this.mails.get(mapKey).delete(mailId);
              if (this.mails.get(mapKey).size === 0) this.mails.delete(mapKey);
            }
          }, 1800000);
        }
        return new Response("ok", { status: 200 });
      } catch (e) {
        return new Response("err: " + e.message, { status: 500 });
      }
    }

    if (request.method === "GET" && path === "/get") {
      // 取验证码: ?key=xxx
      const key = (url.searchParams.get("key") || "").toLowerCase();
      const val = this.codes.get(key);
      return new Response(val || "", {
        status: val ? 200 : 404,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*", "cache-control": "no-store" },
      });
    }

    if (request.method === "GET" && path === "/list_mailboxes") {
      // 列出邮箱: ?query=xxx
      const query = (url.searchParams.get("query") || "").toLowerCase();
      const results = [];
      for (const [addr, val] of this.mailboxes) {
        if (!query || addr.includes(query)) {
          try { results.push(JSON.parse(val)); } catch (e) {}
        }
      }
      return new Response(JSON.stringify({ results }), {
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*", "cache-control": "no-store" },
      });
    }

    if (request.method === "GET" && path === "/get_mailbox") {
      // 取单个邮箱注册信息: ?address=xxx
      const addr = (url.searchParams.get("address") || "").toLowerCase();
      const val = this.mailboxes.get(addr);
      return new Response(val || "", {
        status: val ? 200 : 404,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*", "cache-control": "no-store" },
      });
    }

    if (request.method === "GET" && path === "/list_mails") {
      // 取某地址的邮件: ?address=xxx
      const addr = (url.searchParams.get("address") || "").toLowerCase();
      const mapKey = "mail:" + addr;
      const mailMap = this.mails.get(mapKey);
      const results = [];
      if (mailMap) {
        for (const [, val] of mailMap) {
          try { results.push(JSON.parse(val)); } catch (e) {}
        }
      }
      return new Response(JSON.stringify({ results }), {
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*", "cache-control": "no-store" },
      });
    }

    return new Response("not found", { status: 404 });
  }
}

// ===== JWT 工具 =====
function base64url(str) {
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function makeJwt(payload, secret) {
  const header = base64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = base64url(JSON.stringify(payload));
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(header + "." + body));
  const sigB64 = base64url(String.fromCharCode(...new Uint8Array(sig)));
  return header + "." + body + "." + sigB64;
}

async function verifyJwt(token, secret) {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const key = await crypto.subtle.importKey(
      "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["verify"]
    );
    const sig = Uint8Array.from(atob(parts[2].replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
    const valid = await crypto.subtle.verify("HMAC", key, sig, new TextEncoder().encode(parts[0] + "." + parts[1]));
    if (!valid) return null;
    return JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
  } catch (e) {
    return null;
  }
}

// ===== 鉴权辅助 =====
function checkAdminAuth(request, env) {
  const adminPw = env.ADMIN_PASSWORD || "";
  if (!adminPw) return false;
  return request.headers.get("x-admin-auth") === adminPw;
}

async function checkBearerAuth(request, env) {
  const auth = request.headers.get("Authorization") || "";
  if (!auth.startsWith("Bearer ")) return null;
  const token = auth.slice(7).trim();
  const adminPw = env.ADMIN_PASSWORD || "";
  return await verifyJwt(token, adminPw);
}

// ===== 保留旧 DO 类（兼容现有部署，避免迁移） =====
export class MailboxStore {
  constructor(state, env) { this.state = state; }
  async fetch(request) {
    return new Response("deprecated", { status: 410, headers: { "content-type": "text/plain" } });
  }
}

// ===== 主 Worker =====
export default {
  async email(message, env, ctx) {
    const to = (message.to || "").toLowerCase().trim();
    const from = (message.from || "").toLowerCase();
    const subject = (message.headers.get("subject") || "");

    // 读原始邮件
    let raw = "";
    try { raw = await new Response(message.raw).text(); } catch (e) {}

    const bodyText = stripHtml(extractMailBody(raw));

    // ---- 存原始邮件（所有来源，供 /api/mails 查询）----
    const mailObj = {
      id: crypto.randomUUID(),
      from: message.from,
      to: message.to,
      subject,
      text: bodyText.substring(0, 10000),
      html: raw.substring(0, 50000),
      created_at: new Date().toISOString(),
    };
    // 写 DO
    try {
      const id = env.NVIDIA_DO.idFromName("global");
      const stub = env.NVIDIA_DO.get(id);
      await stub.fetch("https://do/store_mail", {
        method: "POST",
        body: JSON.stringify({ address: to, mailObj }),
      });
    } catch (e) {}
    // 写 KV（备份，30 分钟 TTL）
    try {
      const kvKey = "mails:" + to;
      const existing = await env.EMAIL_STORAGE.get(kvKey, "json");
      const mails = Array.isArray(existing) ? existing : [];
      mails.push(mailObj);
      // 只保留最近 50 封
      if (mails.length > 50) mails.splice(0, mails.length - 50);
      await env.EMAIL_STORAGE.put(kvKey, JSON.stringify(mails), { expirationTtl: 1800 });
    } catch (e) {}

    // ---- NVIDIA 验证码提取（原有逻辑）----
    const isNvidia = from.includes("nvidia") || subject.toLowerCase().includes("nvidia");
    if (isNvidia) {
      let code = extractCode(bodyText) || extractCode(stripHtml(raw));
      if (code) {
        const val = JSON.stringify({ code, ts: Date.now(), from: message.from, subject, to });
        // 写 KV（备份）
        try { await env.EMAIL_STORAGE.put(to, val, { expirationTtl: 300 }); } catch (e) {}
        // 写 DO（即时强一致）
        try {
          const id = env.NVIDIA_DO.idFromName("global");
          const stub = env.NVIDIA_DO.get(id);
          await stub.fetch("https://do/store", { method: "POST", body: JSON.stringify({ key: to, val }) });
        } catch (e) {}
      }
    }

    // 转发原件到 qq
    try { await message.forward("913812273@qq.com"); } catch (e) {}
  },

  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET,POST,OPTIONS",
          "access-control-allow-headers": "Content-Type,Authorization,x-admin-auth",
        },
      });
    }

    const headers = {
      "content-type": "application/json",
      "access-control-allow-origin": "*",
      "cache-control": "no-store",
    };

    // ---- 原有端点: NVIDIA 验证码查询 ----
    if (path === "/" || path === "") {
      if (url.searchParams.get("token") !== (env.WORKER_TOKEN || "nv2026")) {
        return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401, headers });
      }
      const key = (url.searchParams.get("key") || "").toLowerCase().trim();
      if (!key) {
        return new Response(JSON.stringify({ error: "missing key" }), { status: 400, headers });
      }
      // 读 DO
      try {
        const id = env.NVIDIA_DO.idFromName("global");
        const stub = env.NVIDIA_DO.get(id);
        const r = await stub.fetch("https://do/get?key=" + encodeURIComponent(key));
        if (r.status === 200) {
          const text = await r.text();
          return new Response(text, { status: 200, headers });
        }
      } catch (e) {}
      // 兜底读 KV
      try {
        const v = await env.EMAIL_STORAGE.get(key);
        return new Response(v || "", { status: v ? 200 : 404, headers });
      } catch (e) {
        return new Response("", { status: 404 });
      }
    }

    // ---- POST /admin/new_address: 创建邮箱 ----
    if (path === "/admin/new_address" && request.method === "POST") {
      if (!checkAdminAuth(request, env)) {
        return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401, headers });
      }
      try {
        const body = await request.json();
        const enablePrefix = body.enablePrefix !== false;
        const rawName = (body.name || randomName()).trim();
        const domain = (body.domain || "").trim();
        if (!domain) {
          return new Response(JSON.stringify({ error: "missing domain" }), { status: 400, headers });
        }
        const name = enablePrefix ? rawName : rawName;
        const address = (name + "@" + domain).toLowerCase();
        const addrId = crypto.randomUUID();
        const createdAt = new Date().toISOString();

        // 注册邮箱到 DO
        try {
          const id = env.NVIDIA_DO.idFromName("global");
          const stub = env.NVIDIA_DO.get(id);
          await stub.fetch("https://do/register_mailbox", {
            method: "POST",
            body: JSON.stringify({ address, id: addrId, name: address, created_at: createdAt }),
          });
        } catch (e) {}

        // 生成 JWT
        const jwt = await makeJwt({ address, iat: Math.floor(Date.now() / 1000) }, env.ADMIN_PASSWORD);

        return new Response(JSON.stringify({ address, jwt, id: addrId }), { status: 200, headers });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers });
      }
    }

    // ---- GET /admin/address: 查已有邮箱 ----
    if (path === "/admin/address" && request.method === "GET") {
      if (!checkAdminAuth(request, env)) {
        return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401, headers });
      }
      const query = (url.searchParams.get("query") || "").toLowerCase();
      try {
        const id = env.NVIDIA_DO.idFromName("global");
        const stub = env.NVIDIA_DO.get(id);
        const r = await stub.fetch("https://do/list_mailboxes?query=" + encodeURIComponent(query));
        if (r.status === 200) {
          const text = await r.text();
          return new Response(text, { status: 200, headers });
        }
      } catch (e) {}
      return new Response(JSON.stringify({ results: [] }), { status: 200, headers });
    }

    // ---- GET /admin/show_password/{id}: 取 JWT ----
    if (path.startsWith("/admin/show_password/") && request.method === "GET") {
      if (!checkAdminAuth(request, env)) {
        return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401, headers });
      }
      const addrId = path.slice("/admin/show_password/".length);
      // 通过 DO 查找邮箱
      try {
        const id = env.NVIDIA_DO.idFromName("global");
        const stub = env.NVIDIA_DO.get(id);
        // 列出所有邮箱找匹配 id
        const r = await stub.fetch("https://do/list_mailboxes");
        if (r.status === 200) {
          const data = JSON.parse(await r.text());
          const matched = (data.results || []).find(m => m.id === addrId);
          if (matched) {
            const jwt = await makeJwt({ address: matched.address, iat: Math.floor(Date.now() / 1000) }, env.ADMIN_PASSWORD);
            return new Response(JSON.stringify({ jwt }), { status: 200, headers });
          }
        }
      } catch (e) {}
      return new Response(JSON.stringify({ error: "address not found" }), { status: 404, headers });
    }

    // ---- GET /api/mails: 查收邮件 ----
    if (path === "/api/mails" && request.method === "GET") {
      const payload = await checkBearerAuth(request, env);
      if (!payload) {
        return new Response(JSON.stringify({ error: "unauthorized" }), { status: 401, headers });
      }
      const address = (payload.address || "").toLowerCase();
      if (!address) {
        return new Response(JSON.stringify({ error: "invalid token" }), { status: 401, headers });
      }

      let results = [];

      // 优先读 DO
      try {
        const id = env.NVIDIA_DO.idFromName("global");
        const stub = env.NVIDIA_DO.get(id);
        const r = await stub.fetch("https://do/list_mails?address=" + encodeURIComponent(address));
        if (r.status === 200) {
          const data = JSON.parse(await r.text());
          results = data.results || [];
        }
      } catch (e) {}

      // 兜底读 KV
      if (results.length === 0) {
        try {
          const kvKey = "mails:" + address;
          const data = await env.EMAIL_STORAGE.get(kvKey, "json");
          if (Array.isArray(data)) {
            results = data;
          }
        } catch (e) {}
      }

      return new Response(JSON.stringify({ results }), { status: 200, headers });
    }

    // ---- POST /api/public/emailList: 兼容原有 CloudMail 协议 ----
    if (path === "/api/public/emailList" && request.method === "POST") {
      const apiKey = request.headers.get("Authorization") || "";
      if (apiKey !== (env.CLOUDMAIL_API_KEY || "")) {
        return new Response(JSON.stringify({ code: 401, message: "unauthorized" }), { status: 401, headers });
      }
      try {
        const body = await request.json();
        const toEmail = (body.toEmail || "").toLowerCase().trim();
        if (!toEmail) {
          return new Response(JSON.stringify({ code: 400, message: "invalid recipient", data: [] }), { status: 400, headers });
        }

        let results = [];

        // 读 DO
        try {
          const id = env.NVIDIA_DO.idFromName("global");
          const stub = env.NVIDIA_DO.get(id);
          const r = await stub.fetch("https://do/list_mails?address=" + encodeURIComponent(toEmail));
          if (r.status === 200) {
            const data = JSON.parse(await r.text());
            results = data.results || [];
          }
        } catch (e) {}

        // 兜底读 KV
        if (results.length === 0) {
          try {
            const kvKey = "mails:" + toEmail;
            const data = await env.EMAIL_STORAGE.get(kvKey, "json");
            if (Array.isArray(data)) results = data;
          } catch (e) {}
        }

        // 转换为 CloudMail 格式
        const cloudmailData = results.map(m => ({
          toEmail: toEmail,
          fromEmail: m.from || "",
          subject: m.subject || "",
          content: m.text || m.html || "",
          html: m.html || "",
          text: m.text || "",
          date: m.created_at || "",
          id: m.id || "",
        }));

        return new Response(JSON.stringify({ code: 200, message: "ok", data: cloudmailData }), { status: 200, headers });
      } catch (e) {
        return new Response(JSON.stringify({ code: 500, message: e.message, data: [] }), { status: 500, headers });
      }
    }

    return new Response(JSON.stringify({ error: "not found" }), { status: 404, headers });
  },
};

// ===== 邮件解析工具 =====

function randomName() {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let s = "";
  for (let i = 0; i < 10; i++) s += chars[Math.floor(Math.random() * chars.length)];
  return s;
}

/** 从原始 RFC822 提取并解码 body */
function extractMailBody(raw) {
  const sep = raw.indexOf("\r\n\r\n");
  const headers = sep >= 0 ? raw.substring(0, sep) : raw;
  let body = sep >= 0 ? raw.substring(sep + 4) : "";
  const ctMatch = headers.match(/content-type:\s*multipart\/[^;]+;\s*boundary="?([^\s";]+)"?/i);
  const texts = [];
  if (ctMatch) {
    const boundary = ctMatch[1];
    const parts = body.split("--" + boundary);
    for (const part of parts) {
      const trimmed = part.replace(/^\r?\n/, "");
      if (!trimmed || trimmed.startsWith("--")) continue;
      const pSep = trimmed.indexOf("\r\n\r\n");
      if (pSep < 0) continue;
      const pHeaders = trimmed.substring(0, pSep);
      let pBody = trimmed.substring(pSep + 4);
      if (!/content-type:\s*text\/(plain|html)/i.test(pHeaders)) continue;
      pBody = decodeBody(pHeaders, pBody);
      pBody = pBody.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, " ").replace(/<script[^>]*>[\s\S]*?<\/script>/gi, " ").replace(/<[^>]+>/g, " ");
      texts.push(pBody);
    }
  } else {
    texts.push(decodeBody(headers, body));
  }
  return texts.join("\n");
}

function decodeBody(headers, body) {
  const cte = ((headers.match(/content-transfer-encoding:\s*(\S+)/i) || [, ''])[1] || '').toLowerCase();
  if (cte === 'base64') {
    try { return decodeUTF8(atob(body.replace(/\s/g, ''))); } catch (e) { return body; }
  } else if (cte === 'quoted-printable') {
    return body.replace(/=([0-9A-Fa-f]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16))).replace(/=\r?\n/g, '');
  }
  return body;
}

function decodeUTF8(binStr) {
  try {
    const bytes = new Uint8Array(binStr.length);
    for (let i = 0; i < binStr.length; i++) bytes[i] = binStr.charCodeAt(i) & 0xff;
    return new TextDecoder('utf-8').decode(bytes);
  } catch (e) { return binStr; }
}

/** 去 HTML 标签 + style/script 块 + CSS 颜色值（#RRGGBB） */
function stripHtml(text) {
  if (!text) return "";
  return text
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/#[0-9a-fA-F]{6}\b/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&#\d+;/g, " ")
    .replace(/\s+/g, " ");
}

function extractCode(text) {
  if (!text) return null;
  const m1 = text.match(/(?:verification code is|验证码|verify|verification code|code is)[^\d]{0,15}(\d[\d\s\-]{4,12}\d)/i);
  if (m1) {
    const d = m1[1].replace(/\D/g, "");
    if (d.length >= 4 && d.length <= 8) return d;
  }
  const m2 = text.match(/\b(\d{3}[\-\s]?\d{3})\b/);
  if (m2) return m2[1].replace(/\D/g, "");
  const m3 = text.match(/\b(\d{6})\b/);
  if (m3) return m3[1];
  return null;
}
