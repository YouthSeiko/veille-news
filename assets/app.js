(function () {
  "use strict";

  const sb = supabase.createClient(SUPABASE_URL, SUPABASE_KEY);
  const $ = (id) => document.getElementById(id);
  const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
  const JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];

  let user = null;
  let myProfile = null;
  let latestPayload = null;
  let currentPayload = null;
  let archiveIndex = [];
  let articlesByLink = new Map();
  let likeCounts = new Map();
  let commentCounts = new Map();
  let myLikes = new Set();
  let likesCache = [];
  let pinMap = new Map();
  let currentArticle = null;
  let langFilter = "";

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  function frDate(iso) {
    if (!iso) return "";
    const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
    return JOURS[d.getDay()] + " " + d.getDate() + " " + MOIS[d.getMonth()] + " " + d.getFullYear();
  }

  function absDate(iso) {
    if (!iso) return "";
    return new Date(iso).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" });
  }

  function relTime(iso) {
    if (!iso) return "date inconnue";
    const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return "à l'instant";
    if (s < 3600) return "il y a " + Math.floor(s / 60) + " min";
    if (s < 86400) return "il y a " + Math.floor(s / 3600) + " h";
    return "il y a " + Math.floor(s / 86400) + " j";
  }

  function toast(msg, kind) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast " + (kind || "");
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.add("hidden"), 3200);
  }

  function authErrMsg(e) {
    const m = (e && e.message) || "";
    if (/Invalid login credentials/i.test(m)) return "Identifiants incorrects.";
    if (/Email not confirmed/i.test(m)) return "Email non confirmé — vérifiez votre boîte mail.";
    if (/fetch|network|Failed to fetch/i.test(m)) return "Impossible de joindre le serveur.";
    return m || "Erreur de connexion.";
  }

  async function loadFile(file) {
    const r = await fetch("data/" + file, { cache: "no-store" });
    if (!r.ok) throw new Error(file + " : " + r.status);
    return r.json();
  }

  function getArticle(url) {
    if (articlesByLink.has(url)) return articlesByLink.get(url);
    const p = pinMap.get(url);
    if (p) return { link: url, title: p.title, source: p.source, summary: p.summary || "", date: null, cat: "", lang: "", tags: [] };
    return { link: url, title: url, source: "", summary: "", date: null, cat: "", lang: "", tags: [] };
  }

  function cardHtml(a, opts) {
    opts = opts || {};
    const cls = ["card"];
    if (opts.pinned) cls.push("pinned-card");
    else cls.push(a.cat === "cyber" ? "cyber" : "tech");
    const tags = (a.tags || []).map((t) => "<span>#" + esc(t) + "</span>").join("");
    const liked = myLikes.has(a.link) ? " liked" : "";
    const pinnedOn = pinMap.has(a.link) ? " pinned-on" : "";
    const likeN = likeCounts.get(a.link) || 0;
    const cmN = commentCounts.get(a.link) || 0;
    const time = a.date
      ? '<time title="' + esc(absDate(a.date)) + '">' + relTime(a.date) + "</time>"
      : "<time>date inconnue</time>";
    const summary = a.summary ? "<p>" + esc(a.summary) + "</p>" : "";
    const langTag = a.lang ? '<span class="lang">' + esc(String(a.lang).toUpperCase()) + "</span>" : "";
    return '<article class="' + cls.join(" ") + '" data-src="' + esc(a.source || "") +
      '" data-lang="' + esc(a.lang || "") + '" data-text="' +
      esc((a.title + " " + (a.summary || "") + " " + (a.source || "")).toLowerCase()) + '">' +
      '<div class="meta"><span class="src">' + esc(a.source || "") + "</span>" + langTag + time + "</div>" +
      "<h3><a href=\"" + esc(a.link) + "\" target=\"_blank\" rel=\"noopener noreferrer\">" + esc(a.title) + "</a></h3>" +
      summary +
      (tags ? '<div class="tags">' + tags + "</div>" : "") +
      '<div class="card-actions">' +
      '<button class="act like' + liked + '" data-like="' + esc(a.link) + '" type="button">J\'aime <span class="n">' + likeN + "</span></button>" +
      '<button class="act" data-open="' + esc(a.link) + '" type="button">Commentaires <span class="n">' + cmN + "</span></button>" +
      '<button class="act pin' + pinnedOn + '" data-pin="' + esc(a.link) + '" type="button">' +
      (pinnedOn ? "Retirer de la une" : "Mettre en avant") + "</button>" +
      "</div></article>";
  }

  function render(payload) {
    currentPayload = payload;
    articlesByLink = new Map();
    payload.articles.forEach((a) => articlesByLink.set(a.link, a));

    $("date-label").textContent = frDate(payload.date) +
      " · généré à " + new Date(payload.generated_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    const ok = payload.sources_total - (payload.sources_failed || []).length;
    $("stats").innerHTML = payload.articles.length + " articles · <span id=\"res\">" +
      payload.articles.length + "</span> affichés · " + ok + "/" + payload.sources_total + " sources en ligne";

    const alerts = [];
    if ((payload.sources_failed || []).length) {
      alerts.push('<div class="banner warn">Flux indisponibles : ' + payload.sources_failed.map(esc).join(", ") + "</div>");
    }
    if (!payload.articles.length) {
      alerts.push('<div class="banner err">Aucun article récupéré — vérification en cours lors de la prochaine exécution.</div>');
    }
    $("alerts").innerHTML = alerts.join("");

    const prevSrc = $("src").value;
    const sources = Array.from(new Set(payload.articles.map((a) => a.source))).sort();
    $("src").innerHTML = '<option value="">Toutes les sources</option>' +
      sources.map((s) => '<option value="' + esc(s) + '">' + esc(s) + "</option>").join("");
    if (sources.indexOf(prevSrc) >= 0) $("src").value = prevSrc;

    const cyber = payload.articles.filter((a) => a.cat === "cyber");
    const tech = payload.articles.filter((a) => a.cat === "tech");
    $("list-cyber").innerHTML = cyber.length
      ? cyber.map((a) => cardHtml(a)).join("")
      : '<p class="empty">Aucun article récent dans cette catégorie.</p>';
    $("list-tech").innerHTML = tech.length
      ? tech.map((a) => cardHtml(a)).join("")
      : '<p class="empty">Aucun article récent dans cette catégorie.</p>';
    applyFilter();
  }

  function renderPinned() {
    const pins = Array.from(pinMap.values());
    $("count-pinned").textContent = pins.length;
    const sec = $("sec-pinned");
    if (!pins.length) { sec.classList.add("hidden"); return; }
    sec.classList.remove("hidden");
    $("list-pinned").innerHTML = pins.map((p) => cardHtml(getArticle(p.url), { pinned: true })).join("");
  }

  function renderArchives(selectedDate) {
    if (!archiveIndex.length) return;
    $("arch-list").innerHTML = archiveIndex.map((e) => {
      const label = e.date.slice(8, 10) + "/" + e.date.slice(5, 7) + "/" + e.date.slice(0, 4);
      if (e.date === (selectedDate || (currentPayload || {}).date)) {
        return '<span class="arch current">' + label + "</span>";
      }
      return '<a class="arch" data-file="' + esc(e.file) + '" data-date="' + esc(e.date) + '" href="#">' + label + "</a>";
    }).join("");
  }

  function applyFilter() {
    const q = $("q");
    const src = $("src");
    if (!q || !src) return;
    const term = q.value.toLowerCase().trim();
    const so = src.value;
    let shown = 0;
    document.querySelectorAll(".list .card").forEach((c) => {
      const ok = (!term || (c.getAttribute("data-text") || "").indexOf(term) >= 0) &&
        (!so || c.getAttribute("data-src") === so) &&
        (!langFilter || c.getAttribute("data-lang") === langFilter);
      c.classList.toggle("hidden", !ok);
      if (ok) shown++;
    });
    [["cyber", "list-cyber"], ["tech", "list-tech"], ["pinned", "list-pinned"]].forEach(([key, listId]) => {
      const list = $(listId);
      if (!list) return;
      const base = list.querySelectorAll(".card").length;
      let n = 0;
      list.querySelectorAll(".card").forEach((c) => { if (!c.classList.contains("hidden")) n++; });
      const el = $("count-" + key);
      if (el) el.textContent = (n === base ? base : n + " / " + base);
    });
    const res = $("res");
    if (res) res.textContent = shown;
  }

  function refreshActionUI() {
    document.querySelectorAll("[data-like]").forEach((b) => {
      const url = b.getAttribute("data-like");
      b.classList.toggle("liked", myLikes.has(url));
      const n = b.querySelector(".n");
      if (n) n.textContent = likeCounts.get(url) || 0;
    });
    document.querySelectorAll("[data-pin]").forEach((b) => {
      const url = b.getAttribute("data-pin");
      const on = pinMap.has(url);
      b.classList.toggle("pinned-on", on);
      b.textContent = on ? "Retirer de la une" : "Mettre en avant";
    });
    document.querySelectorAll("[data-open]").forEach((b) => {
      const n = b.querySelector(".n");
      if (n) n.textContent = commentCounts.get(b.getAttribute("data-open")) || 0;
    });
  }

  async function loadPins() {
    const { data, error } = await sb.from("pins").select("*").order("created_at", { ascending: false });
    if (error) throw error;
    pinMap = new Map((data || []).map((p) => [p.url, p]));
  }

  async function loadSocial() {
    const [likes, pins, comments] = await Promise.all([
      sb.from("likes").select("url,user_id"),
      sb.from("pins").select("*").order("created_at", { ascending: false }),
      sb.from("comments").select("url")
    ]);
    if (likes.error) throw likes.error;
    if (pins.error) throw pins.error;
    if (comments.error) throw comments.error;
    likesCache = likes.data || [];
    pinMap = new Map((pins.data || []).map((p) => [p.url, p]));
    commentCounts = new Map();
    (comments.data || []).forEach((c) => commentCounts.set(c.url, (commentCounts.get(c.url) || 0) + 1));
    recomputeMyLikes();
  }

  function recomputeMyLikes() {
    likeCounts = new Map();
    likesCache.forEach((l) => likeCounts.set(l.url, (likeCounts.get(l.url) || 0) + 1));
    myLikes = new Set(user ? likesCache.filter((l) => l.user_id === user.id).map((l) => l.url) : []);
  }

  function refreshAll() {
    if (currentPayload) render(currentPayload);
    renderPinned();
    renderArchives();
  }

  async function loadProfile() {
    if (!user) { myProfile = null; return; }
    const { data } = await sb.from("profiles").select("display_name,is_editor").eq("id", user.id).maybeSingle();
    myProfile = data || null;
    if (data) $("user-name").textContent = data.display_name;
  }

  function handleUser(u) {
    user = u;
    const logged = !!u;
    $("btn-login-open").classList.toggle("hidden", logged);
    $("user-box").classList.toggle("hidden", !logged);
    if (logged) {
      $("user-name").textContent = (u.email || "").split("@")[0];
      loadProfile().then(() => refreshAll()).catch(() => {});
    } else {
      myProfile = null;
      $("user-name").textContent = "";
    }
    recomputeMyLikes();
    refreshAll();
    updateCommentFormState();
  }

  function openModal(id) { $(id).classList.remove("hidden"); }
  function closeModals() {
    $("modal-article").classList.add("hidden");
    $("modal-login").classList.add("hidden");
    currentArticle = null;
  }
  function openLogin() {
    $("login-err").classList.add("hidden");
    openModal("modal-login");
    setTimeout(() => $("login-email").focus(), 60);
  }

  function updateCommentFormState() {
    const form = $("comment-form");
    const hintLogin = $("comment-login-hint");
    if (user) {
      form.classList.remove("hidden");
      hintLogin.classList.add("hidden");
      $("comment-hint").textContent = "en tant que " + ((myProfile && myProfile.display_name) || (user.email || "").split("@")[0]);
    } else {
      form.classList.add("hidden");
      hintLogin.classList.remove("hidden");
    }
  }

  async function loadComments(url) {
    const { data: rows, error } = await sb.from("comments")
      .select("id,user_id,content,created_at")
      .eq("url", url)
      .order("created_at", { ascending: true });
    if (error) { $("comments-list").innerHTML = '<p class="err">Erreur de chargement des commentaires.</p>'; return; }
    commentCounts.set(url, rows.length);
    $("count-comments").textContent = rows.length;
    if (!rows.length) {
      $("comments-list").innerHTML = '<p class="hint">Aucun commentaire pour le moment.</p>';
      return;
    }
    const ids = Array.from(new Set(rows.map((r) => r.user_id)));
    let names = new Map();
    const { data: profs } = await sb.from("profiles").select("id,display_name").in("id", ids);
    (profs || []).forEach((p) => names.set(p.id, p.display_name));
    $("comments-list").innerHTML = rows.map((r) => {
      const canDel = user && (r.user_id === user.id || (myProfile && myProfile.is_editor));
      const who = names.get(r.user_id) || "Membre";
      return '<div class="comment">' +
        (canDel ? '<button class="del" data-del="' + esc(r.id) + '" type="button">supprimer</button>' : "") +
        '<span class="who">' + esc(who) + "</span>" +
        '<span class="when">' + relTime(r.created_at) + "</span>" +
        '<div class="body">' + esc(r.content) + "</div></div>";
    }).join("");
  }

  async function openArticle(url) {
    const a = getArticle(url);
    currentArticle = a;
    const tags = (a.tags || []).map((t) => "<span>#" + esc(t) + "</span>").join("");
    $("modal-article-body").innerHTML =
      '<div class="meta"><span class="src">' + esc(a.source || "") + "</span>" +
      (a.lang ? '<span class="lang">' + esc(String(a.lang).toUpperCase()) + "</span>" : "") +
      (a.date ? "<time>" + relTime(a.date) + "</time>" : "") + "</div>" +
      "<h3><a href=\"" + esc(a.link) + "\" target=\"_blank\" rel=\"noopener noreferrer\">" + esc(a.title) + "</a></h3>" +
      (a.summary ? "<p>" + esc(a.summary) + "</p>" : "") +
      (tags ? '<div class="tags">' + tags + "</div>" : "");
    openModal("modal-article");
    updateCommentFormState();
    $("comments-list").innerHTML = '<p class="hint">Chargement…</p>';
    $("count-comments").textContent = "…";
    await loadComments(url);
  }

  async function toggleLike(url) {
    if (!user) { openLogin(); return; }
    const liked = myLikes.has(url);
    if (liked) {
      const { error } = await sb.from("likes").delete().eq("url", url).eq("user_id", user.id);
      if (error) { toast(error.message, "error"); return; }
      likesCache = likesCache.filter((l) => !(l.url === url && l.user_id === user.id));
    } else {
      const { error } = await sb.from("likes").insert({ url: url, user_id: user.id });
      if (error) { toast(error.message, "error"); return; }
      likesCache.push({ url: url, user_id: user.id });
    }
    recomputeMyLikes();
    refreshActionUI();
  }

  async function togglePin(url) {
    if (!user) { openLogin(); return; }
    const on = pinMap.has(url);
    if (on) {
      const { error } = await sb.from("pins").delete().eq("url", url).eq("user_id", user.id);
      if (error) { toast(error.message, "error"); return; }
      toast("Retiré de la une");
    } else {
      const a = getArticle(url);
      const { error } = await sb.from("pins").insert({
        user_id: user.id, url: url, title: a.title,
        source: a.source || "", summary: (a.summary || "").slice(0, 300)
      });
      if (error) { toast(error.message, "error"); return; }
      toast("Ajouté à la une", "ok");
    }
    await loadPins();
    refreshAll();
  }

  async function submitComment(ev) {
    ev.preventDefault();
    if (!user || !currentArticle) return;
    const text = $("comment-text").value.trim();
    if (!text) return;
    const { error } = await sb.from("comments").insert({
      user_id: user.id, url: currentArticle.link, content: text
    });
    if (error) { toast(error.message, "error"); return; }
    $("comment-text").value = "";
    toast("Commentaire publié", "ok");
    commentCounts.set(currentArticle.link, (commentCounts.get(currentArticle.link) || 0) + 1);
    await loadComments(currentArticle.link);
    refreshActionUI();
  }

  async function deleteComment(id) {
    const { error } = await sb.from("comments").delete().eq("id", id);
    if (error) { toast(error.message, "error"); return; }
    if (currentArticle) await loadComments(currentArticle.link);
    if (currentArticle) {
      commentCounts.set(currentArticle.link, Math.max(0, (commentCounts.get(currentArticle.link) || 1) - 1));
    }
    refreshActionUI();
  }

  async function submitLogin(ev) {
    ev.preventDefault();
    const btn = $("login-submit");
    const errEl = $("login-err");
    btn.disabled = true;
    errEl.classList.add("hidden");
    const { error } = await sb.auth.signInWithPassword({
      email: $("login-email").value.trim(),
      password: $("login-password").value
    });
    btn.disabled = false;
    if (error) {
      errEl.textContent = authErrMsg(error);
      errEl.classList.remove("hidden");
      return;
    }
    $("login-password").value = "";
    closeModals();
    toast("Connexion réussie", "ok");
  }

  function wire() {
    $("q").addEventListener("input", applyFilter);
    $("src").addEventListener("change", applyFilter);
    $("seg").addEventListener("click", (ev) => {
      const b = ev.target.closest("button");
      if (!b) return;
      $("seg").querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      langFilter = b.getAttribute("data-lang") || "";
      applyFilter();
    });
    $("btn-login-open").addEventListener("click", openLogin);
    $("link-login-2").addEventListener("click", (ev) => { ev.preventDefault(); openLogin(); });
    $("btn-logout").addEventListener("click", async () => { await sb.auth.signOut(); toast("Déconnecté"); });
    $("login-form").addEventListener("submit", submitLogin);
    $("comment-form").addEventListener("submit", submitComment);
    $("btn-today").addEventListener("click", () => {
      if (!latestPayload) return;
      render(latestPayload);
      renderArchives();
      $("btn-today").classList.add("hidden");
    });

    document.addEventListener("click", (ev) => {
      const like = ev.target.closest("[data-like]");
      if (like) { toggleLike(like.getAttribute("data-like")); return; }
      const pin = ev.target.closest("[data-pin]");
      if (pin) { togglePin(pin.getAttribute("data-pin")); return; }
      const open = ev.target.closest("[data-open]");
      if (open) { openArticle(open.getAttribute("data-open")); return; }
      const del = ev.target.closest("[data-del]");
      if (del) { deleteComment(del.getAttribute("data-del")); return; }
      const arch = ev.target.closest("a.arch");
      if (arch) {
        ev.preventDefault();
        loadFile(arch.getAttribute("data-file")).then((data) => {
          render(data);
          renderArchives(data.date);
          $("btn-today").classList.remove("hidden");
          window.scrollTo({ top: 0, behavior: "smooth" });
        }).catch(() => toast("Archive indisponible", "error"));
        return;
      }
      if (ev.target.closest("[data-close]") || ev.target.classList.contains("backdrop")) closeModals();
    });

    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") closeModals();
      if (ev.key === "/" && document.activeElement !== $("q") &&
          !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
        ev.preventDefault();
        $("q").focus();
      }
    });
  }

  async function init() {
    wire();
    sb.auth.onAuthStateChange((_event, session) => {
      handleUser(session ? session.user : null);
    });
    try {
      latestPayload = await loadFile("latest.json");
      render(latestPayload);
    } catch (e) {
      $("alerts").innerHTML = '<div class="banner err">Données indisponibles : la première exécution de l\'action quotidienne est peut-être encore en attente.</div>';
      $("date-label").textContent = "Données indisponibles";
    }
    try {
      archiveIndex = await loadFile("index.json");
      renderArchives();
    } catch (e) { /* première exécution */ }
    try {
      await loadSocial();
      refreshAll();
    } catch (e) { /* Supabase injoignable */ }
    try {
      const { data: { session } } = await sb.auth.getSession();
      handleUser(session ? session.user : null);
    } catch (e) { /* ignore */ }
  }

  init();
})();
