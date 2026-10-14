/**
 * LLM Proxy Server — bridges WorkBuddy Cloud SDK (streaming) to the
 * Python backend's synchronous OpenAI-compatible /chat/completions endpoint.
 *
 * The WorkBuddy Cloud LLM API:
 *   - Only supports streaming (SSE)
 *   - Uses keyless auth via publishableKey + endpoint
 *   - Requires the @tencent-ai/workbuddy-cloud-sdk JavaScript SDK
 *
 * This proxy:
 *   1. Receives a standard OpenAI chat/completions request (non-streaming)
 *   2. Calls cloud.llm.chat.completions.create() with stream:true
 *   3. Collects all SSE chunks into a single response
 *   4. Returns a standard OpenAI chat/completions JSON response
 *
 * Configuration:
 *   Read from proxy-config.json (created by the activate step) or env vars:
 *   - CLOUD_ENDPOINT: WorkBuddy Cloud service endpoint
 *   - CLOUD_PUBLISHABLE_KEY: WorkBuddy Cloud publishable key
 *
 * Usage:
 *   node llm-proxy/server.js
 *   Listens on http://127.0.0.1:8877
 */

const http = require('http');

// Load config from proxy-config.json or environment variables
const fs = require('fs');
const path = require('path');

let cloudConfig = null;
const configPath = path.join(__dirname, 'proxy-config.json');
if (fs.existsSync(configPath)) {
  cloudConfig = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
} else {
  cloudConfig = {
    endpoint: process.env.CLOUD_ENDPOINT || '',
    publishableKey: process.env.CLOUD_PUBLISHABLE_KEY || '',
  };
}

if (!cloudConfig.endpoint || !cloudConfig.publishableKey) {
  console.error('[LLM Proxy] Missing cloud configuration.');
  console.error('[LLM Proxy] Create proxy-config.json with endpoint and publishableKey,');
  console.error('[LLM Proxy] or set CLOUD_ENDPOINT and CLOUD_PUBLISHABLE_KEY env vars.');
  console.error('[LLM Proxy] The WorkBuddy Cloud Service must be activated first.');
  process.exit(1);
}

// Initialize the WorkBuddy Cloud SDK
let cloud = null;
try {
  const { createWorkBuddyCloud } = require('@tencent-ai/workbuddy-cloud-sdk');
  cloud = createWorkBuddyCloud({
    endpoint: cloudConfig.endpoint,
    publishableKey: cloudConfig.publishableKey,
  });
  console.log('[LLM Proxy] WorkBuddy Cloud SDK initialized.');
  console.log('[LLM Proxy] Endpoint:', cloudConfig.endpoint);
} catch (err) {
  console.error('[LLM Proxy] Failed to load WorkBuddy Cloud SDK:', err.message);
  console.error('[LLM Proxy] Install it with: npm install @tencent-ai/workbuddy-cloud-sdk@dev');
  process.exit(1);
}

// Cache the model list
let cachedModels = null;
async function getModels() {
  if (cachedModels) return cachedModels;
  try {
    const models = await cloud.llm.models.list();
    cachedModels = models;
    console.log('[LLM Proxy] Available models:', models.map(m => `${m.id} (${m.name || 'unnamed'})`).join(', '));
    return models;
  } catch (err) {
    console.error('[LLM Proxy] Failed to list models:', err.message);
    return [];
  }
}

// Pick a default model
async function pickModel(requestedModel) {
  const models = await getModels();
  if (models.length === 0) {
    throw new Error('No models available. Check your cloud service configuration.');
  }
  // LLM_PROXY_MODEL pins a model; "proxy" or empty picks the first enabled one.
  if ((!requestedModel || requestedModel === 'proxy') && process.env.LLM_PROXY_MODEL) requestedModel = process.env.LLM_PROXY_MODEL;
  if (!requestedModel || requestedModel === 'proxy') {
    const enabled = models.find(m => m.disabled !== true);
    if (!enabled) throw new Error('No enabled model available.');
    return enabled.id;
  }
  // If requested model matches, use it
  const match = models.find(m => m.id === requestedModel);
  if (match && match.disabled !== true) return match.id;
  // Fall back to first enabled
  const enabled = models.find(m => m.disabled !== true);
  if (!enabled) throw new Error('No enabled model available.');
  console.warn(`[LLM Proxy] Requested model "${requestedModel}" not found or disabled, using "${enabled.id}".`);
  return enabled.id;
}

