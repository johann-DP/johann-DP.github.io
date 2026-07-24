(() => {
  "use strict";

  const ENDPOINT = "__DATAPREDICT_COUNTER_ENDPOINT__";
  const OPT_OUT_COOKIE = "datapredict_audience_optout";
  const OPT_OUT_MAX_AGE = 31_536_000;
  const ALLOWED_PAGES = new Set([
    "/",
    "/index.html",
    "/offres.html",
    "/methode.html",
    "/cas-clients.html",
    "/contact.html",
  ]);

  const cookieValue = (name) => document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`))
    ?.slice(name.length + 1);

  const setOptOut = (disabled) => {
    if (!disabled) {
      document.cookie = `${OPT_OUT_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
      return;
    }

    const secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${OPT_OUT_COOKIE}=1; Path=/; Max-Age=${OPT_OUT_MAX_AGE}; SameSite=Lax${secure}`;
  };

  const choice = new URL(location.href).searchParams.get("audience");
  if (choice === "off" || choice === "on") {
    setOptOut(choice === "off");
    const cleanUrl = new URL(location.href);
    cleanUrl.searchParams.delete("audience");
    history.replaceState(null, "", `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`);
  }

  const optedOut = cookieValue(OPT_OUT_COOKIE) === "1";
  const privacySignal = navigator.globalPrivacyControl === true
    || navigator.doNotTrack === "1"
    || window.doNotTrack === "1";
  const disabled = optedOut || privacySignal;
  const configured = ENDPOINT.startsWith("https://");

  document.querySelectorAll("[data-audience-disable]").forEach((link) => {
    link.hidden = disabled;
  });
  document.querySelectorAll("[data-audience-enable]").forEach((link) => {
    link.hidden = !optedOut;
  });
  document.querySelectorAll("[data-audience-status]").forEach((status) => {
    status.textContent = !configured
      ? "Le compteur n’est pas encore activé."
      : disabled
      ? "Le compteur est désactivé dans ce navigateur."
      : "Le compteur est actif dans ce navigateur.";
  });

  const page = location.pathname === "" ? "/" : location.pathname;
  if (
    disabled
    || !configured
    || !ALLOWED_PAGES.has(page)
  ) {
    return;
  }

  const send = () => {
    const body = JSON.stringify({ page: page === "/index.html" ? "/" : page });
    fetch(ENDPOINT, {
      method: "POST",
      body,
      cache: "no-store",
      credentials: "omit",
      keepalive: true,
      mode: "cors",
      referrerPolicy: "no-referrer",
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
    }).catch(() => {});
  };

  if (document.readyState === "complete") {
    send();
  } else {
    window.addEventListener("load", send, { once: true });
  }
})();
