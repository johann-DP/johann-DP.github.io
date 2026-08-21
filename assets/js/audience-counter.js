(() => {
  "use strict";

  const ENDPOINT = "https://datapredict-audience-counter.johann-grisel.workers.dev/hit";
  const OPT_OUT_COOKIE = "datapredict_audience_optout";
  const OPT_OUT_MAX_AGE = 31_536_000;
  const SESSION_VISIT_KEY = "datapredict_audience_session_started";
  const ENGAGED_THRESHOLD_MS = 30_000;
  const ALLOWED_PAGES = new Set([
    "/",
    "/index.html",
    "/offres.html",
    "/methode.html",
    "/cas-clients.html",
    "/demonstrations.html",
    "/demonstrations/ormevia-batiment.html",
    "/contact.html",
  ]);
  const SEARCH_DOMAINS = [
    "bing.com",
    "duckduckgo.com",
    "ecosia.org",
    "qwant.com",
    "startpage.com",
    "search.brave.com",
    "baidu.com",
    "perplexity.ai",
  ];
  const OTHER_SOCIAL_DOMAINS = [
    "facebook.com",
    "fb.com",
    "instagram.com",
    "threads.net",
    "x.com",
    "twitter.com",
    "t.co",
    "bsky.app",
    "mastodon.social",
    "youtube.com",
    "tiktok.com",
  ];

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
  if (choice === "off") {
    setOptOut(true);
  }
  if (choice === "off" || choice === "on") {
    const cleanUrl = new URL(location.href);
    cleanUrl.searchParams.delete("audience");
    history.replaceState(null, "", `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`);
  }

  const privacyDisabled = () => cookieValue(OPT_OUT_COOKIE) === "1"
    || navigator.globalPrivacyControl === true
    || navigator.doNotTrack === "1"
    || window.doNotTrack === "1";
  const optedOut = cookieValue(OPT_OUT_COOKIE) === "1";
  const disabled = privacyDisabled();
  const configured = ENDPOINT.startsWith("https://");

  document.querySelectorAll("[data-audience-disable]").forEach((link) => {
    link.hidden = disabled;
  });
  document.querySelectorAll("[data-audience-enable]").forEach((button) => {
    button.hidden = !optedOut;
    button.addEventListener("click", () => {
      setOptOut(false);
      location.reload();
    });
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

  const matchesDomain = (hostname, domain) => hostname === domain
    || hostname.endsWith(`.${domain}`);

  const classifySource = () => {
    if (!document.referrer) {
      return "direct";
    }

    let referrerHostname;
    try {
      referrerHostname = new URL(document.referrer).hostname.toLowerCase();
    } catch {
      return "direct";
    }

    const currentHostname = location.hostname.toLowerCase();
    if (
      referrerHostname === currentHostname
      || (
        matchesDomain(referrerHostname, "datapredict.org")
        && matchesDomain(currentHostname, "datapredict.org")
      )
    ) {
      return "internal";
    }

    if (
      matchesDomain(referrerHostname, "linkedin.com")
      || matchesDomain(referrerHostname, "lnkd.in")
    ) {
      return "linkedin";
    }

    if (
      /(^|\.)google\.[a-z.]+$/.test(referrerHostname)
      || /(^|\.)search\.yahoo\.[a-z.]+$/.test(referrerHostname)
      || /(^|\.)yandex\.[a-z.]+$/.test(referrerHostname)
      || SEARCH_DOMAINS.some((domain) => matchesDomain(referrerHostname, domain))
    ) {
      return "search";
    }

    if (
      OTHER_SOCIAL_DOMAINS.some((domain) => matchesDomain(referrerHostname, domain))
    ) {
      return "other-social";
    }

    return "other-site";
  };

  const classifyDevice = () => {
    const userAgent = navigator.userAgent || "";
    const isIPadOS = /Macintosh/i.test(userAgent) && navigator.maxTouchPoints > 1;
    const isTablet = isIPadOS
      || /iPad|Tablet|PlayBook|Silk/i.test(userAgent)
      || (/Android/i.test(userAgent) && !/Mobi/i.test(userAgent));

    if (isTablet) {
      return "tablet";
    }
    if (/Mobi|Android|iPhone|iPod|Windows Phone/i.test(userAgent)) {
      return "mobile";
    }
    return "desktop";
  };

  const takeSessionVisit = () => {
    try {
      if (sessionStorage.getItem(SESSION_VISIT_KEY) === "1") {
        return false;
      }
      sessionStorage.setItem(SESSION_VISIT_KEY, "1");
      return true;
    } catch {
      return false;
    }
  };

  const normalizedPage = page === "/index.html" ? "/" : page;
  const source = classifySource();
  const device = classifyDevice();

  const send = (event, visit = false) => {
    if (privacyDisabled()) {
      return;
    }

    const body = JSON.stringify({
      page: normalizedPage,
      event,
      visit,
      source,
      device,
    });
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

  const startEngagementTracking = () => {
    let visibleMilliseconds = 0;
    let visibleSince = null;
    let timer = null;
    let sent = false;

    const clearTimer = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    };

    const recordVisibleTime = () => {
      if (visibleSince !== null) {
        visibleMilliseconds += performance.now() - visibleSince;
        visibleSince = null;
      }
    };

    const complete = () => {
      if (sent) {
        return;
      }
      sent = true;
      clearTimer();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      send("engaged_30s");
    };

    const schedule = () => {
      clearTimer();
      if (sent || document.visibilityState !== "visible") {
        return;
      }

      if (visibleSince === null) {
        visibleSince = performance.now();
      }
      const remaining = ENGAGED_THRESHOLD_MS - visibleMilliseconds;
      if (remaining <= 0) {
        complete();
        return;
      }

      timer = setTimeout(() => {
        recordVisibleTime();
        if (visibleMilliseconds >= ENGAGED_THRESHOLD_MS) {
          complete();
        } else {
          schedule();
        }
      }, remaining);
    };

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        schedule();
        return;
      }

      recordVisibleTime();
      clearTimer();
      if (visibleMilliseconds >= ENGAGED_THRESHOLD_MS) {
        complete();
      }
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    schedule();
  };

  const startScrollTracking = () => {
    let sent = false;

    const check = () => {
      if (sent) {
        return;
      }

      const root = document.documentElement;
      const body = document.body;
      const documentHeight = Math.max(
        root.scrollHeight,
        root.offsetHeight,
        body?.scrollHeight || 0,
        body?.offsetHeight || 0,
      );
      const viewportBottom = window.scrollY + window.innerHeight;
      if (documentHeight > 0 && viewportBottom >= documentHeight * 0.75) {
        sent = true;
        window.removeEventListener("scroll", check);
        window.removeEventListener("resize", check);
        send("scroll_75");
      }
    };

    window.addEventListener("scroll", check, { passive: true });
    window.addEventListener("resize", check, { passive: true });
    requestAnimationFrame(check);
  };

  send("pageview", takeSessionVisit());
  startEngagementTracking();

  if (document.readyState === "complete") {
    startScrollTracking();
  } else {
    window.addEventListener("load", startScrollTracking, { once: true });
  }
})();
