# OCI Health Check

A small website to walk through health checks for Oracle Cloud Infrastructure services, styled after the OCI Console. Each health check is a JSON checklist in the `healthcheck/` folder; the site opens with a landing page where you pick the health check to run through. The tool ships with health checks for various OCI services, and new ones are added simply by dropping another checklist file into that folder.

## Hosted version

You do not need to install anything to use the health checks: a public instance is available at **[https://healthcheck.oci-workshop.com](https://healthcheck.oci-workshop.com)**.

Everything you enter while working through a health check - statuses, comments, the details of the environment you are reviewing - stays in your own browser (localStorage) and is never transmitted to the server. Nothing about your tenancy or customer is stored on the server side. The only data sent to the server is the optional feedback you choose to submit about a checklist item, which maintainers use to improve the checklists. To continue on another machine or share results with a colleague, use **Export results** / **Import results** from the menu.

## Usage

Run the bundled server (plain Python, no dependencies). It serves the site, lists the available health checks and persists checklist edits made in editor mode:

```powershell
python server.py 8080
# then browse to http://localhost:8080
```

`server.py` is required: the landing page asks the server which health checks exist (`api/healthchecks`), so a plain static file server is not sufficient.

To reach the site from other machines, allow inbound TCP 8080 through Windows Firewall once (elevated prompt):

```powershell
netsh advfirewall firewall add rule name="OCI Health Check (HTTP 8080)" dir=in action=allow protocol=TCP localport=8080
```

Other machines can then browse to `http://<this-machine's-IP>:8080`. Note that statuses and comments are stored per browser (localStorage), so every visitor has their own working copy - use Export/Import from the hamburger menu to hand results over.

## Adding a health check

Drop a checklist definition into the `healthcheck/` folder as `<name>.json` and reload the landing page; no restart is needed. The file name (without `.json`) becomes the health check id used in the URL, e.g. `healthcheck/My-Service.json` is opened via `#/My-Service`. Use only letters, digits, `.`, `_` and `-` in the name.

The file has the same structure as the bundled checklists in `healthcheck/`:

- `title` and `description` (HTML allowed) - shown on the landing page card and on the health check's overview page.
- `categories` - a list of `{ "id", "route", "title", "short", "description", "items" }`, where each item is `{ "id", "label", "description"?, "commands"?, "links"?, "children"? }`. Item ids must be unique within the file; they key the stored statuses, comments and feedback.

Files that are not valid checklist JSON are skipped (with a message on the server console).

See [template.md](template.md) for a full description of the file format, a minimal template to copy, and guidance on what a health check should cover.

## Production deployment (Ubuntu 24.04)

The `deploy/` directory contains an installer that sets the tool up as a proper service with HTTPS:

- runs `server.py` as a hardened systemd service (`oci-healthcheck`) under a dedicated system user, listening on localhost only
- installs nginx as a reverse proxy that does the SSL offloading
- obtains a Let's Encrypt certificate for your domain via certbot (auto-renewal included) and redirects HTTP to HTTPS
- opens ports 443 and 80 in ufw (enabling ufw with SSH allowed if it was inactive)

On the Ubuntu server, from a checkout of this repository:

```bash
cd deploy
cp install.conf.example install.conf
nano install.conf        # set DOMAIN and LETSENCRYPT_EMAIL
sudo bash install.sh
```

The domain must already have a public DNS record pointing at the server, otherwise the Let's Encrypt challenge fails (set `SKIP_CERTBOT="yes"` in `install.conf` for an HTTP-only dry run). The app is installed to `/opt/oci-healthcheck`; live data lives in `/opt/oci-healthcheck/data` (feedback) and `/opt/oci-healthcheck/healthcheck` (the checklists, including edits made through the site) and is preserved when the installer is re-run to deploy updates. Health checks that are new in the repository are added on deploy; existing ones are never overwritten.

## Features

- A landing page listing all health checks as cards (title, description, number of categories/items and the progress stored in this browser). Pick one to open it.
- Per health check an overview page with one card per category, and one page per category reachable via the navigation bar under the header. **‹ All health checks** in that bar returns to the landing page.
- Each checklist item can be set to **Checked off**, **In progress** or **Needs attention** (or left as **Not checked**) and has a collapsible comments field for findings.
- Progress is saved automatically to the browser's localStorage, separately for each health check.
- The hamburger menu in the top bar provides **Export all results (JSON)**, **Export action items (JSON)**, **Import results** and **Reset all** for the health check that is open. Exports record which health check they belong to; importing into a different one asks for confirmation.
- The **Action items** page has **Export to JSON** (the same file as *Export action items (JSON)* in the menu) and **Export to Word** buttons. The Word export downloads a formatted `.docx` report: a summary table per category, followed by one table per category listing each item that is *In progress* or *Needs attention* with its outline path, description and the comments recorded for it. The document is generated entirely in the browser, so nothing is sent to the server.
- Every item has a feedback button (speech bubble): any user can leave feedback about the item's topic in a popup. Feedback is stored on the server (`data/feedback.json`, per health check) and is not visible to regular users; in editor mode the button shows a count badge on items that received feedback and clicking it lists all entries with timestamps, where each entry can be deleted.

## Editor mode

The hamburger menu has an **Editor** section. Choosing **Enable editor** asks for a password; once enabled you can:

- Add, edit and remove checklist items (including sub-items) on every category page. Outline numbering (a / i / 1) is recalculated automatically.
- Manage an item's reference links in the same inline editor: edit the display text and URL of existing links, remove them, or use **+ Add link** to attach new ones. URLs typed directly in an item's text are also rendered as clickable links automatically.
- Reorder items by dragging the dotted grip at the left edge of an item up or down; items can be reordered among their siblings (within the same parent).
- Add categories from the health check's overview page, and rename or delete a category from its page header. The overview page's title and description (what the landing page card shows) can be edited there as well.
- **Download checklist (JSON)** - downloads the open health check's checklist as a backup copy.
- **Import checklist (JSON)** - replaces the open health check's entire checklist with a previously downloaded file (after confirmation) and saves it to the server for everyone.

Checklist edits are saved to the server (written to `healthcheck/<id>.json`), so they are shared with everyone using the tool - other visitors get the updated checklist when they load or refresh the page. The server verifies the editor password on every save. Statuses and comments remain per browser; use Export/Import to hand results over.

The default password is `oracle`. To change it, compute the SHA-256 hex digest of your new password (e.g. `node -e "console.log(require('crypto').createHash('sha256').update('newpassword').digest('hex'))"`) and set `editorPasswordHash` in `config.json` (see `config.json.example`).

## Structure

- `config.json` - editor password hash (copy from `config.json.example` if missing)
- `index.html` - app shell (top bar, hamburger menu, category navigation, content container, password modal)
- `css/styles.css` - OCI Console inspired styling
- `healthcheck/*.json` - one checklist definition per health check (title, description, categories and items); the bundled files cover various OCI services
- `template.md` - how to write a health check: file format, minimal template and content guidance
- `data/feedback.json` - user feedback, per health check (created by the server, never served)
- `js/app.js` - landing page, data loading, hash router (`#/<healthcheck>/<category>`), rendering, persistence, export/import, editor mode
- `server.py` - serves the site, lists the health checks (`GET /api/healthchecks`), saves checklist edits (`POST /api/checklist/<id>`) and stores feedback (`/api/feedback/<id>`)
- `deploy/` - Ubuntu 24.04 installer (`install.sh` + `install.conf.example`): systemd service, nginx SSL offloading, Let's Encrypt, firewall

No build step or dependencies required (Python 3 for the server).
