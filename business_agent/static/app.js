const translations = {
  en: {
    newChat: "New conversation", workspace: "WORKSPACE", assistant: "Business assistant",
    recent: "RECENT", currentSession: "Current session", live: "LIVE",
    privateNote: "Your business data stays in your local database.",
    workspaceName: "Business workspace", localAssistant: "Local assistant",
    language: "Language", eyebrow: "YOUR BUSINESS, IN FOCUS",
    welcomeLine1: "Good afternoon.", welcomeLine2: "What can I help you uncover?",
    welcomeCopy: "Ask questions about your orders, customers, and products. I’ll find the answer in your business data.",
    suggestionOrders: "Explore orders", suggestionOrdersSub: "Browse order status and details",
    suggestionInventory: "Check inventory", suggestionInventorySub: "See your product availability",
    suggestionCustomer: "Find a customer", suggestionCustomerSub: "Look up a profile or order history",
    suggestionSummary: "Get a summary", suggestionSummarySub: "Turn business data into insights",
    actingAs: "Acting as", decisionTrace: "Decision trace",
    messageLabel: "Message the assistant", composerPlaceholder: "Ask anything about your business…",
    sendHint: "to send", newlineHint: "for a new line", send: "Send",
    disclaimer: "AI can make mistakes. Verify important business decisions with your source data.",
    you: "You", assistantName: "Northstar", thinking: "Thinking through your request…",
    requestFailed: "The request could not be completed.", clearConfirm: "Clear this conversation and its in-memory context?",
    cleared: "Conversation cleared.", clearFailed: "Could not clear the conversation.",
    connectionError: "Could not connect to the local assistant.",
    roles: {
      customer_support: "Customer support",
      sales_analyst: "Sales analyst",
      inventory_manager: "Inventory manager",
      admin: "Administrator"
    },
    copied: "SQL copied to clipboard.", copy: "Copy SQL", sql: "Generated SQL",
    trace: "Decision summary", seconds: "s", focusComposer: "Type a message first."
  },
  zh: {
    newChat: "新建对话", workspace: "工作区", assistant: "业务助手",
    recent: "最近", currentSession: "当前会话", live: "在线",
    privateNote: "业务数据保留在本地数据库中。",
    workspaceName: "业务工作区", localAssistant: "本地助手",
    language: "语言", eyebrow: "让业务一目了然",
    welcomeLine1: "下午好。", welcomeLine2: "今天想了解什么业务？",
    welcomeCopy: "查询订单、客户和产品信息。我会从业务数据库中为你查找答案。",
    suggestionOrders: "浏览订单", suggestionOrdersSub: "查看订单状态和详情",
    suggestionInventory: "检查库存", suggestionInventorySub: "了解产品库存情况",
    suggestionCustomer: "查找客户", suggestionCustomerSub: "查询客户资料或订单历史",
    suggestionSummary: "业务概览", suggestionSummarySub: "汇总业务数据，发现关键信息",
    actingAs: "当前角色", decisionTrace: "决策摘要",
    messageLabel: "发送消息给助手", composerPlaceholder: "问问你的业务数据…",
    sendHint: "发送", newlineHint: "换行", send: "发送",
    disclaimer: "AI 可能会出错。重要业务决策请以源数据为准。",
    you: "你", assistantName: "Northstar", thinking: "正在分析你的问题…",
    requestFailed: "请求未能完成。", clearConfirm: "确定清除当前对话及其记忆？",
    cleared: "对话已清除。", clearFailed: "无法清除对话。",
    connectionError: "无法连接本地助手。",
    roles: {
      customer_support: "客服人员",
      sales_analyst: "销售分析",
      inventory_manager: "库存管理",
      admin: "管理员"
    },
    copied: "SQL 已复制。", copy: "复制 SQL", sql: "生成的 SQL",
    trace: "决策摘要", seconds: "秒", focusComposer: "请先输入问题。"
  }
};

const state = {
  language: localStorage.getItem("northstar-language") || "en",
  busy: false,
  config: null
};

const elements = {
  conversation: document.querySelector("#conversation"),
  welcome: document.querySelector("#welcome"),
  messageList: document.querySelector("#message-list"),
  form: document.querySelector("#chat-form"),
  input: document.querySelector("#message-input"),
  send: document.querySelector("#send-button"),
  role: document.querySelector("#role-select"),
  language: document.querySelector("#language-select"),
  trace: document.querySelector("#trace-toggle"),
  model: document.querySelector("#model-name"),
  toast: document.querySelector("#toast")
};

function t(key) {
  return translations[state.language][key] || key;
}

