# DelugeVPN (test) - widget build

Temporary test app. It is a copy of DelugeVPN 2.1.1 plus two Umbrel home-screen
widgets, on its own port (8113) so it can run next to the real app.

## Try it

1. Install **DelugeVPN (test)**, open it, and fill in the setup form.
   Shortcut: copy the real app's `data/vpn.env` into this app's `data` folder
   before the first start and the form is skipped.
2. Wait for Deluge to start (a minute or two).
3. Umbrel home screen: right-click (or long-press) -> **Edit widgets** ->
   **DelugeVPN (test)** -> add the widgets.
4. Add a torrent to see the list fill in.

## If the widgets only say "waiting for Deluge"

1. In the test app's Deluge: **Preferences -> Daemon -> Allow Remote Connections**,
   tick it, save, and restart the app.
2. Still nothing? On your Umbrel run
   `sudo docker logs dxd7-deluge-vpn-test_widget-server_1 2>&1 | tail -20`
   and send the output (it contains no passwords).

## Widgets

| Widget | Type | Shows |
|---|---|---|
| torrents | four-stats | Downloading / Seeding / Paused / Queued counts |
| active | list | Up to 3 torrents: percent, name, down/up speed |

Set `WIDGET_SHOW_NAMES=no` on the `widget-server` service in
`docker-compose.yml` to hide torrent names on the home screen.

## Cleaning up

Uninstall the test app and delete the `dxd7-deluge-vpn-test` folder from the repo.
