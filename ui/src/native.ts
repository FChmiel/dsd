/** Bridges to the Tauri shell when running inside the desktop app (window.__TAURI__), no-ops in a browser. */
const T: any = (window as any).__TAURI__;

export const inApp = !!T;

export async function pickFolder(): Promise<string | null> {
  if (!T?.dialog?.open) return null;
  const dir = await T.dialog.open({ directory: true, multiple: false, title: "Choose a project folder" });
  return typeof dir === "string" ? dir : null;
}

/** In the app, links meant for a new tab open in the user's default browser instead. */
export function installLinkHandler() {
  if (!T?.opener?.openUrl) return;
  document.addEventListener("click", (e) => {
    const a = (e.target as Element)?.closest?.("a[target=_blank]") as HTMLAnchorElement | null;
    if (!a || !a.href) return;
    e.preventDefault();
    T.opener.openUrl(a.href);
  }, true);
}