function localizeTrace(entry) {
  if (state.language === "zh") return entry;
  if (entry.includes("预检判断")) {
    return "Pre-check: required business details are missing; asking for clarification without calling the model or database.";
  }
  if (entry.includes("普通对话")) return "Route: general conversation; respond directly without querying the database.";
  if (entry.includes("信息不足")) return "Route: business request needs clarification; no database query will run.";
  if (entry.includes("业务数据查询")) return "Route: business-data query; preparing a read-only SQL statement.";
  const rows = entry.match(/返回 (\d+) 行/);
  if (rows) return `Query complete: ${rows[1]} row(s) returned (role limit ${entry.match(/上限 (\d+) 行/)?.[1] || "—"}).`;
  return entry;
}

function localize() {
  document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
  document.title = state.language === "zh" ? "Northstar · 业务助手" : "Northstar · Business Assistant";
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  elements.language.value = state.language;
  if (state.config) populateRoles();
  document.querySelectorAll(".message-meta[data-role-label]").forEach((node) => {
    node.textContent = node.dataset.roleLabel === "user" ? t("you") : t("assistantName");
  });
}

function populateRoles() {
  const selected = elements.role.value || "sales_analyst";
  elements.role.replaceChildren();
  state.config.roles.forEach((role) => {
    const option = document.createElement("option");
    option.value = role.id;
    option.textContent = translations[state.language].roles[role.id] || role.name;
    elements.role.append(option);
  });
  elements.role.value = selected;
}

async function request(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || t("requestFailed"));
  return result;
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  clearTimeout(showToast.timeout);
  showToast.timeout = setTimeout(() => elements.toast.classList.remove("visible"), 2600);
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    elements.conversation.scrollTo({ top: elements.conversation.scrollHeight, behavior: "smooth" });
  });
}

function parseTable(lines) {
  if (lines.length < 2 || !lines[0].startsWith("|") || !/^\|?[\s|:-]+\|?$/.test(lines[1])) {
    return null;
  }
  const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim().replaceAll("\\|", "|"));
  return { headers: cells(lines[0]), rows: lines.slice(2).filter((line) => line.startsWith("|")).map(cells) };
}

function appendAnswerContent(container, answer) {
  const lines = answer.split("\n");
  let current = [];
  let insideTable = false;
  const flushText = () => {
    if (!current.length) return;
    const paragraph = document.createElement("div");
    paragraph.className = "answer-text";
    paragraph.textContent = current.join("\n");
    container.append(paragraph);
    current = [];
  };
  for (const line of lines) {
    if (line.startsWith("|")) {
      if (!insideTable) flushText();
      current.push(line);
      insideTable = true;
      continue;
    }
    if (insideTable) {
      const table = parseTable(current);
      if (table) {
        const wrap = document.createElement("div");
        wrap.className = "message-table-wrap";
        const tableElement = document.createElement("table");
        tableElement.className = "message-table";
        const head = document.createElement("thead");
        const headRow = document.createElement("tr");
        table.headers.forEach((text) => {
          const cell = document.createElement("th");
          cell.textContent = text;
          headRow.append(cell);
        });
        head.append(headRow);
        const body = document.createElement("tbody");
        table.rows.forEach((row) => {
          const rowElement = document.createElement("tr");
          table.headers.forEach((_, index) => {
            const cell = document.createElement("td");
            cell.textContent = row[index] || "";
            rowElement.append(cell);
          });
          body.append(rowElement);
        });
        tableElement.append(head, body);
        wrap.append(tableElement);
        container.append(wrap);
      } else {
        current.forEach((text) => {
          const lineElement = document.createElement("div");
          lineElement.className = "answer-text";
          lineElement.textContent = text;
          container.append(lineElement);
        });
      }
      current = [];
      insideTable = false;
    }
    current.push(line);
  }
  if (insideTable) {
    const table = parseTable(current);
    if (!table) {
      current.forEach((text) => {
        const lineElement = document.createElement("div");
        lineElement.className = "answer-text";
        lineElement.textContent = text;
        container.append(lineElement);
      });
    } else {
      const wrap = document.createElement("div");
      wrap.className = "message-table-wrap";
      const tableElement = document.createElement("table");
      tableElement.className = "message-table";
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      table.headers.forEach((text) => {
        const cell = document.createElement("th");
        cell.textContent = text;
        headRow.append(cell);
      });
      head.append(headRow);
      const body = document.createElement("tbody");
      table.rows.forEach((row) => {
        const rowElement = document.createElement("tr");
        table.headers.forEach((_, index) => {
          const cell = document.createElement("td");
          cell.textContent = row[index] || "";
          rowElement.append(cell);
        });
        body.append(rowElement);
      });
      tableElement.append(head, body);
      wrap.append(tableElement);
      container.append(wrap);
    }
    current = [];
  }
  flushText();
}

