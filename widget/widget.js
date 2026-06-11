/**
 * Nata Portuguese Bakery — Embeddable Chat Widget
 * Embed with: <script src="https://shopify.projekts.pk/widget.js"></script>
 *
 * ─── CONFIG ──────────────────────────────────────────────────────────────────
 * Change these values to customise the widget without touching the rest.
 */
(function () {
  "use strict";

  // ── Configurable constants ────────────────────────────────────────────────
  var API_BASE_URL    = "https://shopify.projekts.pk";   // Backend URL
  var BOT_NAME        = "Nata";
  var BOT_LOGO_URL    = "https://www.nata.co.nz/cdn/shop/files/top_logo.png?v=1613715845&width=150";
  var USER_AVATAR_EMOJI = "👤";
  var WELCOME_MESSAGE = "Olá! 👋 Welcome to Nata Portuguese Bakery!\n\nI'm here to help with orders, delivery, wholesale enquiries, and anything else. What can I help you with today?";
  var WIDGET_CSS_URL  = API_BASE_URL + "/widget.css";
  var STORAGE_KEY     = "shopify_chat_session_id";

  // Quick reply suggestions shown on first open
  var QUICK_REPLIES = [
    "Order info",
    "Delivery & pickup",
    "Wholesale",
    "Where to buy",
  ];

  // ── Session ID ────────────────────────────────────────────────────────────
  function getOrCreateSessionId() {
    var stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
    var id = (typeof crypto !== "undefined" && crypto.randomUUID)
      ? crypto.randomUUID()
      : "sess_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
    localStorage.setItem(STORAGE_KEY, id);
    return id;
  }

  var SESSION_ID = getOrCreateSessionId();

  // ── Inject CSS ────────────────────────────────────────────────────────────
  function injectCSS() {
    if (document.getElementById("shopify-chat-css")) return;
    var link = document.createElement("link");
    link.id   = "shopify-chat-css";
    link.rel  = "stylesheet";
    link.href = WIDGET_CSS_URL;
    document.head.appendChild(link);
  }

  // ── Build DOM ─────────────────────────────────────────────────────────────
  function buildWidget() {
    // Toggle button
    var toggle = document.createElement("button");
    toggle.id = "shopify-chat-toggle";
    toggle.setAttribute("aria-label", "Open chat");
    toggle.innerHTML = [
      '<img id="chat-icon-open" src="' + BOT_LOGO_URL + '" alt="Nata" />',
      '<svg viewBox="0 0 24 24" id="chat-icon-close" style="display:none">',
        '<line x1="18" y1="6" x2="6" y2="18"/>',
        '<line x1="6" y1="6" x2="18" y2="18"/>',
      '</svg>',
      '<span id="shopify-chat-badge"></span>',
    ].join("");

    // Chat window
    var win = document.createElement("div");
    win.id = "shopify-chat-window";
    win.className = "chat-hidden";
    win.setAttribute("role", "dialog");
    win.setAttribute("aria-label", "Nata Portuguese Bakery chat");
    win.innerHTML = [
      // Header
      '<div id="shopify-chat-header">',
        '<div class="chat-avatar"><img src="' + BOT_LOGO_URL + '" alt="Nata" /></div>',
        '<div class="chat-header-info">',
          '<div class="chat-header-name">' + BOT_NAME + '</div>',
          '<div class="chat-header-status">',
            '<span class="chat-status-dot"></span> Online — replies instantly',
          '</div>',
        '</div>',
        '<button id="shopify-chat-close" aria-label="Close chat">✕</button>',
      '</div>',

      // Messages
      '<div id="shopify-chat-messages" role="log" aria-live="polite"></div>',

      // Quick replies
      '<div id="shopify-chat-quick-replies"></div>',

      // Input area
      '<div id="shopify-chat-input-area">',
        '<textarea',
          ' id="shopify-chat-input"',
          ' placeholder="Type your message…"',
          ' rows="1"',
          ' aria-label="Chat message input"',
        '></textarea>',
        '<button id="shopify-chat-send" aria-label="Send message">',
          '<svg viewBox="0 0 24 24"><path d="M22 2L11 13"/><path d="M22 2L15 22l-4-9-9-4 20-7z"/></svg>',
        '</button>',
      '</div>',

      // Brand footer
      '<div class="chat-footer-brand">Powered by AI · nata.co.nz</div>',
    ].join("");

    document.body.appendChild(toggle);
    document.body.appendChild(win);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function formatTime() {
    var d = new Date();
    return d.getHours().toString().padStart(2, "0") + ":" +
           d.getMinutes().toString().padStart(2, "0");
  }

  function scrollToBottom() {
    var msgs = document.getElementById("shopify-chat-messages");
    if (msgs) msgs.scrollTop = msgs.scrollHeight;
  }

  function autoResizeTextarea() {
    var ta = document.getElementById("shopify-chat-input");
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 100) + "px";
  }

  // ── Message Rendering ─────────────────────────────────────────────────────
  function appendMessage(role, text) {
    var msgs = document.getElementById("shopify-chat-messages");
    if (!msgs) return;

    var wrap = document.createElement("div");
    wrap.className = "chat-message " + role;

    var avatarEl = document.createElement("div");
    avatarEl.className = "chat-message-avatar";
    if (role === "user") {
      avatarEl.textContent = USER_AVATAR_EMOJI;
    } else {
      avatarEl.innerHTML = '<img src="' + BOT_LOGO_URL + '" alt="Nata" />';
    }

    var bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    bubble.textContent = text;  // safe — no innerHTML

    var col = document.createElement("div");
    col.style.display = "flex";
    col.style.flexDirection = "column";
    col.style.maxWidth = "78%";
    if (role === "user") col.style.alignItems = "flex-end";

    var ts = document.createElement("div");
    ts.className = "chat-timestamp";
    ts.textContent = formatTime();

    col.appendChild(bubble);
    col.appendChild(ts);
    wrap.appendChild(avatarEl);
    wrap.appendChild(col);
    msgs.appendChild(wrap);
    scrollToBottom();
    return wrap;
  }

  function showTyping() {
    var msgs = document.getElementById("shopify-chat-messages");
    if (!msgs) return null;

    var wrap = document.createElement("div");
    wrap.className = "chat-message bot";
    wrap.id = "shopify-typing-indicator";

    var avatarEl = document.createElement("div");
    avatarEl.className = "chat-message-avatar";
    avatarEl.innerHTML = '<img src="' + BOT_LOGO_URL + '" alt="Nata" />';

    var typing = document.createElement("div");
    typing.className = "chat-typing";
    typing.innerHTML = '<div class="chat-typing-dot"></div><div class="chat-typing-dot"></div><div class="chat-typing-dot"></div>';

    wrap.appendChild(avatarEl);
    wrap.appendChild(typing);
    msgs.appendChild(wrap);
    scrollToBottom();
    return wrap;
  }

  function removeTyping() {
    var el = document.getElementById("shopify-typing-indicator");
    if (el) el.remove();
  }

  // ── Quick Replies ─────────────────────────────────────────────────────────
  function renderQuickReplies(replies) {
    var container = document.getElementById("shopify-chat-quick-replies");
    if (!container) return;
    container.innerHTML = "";
    replies.forEach(function (text) {
      var btn = document.createElement("button");
      btn.className = "chat-quick-btn";
      btn.textContent = text;
      btn.onclick = function () {
        container.innerHTML = "";  // hide after first use
        sendMessage(text);
      };
      container.appendChild(btn);
    });
  }

  // ── Unread Badge ──────────────────────────────────────────────────────────
  var _unread = 0;
  var _isOpen = false;

  function incrementBadge() {
    if (_isOpen) return;
    _unread++;
    var badge = document.getElementById("shopify-chat-badge");
    if (badge) {
      badge.textContent = _unread > 9 ? "9+" : String(_unread);
      badge.style.display = "flex";
    }
  }

  function clearBadge() {
    _unread = 0;
    var badge = document.getElementById("shopify-chat-badge");
    if (badge) badge.style.display = "none";
  }

  // ── Send Message ──────────────────────────────────────────────────────────
  var _isSending = false;

  function sendMessage(text) {
    if (_isSending || !text || !text.trim()) return;
    _isSending = true;

    var sendBtn = document.getElementById("shopify-chat-send");
    var input   = document.getElementById("shopify-chat-input");
    if (sendBtn) sendBtn.disabled = true;
    if (input)   { input.value = ""; autoResizeTextarea(); }

    appendMessage("user", text.trim());
    var typingEl = showTyping();

    fetch(API_BASE_URL + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SESSION_ID, message: text.trim() }),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        removeTyping();
        var reply = (data && data.reply) ? data.reply : "Sorry, I could not get a response. Please try again.";
        appendMessage("bot", reply);
        incrementBadge();
      })
      .catch(function (err) {
        console.error("[ChatWidget] Error:", err);
        removeTyping();
        appendMessage("bot", "⚠️ Something went wrong. Please try again in a moment.");
      })
      .finally(function () {
        _isSending = false;
        if (sendBtn) sendBtn.disabled = false;
        if (input)   input.focus();
      });
  }

  // ── Open / Close ──────────────────────────────────────────────────────────
  var _welcomeSent = false;

  function openChat() {
    _isOpen = true;
    clearBadge();
    var toggle = document.getElementById("shopify-chat-toggle");
    var win    = document.getElementById("shopify-chat-window");
    var iOpen  = document.getElementById("chat-icon-open");
    var iClose = document.getElementById("chat-icon-close");
    if (toggle) toggle.classList.add("chat-is-open");
    if (win)    win.classList.remove("chat-hidden");
    if (iOpen)  iOpen.style.display  = "none";
    if (iClose) iClose.style.display = "block";

    if (!_welcomeSent) {
      _welcomeSent = true;
      setTimeout(function () {
        appendMessage("bot", WELCOME_MESSAGE);
        renderQuickReplies(QUICK_REPLIES);
        scrollToBottom();
      }, 200);
    }

    setTimeout(function () {
      var input = document.getElementById("shopify-chat-input");
      if (input) input.focus();
    }, 350);
  }

  function closeChat() {
    _isOpen = false;
    var toggle = document.getElementById("shopify-chat-toggle");
    var win    = document.getElementById("shopify-chat-window");
    var iOpen  = document.getElementById("chat-icon-open");
    var iClose = document.getElementById("chat-icon-close");
    if (toggle) toggle.classList.remove("chat-is-open");
    if (win)    win.classList.add("chat-hidden");
    if (iOpen)  iOpen.style.display  = "block";
    if (iClose) iClose.style.display = "none";
  }

  // ── Event Listeners ───────────────────────────────────────────────────────
  function bindEvents() {
    document.getElementById("shopify-chat-toggle").addEventListener("click", function () {
      _isOpen ? closeChat() : openChat();
    });

    document.getElementById("shopify-chat-close").addEventListener("click", closeChat);

    var input = document.getElementById("shopify-chat-input");
    input.addEventListener("input", autoResizeTextarea);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage(input.value);
      }
    });

    document.getElementById("shopify-chat-send").addEventListener("click", function () {
      sendMessage(document.getElementById("shopify-chat-input").value);
    });

    // Close on Escape
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && _isOpen) closeChat();
    });
  }

  // ── Init ──────────────────────────────────────────────────────────────────
  function init() {
    injectCSS();
    buildWidget();
    bindEvents();

    // Show unread badge after 3 seconds to grab attention on first visit
    setTimeout(function () {
      if (!_isOpen) {
        incrementBadge();
      }
    }, 3000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