// Call the WorkBuddy Cloud LLM with streaming, collect full response
async function callLLM(payload) {
  const model = await pickModel(payload.model);

  // Build messages — ensure system message is first
  let messages = payload.messages || [];
  if (!messages.some(m => m.role === 'system')) {
    messages = [{ role: 'system', content: 'You are a helpful assistant. Be concise and helpful.' }, ...messages];
  }

  const createParams = {
    model,
    messages,
    stream: true,
    stream_options: { include_usage: true },
  };

  // Pass through temperature if provided
  if (payload.temperature !== undefined) createParams.temperature = payload.temperature;
  if (payload.top_p !== undefined) createParams.top_p = payload.top_p;

  // Pass through tools if provided
  if (payload.tools && payload.tools.length > 0) {
    createParams.tools = payload.tools;
    createParams.tool_choice = payload.tool_choice || 'auto';
  }

  // Pass through response_format if provided
  if (payload.response_format) {
    createParams.response_format = payload.response_format;
  }

  // Collect streaming response
  let content = '';
  let reasoning = '';
  let finishReason = null;
  let usage = null;
  let toolCalls = [];
  const toolCallMap = new Map();

  for await (const chunk of cloud.llm.chat.completions.create(createParams)) {
    const choice = chunk.choices && chunk.choices[0];
    if (!choice) continue;

    const delta = choice.delta;
    if (delta) {
      if (delta.content) content += delta.content;
      if (delta.reasoning_content) reasoning += delta.reasoning_content;
      if (delta.tool_calls) {
        for (const tc of delta.tool_calls) {
          const existing = toolCallMap.get(tc.index) || { id: '', type: 'function', function: { name: '', arguments: '' } };
          if (tc.id) existing.id = tc.id;
          if (tc.type) existing.type = tc.type;
          if (tc.function) {
            if (tc.function.name) existing.function.name = tc.function.name;
            if (tc.function.arguments) existing.function.arguments += tc.function.arguments;
          }
          toolCallMap.set(tc.index, existing);
        }
      }
    }

    if (choice.finish_reason) {
      finishReason = choice.finish_reason;
    }

    if (chunk.usage) {
      usage = chunk.usage;
    }
  }

  // Convert tool call map to array. Some models stream tool calls without an id; the backend needs one
  // to match each tool result to its call, so assign a stable fallback.
  toolCalls = Array.from(toolCallMap.entries())
    .filter(([, tc]) => tc.id || tc.function.name)
    .map(([index, tc]) => ({ ...tc, id: tc.id || `call_${Date.now()}_${index}` }));

  return {
    content,
    reasoning,
    finishReason: finishReason || 'stop',
    usage: usage || { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
    toolCalls,
    model,
  };
}

// Build an OpenAI-compatible response
function buildResponse(result, requestId) {
  const message = {
    role: 'assistant',
    content: result.content || null,
  };

  if (result.toolCalls.length > 0) {
    message.tool_calls = result.toolCalls;
  }

  return {
    id: requestId,
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model: result.model,
    choices: [{
      index: 0,
      message,
      finish_reason: result.finishReason,
    }],
    usage: result.usage,
  };
}

// Create HTTP server
const server = http.createServer(async (req, res) => {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // Health check
  if (req.url === '/health' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true, proxy: 'llm-proxy', cloud: 'connected' }));
    return;
  }

  // Models list
  if (req.url === '/models' && req.method === 'GET') {
    try {
      const models = await getModels();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ models }));
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    }
    return;
  }

  // Chat completions
  if (req.url === '/chat/completions' && req.method === 'POST') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', async () => {
      try {
        const payload = JSON.parse(body);
        const requestId = 'chatcmpl-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
        console.log(`[LLM Proxy] Request ${requestId}: model=${payload.model}, messages=${payload.messages?.length}, tools=${payload.tools?.length || 0}`);

        const result = await callLLM(payload);
        const response = buildResponse(result, requestId);

        console.log(`[LLM Proxy] Response ${requestId}: finish=${result.finishReason}, content=${result.content.length}chars, tool_calls=${result.toolCalls.length}`);

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(response));
      } catch (err) {
        console.error('[LLM Proxy] Error:', err.message);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          error: {
            message: err.message,
            type: 'proxy_error',
            code: null,
          },
        }));
      }
    });
    return;
  }

  // Unknown route
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Not found' }));
});

const PORT = 8877;
server.listen(PORT, '127.0.0.1', async () => {
  console.log(`[LLM Proxy] Server running on http://127.0.0.1:${PORT}`);
  console.log('[LLM Proxy] Endpoints: POST /chat/completions, GET /models, GET /health');
  // Pre-fetch models on startup
  await getModels();
});

// Handle graceful shutdown
process.on('SIGINT', () => {
  console.log('[LLM Proxy] Shutting down...');
  server.close();
  process.exit(0);
});
