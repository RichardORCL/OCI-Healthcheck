# Writing a health check

This document explains what the OCI Health Check tool is for, how a health check definition (`healthcheck/<name>.json`) is built, and what a good health check typically covers. Use it as the starting point when adding a health check for a new OCI service.

## Purpose of the tool

The OCI Health Check tool is a lightweight web app for walking through a structured review of a customer's use of an OCI service, for example during an architecture review, a support engagement or a periodic operational check.

- A health check is a **checklist**: a set of categories, each containing questions or checks to go through with the customer.
- The reviewer sets a **status** for every item - *Checked off*, *In progress*, *Needs attention* or *Not checked* - and records findings in a **comment**.
- The **Action items** page collects everything that is *In progress* or *Needs attention* across all categories, so the follow-ups for the customer fall out of the review automatically.
- Results stay in the reviewer's browser (with Export/Import to hand them over); nothing about the customer environment is stored on the server.
- The checklist content itself is shared: maintainers refine it in **editor mode**, and everyone gets the updated version.

The landing page lists every file in the `healthcheck/` folder as a selectable health check, so the same tool serves any number of OCI services.

## How a health check file works

Each health check is one JSON file: `healthcheck/<name>.json`.

- The **file name** (without `.json`) is the health check's id and appears in the URL: `healthcheck/OCI-storage.json` opens as `#/OCI-storage`. Use only letters, digits, `.`, `_` and `-`, and start with a letter or digit.
- The server picks the file up on the next load of the landing page; no restart or registration is needed.
- Files that are not valid JSON, or that have no `categories` array, are skipped and reported on the server console.

### Top-level structure

```json
{
  "title": "OCI <Service> Health Check",
  "description": "One or two sentences on what this health check covers and how to use it. <b>HTML is allowed.</b>",
  "categories": [ ... ]
}
```

| Field | Required | Purpose |
| --- | --- | --- |
| `title` | yes | Shown on the landing page card, the overview page and the top bar. Falls back to the file name if missing. |
| `description` | recommended | Shown under the title on the landing page card and the overview page. HTML allowed (`<b>`, `<br>`, links). |
| `categories` | yes | Ordered list of categories (below). Order is the order of the navigation bar and overview cards. |
| `exportedAt` | no | Timestamp written by the editor's *Download checklist*. Ignored on load. |

### Category

```json
{
  "id": "block-volumes",
  "route": "block-volumes",
  "title": "Block Volumes",
  "short": "Block Volumes",
  "description": "Block Volume inventory, performance settings, backup policies, replication and encryption.",
  "items": [ ... ]
}
```

| Field | Required | Purpose |
| --- | --- | --- |
| `id` | yes | Unique within the file. Conventionally the same as `route`. |
| `route` | yes | URL segment of the category page: `#/<healthcheck>/<route>`. Lowercase, hyphenated. |
| `title` | yes | Heading of the category page and its overview card. |
| `short` | recommended | Short label for the navigation bar (e.g. `Inventory` for `OCVS Inventory`). Defaults to `title`. |
| `description` | recommended | One sentence shown on the overview card and under the page heading. HTML allowed. |
| `items` | yes | Ordered list of checklist items (below). May be empty while drafting. |

### Item

```json
{
  "id": "blk-c",
  "label": "Are backup policies assigned to all business-critical volumes?",
  "description": "Optional context: why this matters, what to look for, how to interpret the result.",
  "commands": [
    "oci bv volume-backup-policy-assignment get-volume-backup-policy-asset-assignment --asset-id <volume-ocid>"
  ],
  "links": [
    { "text": "Policy-Based Backups documentation", "url": "https://docs.oracle.com/en-us/iaas/Content/Block/Tasks/schedulingvolumebackups.htm" }
  ],
  "children": [
    { "id": "blk-c-i",  "label": "Is a policy-based schedule (Bronze/Silver/Gold or custom) in place, or are backups taken manually?" },
    { "id": "blk-c-ii", "label": "Are backups copied to a second region for disaster recovery?" }
  ]
}
```

| Field | Required | Purpose |
| --- | --- | --- |
| `id` | yes | **Unique within the file and stable over time.** Statuses, comments, exports and feedback are keyed on it - renaming an id orphans everything recorded against it. |
| `label` | yes | The question or check itself. Plain text; URLs in the text are linkified automatically. HTML is accepted if needed. |
| `description` | no | Supporting text under the label: background, what "good" looks like, where to find the setting. HTML allowed. |
| `commands` | no | List of command examples (OCI CLI, Cloud Shell, PowerShell, SSH ...). Each is rendered as a code block with a copy button. Use `\n` for multi-line scripts. |
| `links` | no | Reference links (`text` + `url`), typically OCI documentation. |
| `children` | no | Nested sub-items with the same structure. |
| `num` | no | Outline marker (`a.`, `i.`, `1.`). **Generated automatically** - leave it out; the tool renumbers on load and after every edit. |

Nesting: top-level items are numbered `a.`, `b.` ..., their children `i.`, `ii.` ..., the next level `1.`, `2.` .... Three levels is the practical maximum; deeper nesting becomes hard to read.

Every item at every level gets its own status and comment, so use children when a question really has separately answerable parts, and put context in `description` when it does not.

### Id conventions

Ids only need to be unique and stable, but a readable scheme helps when reading exports and feedback:

- Category: `<topic>` (`inventory`, `networking`, `block-volumes`)
- Item: `<cat-prefix>-<letter>` (`inv-a`, `blk-c`)
- Child: `<parent>-<roman>` or `<parent>-<n>` (`blk-c-i`, `inv-a-2`)

