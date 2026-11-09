import { useEffect, useState } from "react";

/** Minimal pushState router. Routes look like /p/<projectId>/<view>/<rest...>?query */
export interface Route {
  pid: string | null;
  view: string;
  rest: string[];
  query: URLSearchParams;
}

export function parseRoute(): Route {
  const parts = window.location.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  const query = new URLSearchParams(window.location.search);
  if (parts[0] !== "p" || !parts[1]) return { pid: null, view: "home", rest: [], query };
  return { pid: parts[1], view: parts[2] || "overview", rest: parts.slice(3), query };
}

export function navigate(to: string, replace = false) {
  if (to === window.location.pathname + window.location.search) return;
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new Event("dsd:navigate"));
}

export function useRoute(): Route {
  const [route, setRoute] = useState(parseRoute);
  useEffect(() => {
    const update = () => setRoute(parseRoute());
    window.addEventListener("popstate", update);
    window.addEventListener("dsd:navigate", update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener("dsd:navigate", update);
    };
  }, []);
  return route;
}

export function href(pid: string, view: string, ...rest: (string | undefined)[]): string {
  const tail = rest.filter((x): x is string => !!x).map((x) => x.split("/").map(encodeURIComponent).join("/"));
  return ["", "p", pid, view, ...tail].join("/");
}

/** <a> that routes client-side but still supports cmd-click / middle-click. */
export function linkProps(to: string) {
  return {
    href: to,
    onClick: (e: React.MouseEvent) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      navigate(to);
    },
  };
}
