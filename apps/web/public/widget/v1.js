/*!
 * Messer chat widget v1 — embeds a published Messer agent in any website.
 *
 *   <script src="https://<messer>/widget/v1.js" data-project="<org>/<project>" data-agent="<agent>" async></script>
 *
 * Optional attributes: data-org (when data-project is only the project slug), data-label (launcher text),
 * data-position="right|left", data-accent="#RRGGBB", data-lang="es|en", data-open="true".
 * The chat runs in an iframe served from the Messer origin (/embed/…); the host page never sees the conversation.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script || script.getAttribute("data-messer-loaded")) return;
  script.setAttribute("data-messer-loaded", "1");

  var project = script.getAttribute("data-project") || "";
  var org = script.getAttribute("data-org") || "";
  if (project.indexOf("/") > 0) {
    var parts = project.split("/");
    org = parts[0];
    project = parts[1];
  }
  var agent = script.getAttribute("data-agent") || "";
  if (!org || !project || !agent) {
    if (window.console) console.error("[messer] widget: data-project=\"<org>/<project>\" and data-agent are required");
    return;
  }
  var origin = new URL(script.src, window.location.href).origin;
  var lang = (script.getAttribute("data-lang") || document.documentElement.lang || "es").slice(0, 2).toLowerCase();
  var text = lang === "en" ? { open: "Open chat", close: "Close chat", title: "Chat" } : { open: "Abrir chat", close: "Cerrar chat", title: "Chat" };
  var label = script.getAttribute("data-label") || "";
  var accent = script.getAttribute("data-accent") || "";
  if (!/^#[0-9a-fA-F]{6}$/.test(accent)) accent = "#D52B1E";
  var side = script.getAttribute("data-position") === "left" ? "left" : "right";
  var src = origin + "/embed/" + encodeURIComponent(org) + "/" + encodeURIComponent(project) + "/chat/" + encodeURIComponent(agent) + (lang === "en" ? "?lang=en" : "");

  var host = document.createElement("div");
  host.setAttribute("data-messer-widget", "");
  var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

  var style = document.createElement("style");
  style.textContent =
    ":host{all:initial}" +
    ".launcher{position:fixed;bottom:20px;" + side + ":20px;z-index:2147483646;display:inline-flex;align-items:center;gap:8px;height:48px;min-width:48px;padding:0 16px;border:0;border-radius:24px;background:" + accent + ";color:#fff;font:600 14px/1 system-ui,-apple-system,'Segoe UI',sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.18);cursor:pointer}" +
    ".launcher:focus-visible{outline:3px solid #111;outline-offset:2px}" +
    ".launcher svg{width:20px;height:20px;flex:none}" +
    ".panel{position:fixed;bottom:80px;" + side + ":20px;z-index:2147483647;width:380px;height:600px;max-width:calc(100vw - 40px);max-height:calc(100vh - 100px);border:1px solid #e7e5e1;border-radius:8px;overflow:hidden;background:#fff;box-shadow:0 12px 40px rgba(0,0,0,.2);display:none}" +
    ".panel.open{display:block}" +
    ".panel iframe{width:100%;height:100%;border:0;display:block}" +
    "@media (max-width:480px){.panel{inset:0;width:100%;height:100%;max-width:none;max-height:none;border-radius:0}.panel.open + .launcher,.launcher.open{bottom:auto;top:12px;" + side + ":12px;height:40px;min-width:40px;padding:0 12px}}";

  var panel = document.createElement("div");
  panel.className = "panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", label || text.title);
  var frame = null;

  var button = document.createElement("button");
  button.type = "button";
  button.className = "launcher";
  button.setAttribute("aria-expanded", "false");
  var chatIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
  var closeIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  function render(open) {
    button.innerHTML = (open ? closeIcon : chatIcon) + (label && !open ? "<span></span>" : "");
    var span = button.querySelector("span");
    if (span) span.textContent = label;
    button.setAttribute("aria-label", open ? text.close : label || text.open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
    button.className = open ? "launcher open" : "launcher";
  }

  function setOpen(open) {
    if (open && !frame) {
      frame = document.createElement("iframe");
      frame.src = src;
      frame.title = label || text.title;
      frame.setAttribute("allow", "clipboard-write");
      frame.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
      panel.appendChild(frame);
    }
    panel.className = open ? "panel open" : "panel";
    render(open);
    if (open && frame) frame.focus();
  }

  button.addEventListener("click", function () {
    setOpen(panel.className.indexOf("open") === -1);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && panel.className.indexOf("open") !== -1) {
      setOpen(false);
      button.focus();
    }
  });

  root.appendChild(style);
  root.appendChild(panel);
  root.appendChild(button);
  render(false);

  function mount() {
    document.body.appendChild(host);
    if (script.getAttribute("data-open") === "true") setOpen(true);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);

  window.MesserWidget = { open: function () { setOpen(true); }, close: function () { setOpen(false); } };
})();
