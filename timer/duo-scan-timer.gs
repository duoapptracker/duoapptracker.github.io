/**
 * Duo scan timer (Google Apps Script, project "Duo scan timer" in the owner's Google account).
 *
 * Why: GitHub's own scheduled runs on this repository are unreliable (on 19 Nov 2026 only 2 of 18
 * hourly runs fired), so this script asks GitHub to start the "Daily refresh" workflow.
 *
 * Setup (done 19 Nov 2026):
 *  1. GitHub fine-grained token "duo-timer": resource owner duoapptracker, only this repository,
 *     permission Actions = Read and write (Metadata read-only is added automatically), ~1 year expiry.
 *  2. script.google.com > Project Settings > Script properties: GH_TOKEN = the token.
 *     The token is NEVER stored in this file or anywhere in the repository.
 *  3. Triggers: startScan, Time-driven, Hour timer, every 6 hours.
 *
 * The workflow is started with reason=timer, so it scans only if the list is at least 5 hours old
 * (see the gate step in .github/workflows/refresh.yml). Log code 204 = started.
 * When the token expires (about Nov 2027), make a new one the same way and replace GH_TOKEN.
 */
function startScan() {
  var token = PropertiesService.getScriptProperties().getProperty('GH_TOKEN');
  var res = UrlFetchApp.fetch(
    'https://api.github.com/repos/duoapptracker/duoapptracker.github.io/actions/workflows/refresh.yml/dispatches',
    {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: 'main', inputs: { reason: 'timer' } }),
      muteHttpExceptions: true
    });
  Logger.log(res.getResponseCode()); // 204 = started
}
