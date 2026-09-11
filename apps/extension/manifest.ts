/**
 * The extension's manifest, built from the same environment the workbench reads.
 *
 * It is generated rather than committed because two of its fields are the
 * addresses of 立言阁 itself, and those differ between a local run, staging and
 * production. A committed manifest would either carry a placeholder into the
 * Web Store or be edited by hand at release, and both are ways to ship a build
 * pointed at the wrong server.
 */

export type ManifestEnvironment = {
  apiBaseUrl: string;
  supabaseUrl: string;
  /** 工作台's address, which is also the 插件's homepage. */
  webBaseUrl: string;
  version: string;
};

/**
 * The oldest Chrome this build actually works in.
 *
 * Not a guess and not a floor picked for comfort: the workbench's stylesheet —
 * which the panel imports whole — uses `color-mix()` unguarded for focus rings
 * and surfaces, and that is Chrome 111. `build.target` in `vite.config.ts` is
 * pinned to the same number so the JavaScript cannot quietly need more than
 * the CSS does.
 *
 * Declaring it is what stops an older Chrome installing this and rendering a
 * panel with no focus rings and missing backgrounds. Chrome will not offer the
 * extension at all instead, which is the honest outcome.
 */
const MINIMUM_CHROME_VERSION = "111";

/** The origin of a URL, as a match pattern covering every path under it. */
function originPattern(value: string): string {
  const { protocol, host } = new URL(value);
  return `${protocol}//${host}/*`;
}

export function buildManifest(environment: ManifestEnvironment) {
  return {
    manifest_version: 3,
    name: "LiYan Studio Extension",
    version: environment.version,
    description:
      "A LiYan Studio product. Create a LiYan task from the page you are reading.",
    minimum_chrome_version: MINIMUM_CHROME_VERSION,
    // 工作台 itself. The Web Store shows this as the item's website, and it is
    // where a user who wants to know what 立言阁 is has to be able to get to —
    // including the 隐私政策 the listing has to point at.
    homepage_url: new URL("/", environment.webBaseUrl).toString(),
    action: {
      default_title: "LiYan Studio",
      default_popup: "popup.html",
      default_icon: {
        16: "icons/icon-16.png",
        32: "icons/icon-32.png",
        48: "icons/icon-48.png",
        128: "icons/icon-128.png",
      },
    },
    icons: {
      16: "icons/icon-16.png",
      32: "icons/icon-32.png",
      48: "icons/icon-48.png",
      128: "icons/icon-128.png",
    },
    // `activeTab` is the address of the tab the user clicked from, and nothing
    // else: no content script, and no standing access to any site they visit.
    // `storage` holds the session and the 任务创建会话 id between openings.
    permissions: ["activeTab", "storage"],
    // 立言阁's own two servers. The API keeps a CORS allowlist that cannot know
    // an unpacked extension's id, and an id only becomes fixed at publication;
    // asking for these hosts is what lets one build work in every environment
    // without the server being told who is calling.
    host_permissions: [originPattern(environment.apiBaseUrl), originPattern(environment.supabaseUrl)],
  };
}
