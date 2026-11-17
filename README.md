# iPhone Duo App Tracker

Live site: https://duoapptracker.github.io/

A small independent website that lists apps on the App Store in India whose update notes say they support iPhone Duo, with the date each one added support.

- `index.html` — the page
- `data.json` — the app list, refreshed once a day
- `duo_cloud.py` — the scan: reads Apple's public App Store charts and store pages
- `.github/workflows/refresh.yml` — runs the scan every morning and saves the new list

Not affiliated with, endorsed by or sponsored by Apple Inc. iPhone and App Store are trademarks of Apple Inc. App names and icons belong to their owners. The list is built automatically and can miss apps or include one by mistake.
