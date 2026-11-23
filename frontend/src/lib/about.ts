/**
 * Copyright and licensing text shown in the app (side pane footer and
 * Settings > About). See LICENSING.md in the repository for the full picture.
 */

/** The copyright line. */
export const COPYRIGHT = "\u00a9 2026 Mohannad Ali";

/**
 * The distributed app includes PyMuPDF (GNU AGPL-3.0), so the app as a whole is
 * conveyed under the AGPL-3.0. The owner's own source code is also available
 * under the MIT License. Never describe the app as MIT-only.
 */
export const APP_LICENSE = "GNU AGPL-3.0";

/** Where the complete corresponding source code is available. */
export const SOURCE_URL = "https://github.com/Ali7488/pdf-manager";

/**
 * The source code of exactly this version: the release tag (vX.Y.Z) the build was
 * made from (AGPL-3.0 sections 6 and 13).
 *
 * @param version - The app version, as `getAppInfo` reports it.
 */
export function sourceUrlFor(version: string): string {
  return `${SOURCE_URL}/tree/v${version}`;
}
