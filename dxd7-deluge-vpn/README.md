# DelugeVPN for Umbrel

[Deluge](https://deluge-torrent.org/) running entirely inside a VPN tunnel, with a kill switch, for [umbrelOS](https://umbrel.com). Packaged from [binhex/arch-delugevpn](https://github.com/binhex/arch-delugevpn) and preconfigured for Private Internet Access (WireGuard).

> Unofficial community package. Not affiliated with binhex, Umbrel, or any VPN provider.

## Features

- First-run setup page: enter your VPN details once, no file editing
- Home-screen widgets: torrent counts and your active downloads at a glance
- All traffic goes through your VPN and is blocked if the tunnel drops
- PIA with WireGuard out of the box, including a choice of server location
- Other providers supported through binhex
- No extra ports opened on your network by default

## Install

1. In umbrelOS go to **App Store → ⋯ → Community App Stores** and add:
   ```
   https://github.com/dxD7/dxD7-Umbrel-store
   ```
2. Install **DelugeVPN** and open it.
3. Fill in the setup page: provider, protocol, username and password. Optionally choose a server location.
4. Press **Save and start Deluge**. Deluge opens automatically when ready, which can take a minute or two.
5. Log in to Deluge with the default password `deluge` and **change it right away** under **Preferences**.

## Connecting Sonarr, Radarr and Prowlarr

In Sonarr and Radarr go to **Settings → Download Clients → Add → Deluge** and enter:

| Field | Value |
|---|---|
| Host | `dxd7-deluge-vpn_deluge-vpn_1` |
| Port | `8112` |
| Password | your Deluge web password |

**Remote path mapping.** Inside this app, Deluge sees your downloads folder as `/data`. Sonarr and Radarr usually mount the same folder under a different path, so after a download finishes they can't find it. Fix that under **Settings → Download Clients → Remote Path Mappings**:

| Host | Remote Path | Local Path |
|---|---|---|
| `dxd7-deluge-vpn_deluge-vpn_1` | `/data/` | the path Radarr/Sonarr use for that same folder, for example `/downloads/` |

To find the local path, look at the `volumes:` section of the app's `docker-compose.yml` (for example `Apps/radarr/docker-compose.yml`). The Host must match the container name above, so update the mapping if you ever reinstall under a different app ID.

Radarr and Sonarr note that mappings are rarely needed when paths already match, and that is the better setup. Here the paths differ because binhex's image keeps downloads at `/data`, so a mapping is the practical fix. Hardlinks still work as long as the download folder and your library are on the same filesystem and visible to Radarr/Sonarr.

## Home-screen widgets

Right-click (or long-press) the Umbrel home screen, choose **Edit widgets**, and add the DelugeVPN widgets:

| Widget | Shows |
|---|---|
| Torrent counts | Downloading, Seeding, Paused and Queued |
| Active torrents | Up to three torrents with progress, name, and down/up speed |

A small helper container (`widget-server`) provides the data. It logs in to Deluge's daemon with Deluge's own credentials, so no extra password is stored.

The widgets show torrent names on your Umbrel home screen. To hide them, set `WIDGET_SHOW_NAMES=no` on the `widget-server` service in `Apps/dxd7-deluge-vpn/docker-compose.yml` and restart the app. App updates reset that file, so repeat the edit after updating.

## Choosing a server (PIA with WireGuard)

The setup page lists PIA locations that support port forwarding, loaded live from PIA with a short built-in list as a fallback. If you don't pick one, PIA connects to Amsterdam (binhex's default). You can also choose **Other** and type any PIA hostname, for example `ca-montreal.privacy.network`.

## Settings

Everything lives in `Apps/dxd7-deluge-vpn/data/vpn.env`.

| Setting | Default | Description |
|---|---|---|
| `VPN_PROV` | `pia` | `pia`, `airvpn`, `protonvpn` or `custom` |
| `VPN_CLIENT` | `wireguard` | `wireguard` or `openvpn` |
| `VPN_USER` / `VPN_PASS` | `CHANGE_ME` | VPN account login |
| `VPN_REMOTE_SERVER` | (not set) | PIA + WireGuard only: server hostname |
| `STRICT_PORT_FORWARD` | `yes` | PIA/ProtonVPN only: require a forwarded port |
| `LAN_NETWORK` | `192.168.1.0/24` | Your home subnet; only needed for extra published ports |
| `NAME_SERVERS` | binhex defaults | DNS servers, comma separated |
| `ENABLE_PRIVOXY` | `no` | HTTP proxy through the VPN (also needs port 8118 published) |

