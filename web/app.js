const state = {
  apiUrl: "",
  authToken: "",
  lastTranslation: null,
};

const $ = (id) => document.getElementById(id);

const INTENT_LABELS = {
  add_ssr_meal: "添加特殊餐食 SSR",
  add_contact_phone: "添加联系电话",
  cancel_segment: "取消航段",
  flight_search_oneway: "查询单程航班",
  flight_search_roundtrip: "查询往返航班",
  flight_search_multicity: "查询多段航班",
};

const STATUS_LABELS = {
  ready_for_confirm: "待确认",
  auto_executable: "可自动执行",
  needs_review: "需要审核",
  rejected: "已拒绝",
  failed: "失败",
  executed: "已执行",
};

const RISK_LABELS = {
  low: "可直接确认",
  medium: "建议复核后确认",
  high: "需要主管审核",
};

const EXAMPLES = {
  flight: {
    text: "下个月23号13点50北京到成都中转上海东航",
    context: { passenger_refs: ["P1"], segment_refs: ["S1", "S2"], version: "v1" },
  },
  ssr: {
    text: "给第一个旅客第二段加一个东航素食餐",
    context: { passenger_refs: ["P1"], segment_refs: ["S2"], version: "v1" },
  },
  roundtrip: {
    text: "查一下7月20号上午北京到上海，7月23号晚上上海回北京的东航往返航班",
    context: { passenger_refs: ["P1"], segment_refs: ["S1", "S2"], version: "v1" },
  },
  multicity: {
    text: "帮我查7月20号北京到上海，7月22号上海到成都的多段航班",
    context: { passenger_refs: ["P1"], segment_refs: ["S1", "S2"], version: "v1" },
  },
  direct: {
    text: "查7月25号上午北京到上海东航直飞航班",
    context: { passenger_refs: ["P1"], segment_refs: ["S1"], version: "v1" },
  },
};

function setStatus(text, kind = "") {
  const el = $("status");
  el.textContent = text;
  el.className = `status ${kind}`.trim();
}

function label(value, labels) {
  return labels[value] || value || "-";
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function clearResult() {
  $("resultHint").textContent = "等待生成";
  $("intent").textContent = "-";
  $("translationStatus").textContent = "-";
  $("risk").textContent = "-";
  $("commandBox").value = "";
  $("copyCommand").disabled = true;
  $("execute").disabled = true;
  $("executionHint").textContent = "可先复制指令进行核对";
  $("executionMessage").classList.add("hidden");
  state.lastTranslation = null;
}

function showError(error) {
  $("translationJson").textContent = pretty({ error: error.message });
  $("resultHint").textContent = "未能生成，请检查输入或稍后重试";
  $("commandBox").value = error.message;
  $("copyCommand").disabled = true;
  $("execute").disabled = true;
  setStatus("生成失败", "error");
}

function loadExample(name) {
  const example = EXAMPLES[name];
  if (!example) {
    return;
  }
  $("userText").value = example.text;
  $("pnrContext").value = pretty(example.context);
  $("contextDebug").textContent = $("pnrContext").value;
  clearResult();
}

async function loadConfig() {
  state.apiUrl = window.PNR_APP_CONFIG?.apiUrl || "";
  state.authToken = window.PNR_APP_CONFIG?.idToken || localStorage.getItem("pnrJwt") || "";
  $("connectionStatus").textContent = state.apiUrl ? "演示环境已连接" : "演示环境未配置";
  $("contextDebug").textContent = $("pnrContext").value;
}

async function apiPost(path, body) {
  const token = state.authToken.trim();
  if (!token) {
    throw new Error("演示环境尚未完成登录配置，请联系工作人员初始化会话");
  }
  const response = await fetch(`${state.apiUrl}${path}`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload;
}

async function translate() {
  setStatus("正在生成...");
  $("resultHint").textContent = "正在识别需求";
  $("execute").disabled = true;
  $("executionJson").textContent = "";
  $("executionMessage").textContent = "确认执行后，系统会在这里显示处理结果。";
  $("executionMessage").classList.add("hidden");
  $("executionHint").textContent = "尚未执行";
  const pnrContext = JSON.parse($("pnrContext").value);
  $("contextDebug").textContent = pretty(pnrContext);
  const payload = await apiPost("/v1/pnr/translate", {
    session_id: `web-${Date.now()}`,
    pnr_context_id: "web-context",
    user_text: $("userText").value,
    pnr_context: pnrContext,
  });
  state.lastTranslation = payload;
  $("intent").textContent = label(payload.intent, INTENT_LABELS);
  $("translationStatus").textContent = label(payload.status, STATUS_LABELS);
  $("risk").textContent = label(payload.risk_level, RISK_LABELS);
  $("commandBox").value = payload.command_preview_redacted || "";
  $("translationJson").textContent = pretty(payload);
  $("execute").disabled = payload.status !== "ready_for_confirm" && payload.status !== "auto_executable";
  $("copyCommand").disabled = !payload.command_preview_redacted;
  $("resultHint").textContent = payload.command_preview_redacted ? "已生成，可复制核对" : "需要补充信息";
  setStatus("已生成", "ok");
}

async function execute() {
  if (!state.lastTranslation) {
    return;
  }
  setStatus("正在执行...");
  const pnrContext = JSON.parse($("pnrContext").value);
  const payload = await apiPost("/v1/pnr/execute", {
    translation_id: state.lastTranslation.translation_id,
    idempotency_key: `web-${Date.now()}`,
    pnr_context_version: pnrContext.version || "v1",
  });
  $("executionJson").textContent = pretty(payload);
  $("executionMessage").textContent = payload.status ? `处理状态：${label(payload.status, STATUS_LABELS)}` : "系统已提交执行。";
  $("executionMessage").classList.remove("hidden");
  $("executionHint").textContent = "已提交";
  setStatus("已执行", "ok");
}

function wireEvents() {
  $("translate").addEventListener("click", () => translate().catch(showError));
  $("execute").addEventListener("click", () => execute().catch((error) => {
    $("executionJson").textContent = pretty({ error: error.message });
    $("executionMessage").textContent = error.message;
    $("executionMessage").classList.remove("hidden");
    $("executionHint").textContent = "执行失败";
    setStatus("执行失败", "error");
  }));
  $("copyCommand").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("commandBox").value);
    setStatus("指令已复制", "ok");
  });
  $("examples").addEventListener("click", (event) => {
    const button = event.target.closest("[data-example]");
    if (button) {
      loadExample(button.dataset.example);
      setStatus("已填入示例");
    }
  });
}

loadConfig();
wireEvents();
