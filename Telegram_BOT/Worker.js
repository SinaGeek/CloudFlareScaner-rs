const TELEGRAM_API = (token, method) => `https://api.telegram.org/bot${token}/${method}`;
const GEOIP_API = 'https://api.ip.sb/geoip/';

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

function text(data, status = 200) {
  return new Response(data, { status, headers: { 'content-type': 'text/plain; charset=utf-8' } });
}

function userFromMessage(message) {
  const from = message.from || {};
  return {
    id: String(from.id || ''),
    username: from.username || '',
    first_name: from.first_name || '',
    last_name: from.last_name || '',
    language_code: from.language_code || '',
    is_bot: Boolean(from.is_bot),
    is_premium: Boolean(from.is_premium),
  };
}

async function telegram(env, method, payload) {
  return fetch(TELEGRAM_API(env.BOT_TOKEN, method), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

async function sendMessage(env, chatId, text) {
  return telegram(env, 'sendMessage', { chat_id: chatId, text, parse_mode: 'HTML' });
}

function secretForUser(env, userId) {
  const seed = `${env.SECRET_SALT || 'pluribus'}:${userId}`;
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return `PLB-${Math.abs(hash >>> 0).toString(36).toUpperCase()}`;
}

async function ensureUser(env, user) {
  const secret = secretForUser(env, user.id);
  await env.DB.prepare(`
    INSERT INTO users (id, username, first_name, last_name, language_code, is_bot, is_premium, secret, added_ips, used_ips, reputation, banned_until, ban_count, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 100, 0, 0, strftime('%s','now'))
    ON CONFLICT(id) DO UPDATE SET
      username=excluded.username,
      first_name=excluded.first_name,
      last_name=excluded.last_name,
      language_code=excluded.language_code,
      is_premium=excluded.is_premium,
      updated_at=strftime('%s','now')
  `).bind(user.id, user.username, user.first_name, user.last_name, user.language_code, user.is_bot ? 1 : 0, user.is_premium ? 1 : 0, secret).run();
  return env.DB.prepare('SELECT * FROM users WHERE id = ?').bind(user.id).first();
}

async function getGeo(ip) {
  const response = await fetch(`${GEOIP_API}${encodeURIComponent(ip)}`, {
    headers: { 'accept': 'application/json', 'user-agent': 'PluribusScannerWorker/1.0' },
  });
  if (!response.ok) return {};
  return response.json();
}

function parseMetricPayload(text) {
  const parts = text.trim().split(/\s+/);
  if (parts[0] !== '/submit' || parts.length < 8) return null;
  const [_, ip, ping, jitter, latency, loss, upload, download] = parts;
  return {
    ip,
    ping: Number(ping),
    jitter: Number(jitter),
    latency: Number(latency),
    loss: Number(loss),
    upload: Number(upload),
    download: Number(download),
    timestamp: Math.floor(Date.now() / 1000),
  };
}

async function storeMeasurement(env, user, measurement) {
  const geo = await getGeo(measurement.ip);
  await env.DB.prepare(`
    INSERT INTO measurements (user_id, ip, ping, jitter, latency, loss, upload, download, country, isp, city, organization, created_at, flushed)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
  `).bind(
    user.id,
    measurement.ip,
    measurement.ping,
    measurement.jitter,
    measurement.latency,
    measurement.loss,
    measurement.upload,
    measurement.download,
    geo.country || '',
    geo.isp || '',
    geo.city || '',
    geo.organization || '',
    measurement.timestamp,
  ).run();
  await env.DB.prepare('UPDATE users SET added_ips = added_ips + 1, updated_at = strftime(\'%s\',\'now\') WHERE id = ?').bind(user.id).run();
}

async function queryTop(env, messageText) {
  const [, window = 'day', isp = 'all', city = 'all', metric = 'dl'] = messageText.trim().split(/\s+/);
  const analyzer = env.ANALYZER_URL;
  if (analyzer) {
    const url = new URL('/top', analyzer);
    url.searchParams.set('window', window);
    url.searchParams.set('isp', isp);
    url.searchParams.set('city', city);
    url.searchParams.set('metric', metric);
    url.searchParams.set('limit', '10');
    const response = await fetch(url, { headers: env.ANALYZER_TOKEN ? { authorization: `Bearer ${env.ANALYZER_TOKEN}` } : {} });
    if (response.ok) {
      const data = await response.json();
      return data.results || [];
    }
  }
  const metricColumn = { ping: 'ping', jitter: 'jitter', latency: 'latency', loss: 'loss', dl: 'download', ul: 'upload' }[metric] || 'download';
  const direction = ['download', 'upload'].includes(metricColumn) ? 'DESC' : 'ASC';
  return env.DB.prepare(`
    SELECT ip, AVG(${metricColumn}) AS score, AVG(ping) AS ping, AVG(download) AS download, COUNT(*) AS samples, isp, city
    FROM measurements
    WHERE created_at >= strftime('%s','now') - ?
      AND (? = 'all' OR lower(isp) = lower(?))
      AND (? = 'all' OR lower(city) = lower(?))
    GROUP BY ip
    ORDER BY score ${direction}
    LIMIT 10
  `).bind(window === '4h' ? 14400 : window === 'week' ? 604800 : 86400, isp, isp, city, city).all().then((r) => r.results || []);
}

function formatTop(rows) {
  if (!rows.length) return 'No clean IP results are available for that filter yet.';
  return rows.map((row, index) => `${index + 1}. <code>${row.ip}</code> score=${Number(row.score).toFixed(2)} samples=${row.samples}`).join('\n');
}

async function handleTelegram(env, update) {
  const message = update.message || update.edited_message;
  if (!message || !message.text) return json({ ok: true });
  const chatId = message.chat.id;
  const user = await ensureUser(env, userFromMessage(message));
  const body = message.text.trim();

  if (body === '/start') {
    await sendMessage(env, chatId, `Welcome to Pluribus Scanner.\nYour secret code is <code>${user.secret}</code>.\n\nCommands:\n/secret\n/submit IP ping jitter latency loss upload download\n/top day all all dl`);
  } else if (body === '/secret') {
    await sendMessage(env, chatId, `Your secret code is <code>${user.secret}</code>.`);
  } else if (body.startsWith('/submit')) {
    const measurement = parseMetricPayload(body);
    if (!measurement) {
      await sendMessage(env, chatId, 'Usage: /submit IP ping jitter latency loss upload download');
    } else {
      await storeMeasurement(env, user, measurement);
      await sendMessage(env, chatId, `Saved <code>${measurement.ip}</code>. Thank you for helping the clean IP database.`);
    }
  } else if (body.startsWith('/top')) {
    await sendMessage(env, chatId, formatTop(await queryTop(env, body)));
  } else {
    await sendMessage(env, chatId, 'Unknown command. Use /start for help.');
  }
  return json({ ok: true });
}

async function flushToAnalyzer(env) {
  if (!env.ANALYZER_URL) return { skipped: 'ANALYZER_URL is not configured' };
  const rows = await env.DB.prepare('SELECT * FROM measurements WHERE flushed = 0 ORDER BY created_at ASC LIMIT 500').all();
  const measurements = rows.results || [];
  if (!measurements.length) return { flushed: 0 };
  const response = await fetch(new URL('/ingest', env.ANALYZER_URL), {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(env.ANALYZER_TOKEN ? { authorization: `Bearer ${env.ANALYZER_TOKEN}` } : {}),
    },
    body: JSON.stringify({ measurements }),
  });
  if (!response.ok) return { error: `analyzer returned ${response.status}` };
  const ids = measurements.map((row) => row.id);
  await env.DB.prepare(`UPDATE measurements SET flushed = 1 WHERE id IN (${ids.map(() => '?').join(',')})`).bind(...ids).run();
  return { flushed: ids.length };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'GET' && url.pathname === '/health') return json({ ok: true, service: 'pluribus-worker' });
    if (request.method === 'POST' && url.pathname === `/telegram/${env.WEBHOOK_SECRET}`) {
      return handleTelegram(env, await request.json());
    }
    if (request.method === 'POST' && url.pathname === '/flush') return json(await flushToAnalyzer(env));
    return text('Not found', 404);
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(flushToAnalyzer(env));
  },
};