`vpn.env` also lists some optional advanced settings (userspace WireGuard, extra firewall ports, SOCKS proxy, debug logging). Any other [binhex variable](https://github.com/binhex/arch-delugevpn) can be added to the file too.

## Changing settings later

Edit `vpn.env` in the Umbrel Files app and restart the app.

| I want to... | Do this |
|---|---|
| Fix a wrong username or password | Edit `VPN_USER` / `VPN_PASS`, restart |
| Run the setup page again | Delete `vpn.env` (or set `VPN_USER` to `CHANGE_ME`), restart, open the app |
| Change PIA server (WireGuard) | Add or edit `VPN_REMOTE_SERVER="ca-montreal.privacy.network"`, restart |
| Go back to the default server | Set `VPN_REMOTE_SERVER="nl-amsterdam.privacy.network"`, restart |

Removing the `VPN_REMOTE_SERVER` line does not switch you back to Amsterdam. Once PIA's config has been generated, the app keeps the server it last used.

## Supported providers

| Provider | Status |
|---|---|
| PIA (WireGuard) | Tested |
| PIA (OpenVPN) | Untested |
| ProtonVPN | Untested |
| AirVPN | Untested |
| Custom (Mullvad, etc.) | Untested |

Untested means it follows binhex's documented behavior but hasn't been verified on Umbrel.

<details>
<summary><b>Using a provider other than PIA</b></summary>

Pick the provider and protocol in the setup page (or set `VPN_PROV` and `VPN_CLIENT`). Some providers, and `custom`, also need a config file instead of, or as well as, a username and password:

- OpenVPN: put your `.ovpn` file(s) in `Apps/dxd7-deluge-vpn/data/openvpn/`
- WireGuard: put `wg0.conf` in `Apps/dxd7-deluge-vpn/data/wireguard/`

If those folders don't exist yet, start and stop the app once to create them. The server location field only applies to PIA with WireGuard. For other setups the server is chosen by your config file. See [binhex's documentation](https://github.com/binhex/arch-delugevpn) for each provider's exact requirements.

</details>

## Security

<details>
<summary><b>What this package does, and what to know</b></summary>

- **Widget helper:** a second container (the same binhex image) mounts the app's data folder read-only and only reads Deluge's `auth` file to connect to the daemon. It publishes no ports; Umbrel reaches it over its internal network.
- **Kill switch:** `VPN_ENABLED` is fixed to `yes` and can't be turned off from `vpn.env`. binhex's firewall rules block traffic if the tunnel drops.
- **Deluge's password is the only login:** anyone on your network who can reach the app can see the page, so change the default `deluge` password right after installing. To also require your Umbrel login, remove the `PROXY_AUTH_ADD: "false"` line in `docker-compose.yml`.
- **Setup page exposure:** until you fill in the setup page, anyone on your network who opens the app first could enter their own VPN login. Do the setup right after installing.
- **No extra ports opened:** the web UI is reachable through Umbrel as usual, but Privoxy (8118), the Deluge daemon (58846) and the SOCKS proxy (9118) are not opened on your network. Other Umbrel apps can still reach Deluge over Umbrel's internal Docker network. To open any of them, uncomment the `ports` section in `docker-compose.yml`.
- **Privileged container:** binhex documents that WireGuard needs privileged mode plus a sysctl, so the container runs privileged. If you only use OpenVPN you can try `cap_add: NET_ADMIN` instead (see `docker-compose.yml`; untested).
- **Plain-text credentials:** your VPN login is stored in `vpn.env` on your Umbrel, readable only by the Umbrel user. Use a password you don't reuse elsewhere.
- **Passwords in logs:** binhex prints your VPN username and password in its startup log. Remove those lines before sharing a log with anyone.
- **Verify the tunnel:** add the [ipleak.net](https://ipleak.net) test torrent to Deluge and compare the torrent IP it shows with your home IP.

</details>

## Updating

The app follows binhex's `2.2` release line. To pick up a newer build of that line, run `sudo docker pull binhex/arch-delugevpn:2.2` on your Umbrel and restart the app. New package versions appear in the Umbrel App Store as usual. New settings added in later versions are listed in the [changelog](CHANGELOG.md) and won't appear in your existing `vpn.env` automatically.

## Troubleshooting

| Problem | What to check |
|---|---|
| Umbrel shows an error page after saving the setup form | Normal while the VPN connects and Deluge starts (a minute or two). Wait and refresh |
| Sonarr/Radarr import fails with "path not found" or similar | Add the remote path mapping described in [Connecting Sonarr, Radarr and Prowlarr](#connecting-sonarr-radarr-and-prowlarr) |
| App starts but never connects | `VPN_USER` and `VPN_PASS` aren't still `CHANGE_ME`; provider and protocol are correct |
| Widgets show dashes or "waiting for Deluge" | Wait until Deluge has fully started, then remove the widget and add it again. If it still says "waiting for Deluge", tick **Allow Remote Connections** in Deluge under **Preferences → Daemon**, restart the app, and check the helper's log: `sudo docker logs dxd7-deluge-vpn_widget-server_1` |
| Server choice ignored | Look for `[dxd7] provider=… server=…` in the app log. The server field only works for PIA with WireGuard |
| Login fails with a valid password | Try a simple password to rule out special characters |
| Other apps can't write to downloads | Files are created with permissions `664`/`775`; check the other app runs as user 1000 |
| Need more detail | The binhex log is `Apps/dxd7-deluge-vpn/data/supervisord.log` (remove the username and password lines before sharing) |

Issues and provider test reports are welcome on the [issue tracker](https://github.com/dxD7/dxD7-Umbrel-store/issues).

## Credits

All the heavy lifting is [binhex's](https://github.com/binhex/arch-delugevpn) work. This repo only packages it for Umbrel.