Items created through editor mode get generated ids like `itm-mrc7jkoi-bcrjl`; that is fine, they are just as stable.

## Minimal template

Copy this to `healthcheck/<Name>.json` and fill it in:

```json
{
  "title": "OCI <Service> Health Check",
  "description": "Walk through the health check for OCI <Service>. Choose a category below or from the top bar, set a status for each item, and record your findings in the comments.",
  "categories": [
    {
      "id": "inventory",
      "route": "inventory",
      "title": "<Service> Inventory",
      "short": "Inventory",
      "description": "What is deployed, where, which versions/shapes/tiers, and under which commercial terms.",
      "items": [
        {
          "id": "inv-a",
          "label": "Is there a complete inventory of all <resources>, including region/AD, size and lifecycle state?",
          "description": "Below example lists all <resources> from the <b>OCI Cloud Shell</b>:",
          "commands": [
            "oci search resource structured-search --query-text \"query <resourcetype> resources where lifecycleState != 'TERMINATED'\""
          ]
        }
      ]
    },
    {
      "id": "general",
      "route": "general",
      "title": "General",
      "short": "General",
      "description": "Other findings, questions or remarks for this health check.",
      "items": [
        { "id": "gen-a", "label": "General comments" }
      ]
    }
  ]
}
```

## What a health check should cover

The OCVS and OCI Storage health checks follow a similar shape. Not every category applies to every service, but this list is a good checklist for the checklist:

| Category | Typical questions |
| --- | --- |
| **Inventory** | What is deployed: resources, regions/ADs/FDs, shapes/tiers/sizes, software versions, number of instances. Is anything orphaned or unused (cost)? Provide a Cloud Shell / CLI command that produces the inventory. |
| **Licensing / commercial** | License model (BYOL vs. included), commitment terms and end dates, upgrade or renewal plans. |
| **Architecture & networking** | Is a current diagram available? Compartment layout vs. network layout (visibility). VCN/subnet/VLAN design, routing, NSGs and security lists, public exposure, DMZ separation. |
| **Data protection** | Backups: policy-based or manual, schedules, second region, restore tested? Replication and DR: targets, intervals, failover tested? Snapshots vs. real backups. Encryption at rest/in transit, customer-managed keys where required. |
| **Performance & capacity** | Do performance settings (VPUs, shapes, mount target throughput, NSX sizing) match the workload? Headroom for growth and for a fault-domain or AD failure. |
| **Security & access** | IAM: who can manage the service and its network (`use`/`manage` on which compartments)? Public access intentional and documented? Local accounts, password expiry, SSH keys, external identity integration. |
| **Monitoring & operations** | Notifications topics and subscribers, alarms on critical metrics/events, log analytics, maintenance-event visibility, integration with the customer's tooling. |
| **Integration with other OCI services** | Which OCI services does this service depend on or feed into, and is each integration configured and healthy? Typical examples: IAM (dynamic groups, policies, resource principals), Vault/KMS (customer-managed keys), Object Storage (backups, exports, logs), Networking (service gateway, private endpoints, DRG), Monitoring/Notifications/Events/Logging, Cloud Guard and Security Zones, Tagging and Cost Analysis, Resource Manager/Terraform for provisioning. Are integrations set up with least privilege, and are they documented? |
| **Troubleshooting & support** | Can the customer actually log in to every layer they are responsible for? Do they know the recovery features (e.g. replace host) and how to raise an Oracle Support request? |
| **Lifecycle** | Versions and upgrade plans, deprecations, lifecycle/retention rules that clean up automatically. |
| **General** | A single free-form item for anything that does not fit above. Keep it - reviewers use it. |

### Writing good items

- **Phrase items as questions** the reviewer asks the customer or checks in the tenancy: "Are backup policies assigned to all business-critical volumes?" rather than "Backup policies".
- **Say why it matters** in the `description`: what the default is, what the risk is, what "good" looks like. That is what makes the item useful to a reviewer who did not write it.
- **Make it verifiable.** Where possible add a `commands` entry that produces the answer (OCI CLI in Cloud Shell is the most portable; `oci search resource structured-search` plus `jq` covers most inventories). Prefer commands that need no editing to run.
- **Link the source of truth** - the OCI documentation page for the feature - in `links`, so the reviewer can check details and the customer gets a reference for the follow-up.
- **Split with `children`** only when the parts are answered separately (each child gets its own status). Otherwise fold the detail into the description.
- **Order categories from discovery to detail**: inventory first, then architecture, data protection, security, monitoring, support processes, and *General* last.
- **Keep it reviewable in a session.** The existing health checks have 5-8 categories and roughly 20-70 items in total. Very long checklists do not get finished.
- **Avoid customer- or tenancy-specific content**; the same checklist is used for every customer. Anything specific goes into the reviewer's comments.

## Workflow for a new health check

1. Draft the file from the minimal template above and save it as `healthcheck/<Name>.json`.
2. Run `python server.py` and open the landing page; the new card appears. Fix any "Skipping ..." message printed by the server (usually a JSON syntax error).
3. Refine the content in the browser with **Enable editor**: add/edit items, links and commands, drag to reorder, edit category and overview text. Every change is written back to the file.
4. Use **Download checklist (JSON)** for a copy, review the diff, and commit the file to the repository. On deployed servers a health check that is new in the repository is added on the next `install.sh -update`; existing ones are left alone because they contain edits made through the site.
5. Once the health check is in use, keep item ids stable so exported results and collected feedback remain attached to the right items.