function addMessage(role, content, metadata = {}) {
  elements.welcome.hidden = true;
  const message = document.createElement("article");
  message.className = `message ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "user" ? "You" : "✦";
  const contentColumn = document.createElement("div");
  contentColumn.className = "message-content";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.dataset.roleLabel = role;
  meta.textContent = role === "user" ? t("you") : t("assistantName");
  contentColumn.append(meta);

  if (metadata.pending) {
    const typing = document.createElement("div");
    typing.className = "typing";
    typing.setAttribute("aria-label", t("thinking"));
    for (let index = 0; index < 3; index += 1) typing.append(document.createElement("span"));
    contentColumn.append(typing);
  } else {
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    if (metadata.error) bubble.classList.add("assistant-error");
    if (role === "user" || metadata.error) {
      bubble.textContent = content;
    } else {
      appendAnswerContent(bubble, content);
    }
    contentColumn.append(bubble);
    if (metadata.sql) {
      const details = document.createElement("details");
      details.className = "message-details";
      const summary = document.createElement("summary");
      summary.textContent = `${t("sql")} · ${t("copy")}`;
      summary.title = t("copy");
      summary.addEventListener("click", (event) => {
        if (event.target === summary && navigator.clipboard) {
          navigator.clipboard.writeText(metadata.sql).then(() => showToast(t("copied")));
        }
      });
      const code = document.createElement("pre");
      code.textContent = metadata.sql;
      details.append(summary, code);
      contentColumn.append(details);
    }
    if (metadata.trace?.length) {
      const details = document.createElement("details");
      details.className = "message-details";
      const summary = document.createElement("summary");
      summary.textContent = t("trace");
      const list = document.createElement("ul");
      list.className = "trace-list";
      metadata.trace.forEach((entry) => {
        const item = document.createElement("li");
        item.textContent = localizeTrace(entry);
        list.append(item);
      });
      details.append(summary, list);
      contentColumn.append(details);
    }
    if (Number.isFinite(metadata.elapsed)) {
      const timing = document.createElement("div");
      timing.className = "message-meta";
      timing.textContent = `${metadata.elapsed}${t("seconds")}`;
      contentColumn.append(timing);
    }
  }
  message.append(avatar, contentColumn);
  elements.messageList.append(message);
  scrollToBottom();
  return message;
}

async function sendMessage(text) {
  const message = text.trim();
  if (!message || state.busy) return;
  addMessage("user", message);
  elements.input.value = "";
  resizeInput();
  state.busy = true;
  elements.send.disabled = true;
  const pending = addMessage("assistant", "", { pending: true });
  try {
    const result = await request("/api/chat", {
      message,
      role: elements.role.value,
      show_trace: elements.trace.checked
    });
    pending.remove();
    addMessage("assistant", result.answer, {
      sql: result.sql,
      trace: result.trace,
      elapsed: result.elapsed_seconds
    });
  } catch (error) {
    pending.remove();
    addMessage("assistant", error.message || t("connectionError"), { error: true });
  } finally {
    state.busy = false;
    elements.send.disabled = false;
    elements.input.focus();
  }
}

function resizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 130)}px`;
}

async function clearConversation() {
  if (state.busy) return;
  if (elements.messageList.childElementCount && !window.confirm(t("clearConfirm"))) return;
  try {
    await request("/api/reset", { role: elements.role.value });
    elements.messageList.replaceChildren();
    elements.welcome.hidden = false;
    showToast(t("cleared"));
  } catch {
    showToast(t("clearFailed"));
  }
}

async function initialize() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) throw new Error(t("connectionError"));
    state.config = await response.json();
    elements.model.textContent = `${state.config.provider} · ${state.config.model}`;
    populateRoles();
    localize();
  } catch (error) {
    elements.model.textContent = t("connectionError");
    showToast(error.message || t("connectionError"));
  }
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(elements.input.value);
});
elements.input.addEventListener("input", resizeInput);
elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});
elements.language.addEventListener("change", () => {
  state.language = elements.language.value;
  localStorage.setItem("northstar-language", state.language);
  localize();
});
document.querySelector("#new-chat").addEventListener("click", clearConversation);
document.querySelector("#clear-chat").addEventListener("click", clearConversation);
elements.role.addEventListener("change", () => {
  elements.messageList.replaceChildren();
  elements.welcome.hidden = false;
});
document.querySelectorAll(".suggestion-card").forEach((button) => {
  button.addEventListener("click", () => {
    const prompt = state.language === "zh" ? button.dataset.promptZh : button.dataset.promptEn;
    sendMessage(prompt);
  });
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.input.focus();
  }
});

localize();
initialize();
