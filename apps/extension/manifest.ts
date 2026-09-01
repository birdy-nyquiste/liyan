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
  version: string;
};

/** The origin of a URL, as a match pattern covering every path under it. */
function originPattern(value: string): string {
  const { protocol, host } = new URL(value);
  return `${protocol}//${host}/*`;
}

export function buildManifest(environment: ManifestEnvironment) {
  return {
    manifest_version: 3,
    name: "立言阁浏览器插件",
    version: environment.version,
    description: "把正在读的页面收集为来源，创建一个立言任务。",
    action: {
      default_title: "立言阁",
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
