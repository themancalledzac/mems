# Eval question review

Mark each question `accept`, `drop`, or `edit: <what to change>` on its Decision line. Then tell me in chat and I'll apply it.

- **Query** is what an agent would type into palace search.
- **Gold** is the file(s) a good search should return. A line with ` | ` means any one of those files counts.
- **Holdout** questions are kept out of tuning, so they test the search fairly.

Still missing, for you to write: 5 user-wing questions, and the 5 seed questions from the earlier review (`mem-01` and `mem-02` already exist).

## edens-zac (edens.zac @ 9f7302b)

### ez-02

- **Query** (identifiers): `TIMING revalidateCache constant value seconds`
- **Gold:** `app/constants/index.ts`
- **Why:** app/constants/index.ts:135-138 defines TIMING.revalidateCache = 3600 (sampled)
- **Decision:** 

### ez-03

- **Query** (identifiers): `isContentVisibleInCollection visibility content block collection-specific visible flag`
- **Gold:** `app/utils/contentLayout.ts`
- **Why:** app/utils/contentLayout.ts:255-275 defines isContentVisibleInCollection (global and per-collection image visibility); 282-303 hasRenderableContent and filterVisibleBlocks (sampled)
- **Decision:** 

### ez-04 (holdout)

- **Query** (identifiers): `BFF proxy route handler Origin allowlist body size cap write methods`
- **Gold:** `app/api/proxy/[...path]/route.ts; app/utils/originAllowlist.ts`
- **Why:** app/api/proxy/[...path]/route.ts:116-161 handle() checks write methods, origin, 16KB/25MB caps; app/utils/originAllowlist.ts:83-87 isAllowedWriteOrigin (sampled)
- **Decision:** 

### ez-05

- **Query** (identifiers): `buildMeContentBlock ME_TILE_ID synthetic Me tile placeholder coverImage`
- **Gold:** `app/utils/meContentBlock.ts`
- **Why:** app/utils/meContentBlock.ts:10-31 defines ME_TILE_ID and buildMeContentBlock, empty imageUrl when no cover (sampled)
- **Decision:** 

### ez-06

- **Query** (identifiers): `CHIP_WEIGHT ToolbarExtra FilterToolbar upper tier extras weight order`
- **Gold:** `app/components/ui/FilterToolbar/chipWeights.ts`
- **Why:** app/components/ui/FilterToolbar/chipWeights.ts:7-19 defines CHIP_WEIGHT and ToolbarExtra (sampled)
- **Decision:** 

### ez-07

- **Query** (identifiers): `filterContent ContentFilterCriteria non-image blocks dropped when filter active`
- **Gold:** `app/utils/contentFilter.ts`
- **Why:** app/utils/contentFilter.ts:33-60 ContentFilterCriteria; 153-187 filterContent returns early with no filters, drops non-images (sampled)
- **Decision:** 

### ez-08

- **Query** (prose): `which api call fetches all content tags and what cache tag does it use`
- **Gold:** `app/lib/api/content.ts`
- **Why:** app/lib/api/content.ts:35-45 getAllTags calls /content/tags with cache tag content-tags (sampled)
- **Decision:** 

### ez-09

- **Query** (prose): `how does the explore page load tags and locations and what does it show when the fetch fails`
- **Gold:** `app/explore/ExploreDirectory.tsx; app/lib/api/collections.ts`
- **Why:** app/explore/ExploreDirectory.tsx:15-36 calls getMetadata and renders the failure message; app/lib/api/collections.ts:336 defines getMetadata (sampled)
- **Decision:** 

### ez-10 (holdout)

- **Query** (prose): `what stops a hostile site from triggering cache revalidation with the admin session cookie`
- **Gold:** `app/api/revalidate/route.ts; app/utils/originAllowlist.ts`
- **Why:** app/api/revalidate/route.ts:43-50 POST checks session cookie then isAllowedWriteOrigin; app/utils/originAllowlist.ts:1-12,83-87 explains and implements the Origin rule (written)
- **Decision:** 

### ez-11

- **Query** (prose): `the Next.js middleware that redirects visitors without a session cookie away from admin pages`
- **Gold:** `proxy.ts`
- **Why:** proxy.ts:23-76 proxy() gates the admin route group on ezac_session and redirects to /login; file is named proxy.ts, not middleware (written)
- **Decision:** 

### ez-12

- **Query** (prose): `how does the download button start a download and reset itself afterward`
- **Gold:** `app/hooks/useDownloadNavigation.ts; app/components/ClientGalleryDownload/ClientGalleryDownload.tsx`
- **Why:** app/hooks/useDownloadNavigation.ts:37-60 startDownload sets window.location.href and resets on a timer; app/components/ClientGalleryDownload/ClientGalleryDownload.tsx:40-53 uses it (sampled)
- **Decision:** 

### ez-13

- **Query** (prose): `when is a viewer allowed to download a client gallery, role grant or password cookie`
- **Gold:** `app/utils/galleryAccess.ts`
- **Why:** app/utils/galleryAccess.ts:43-73 canDownloadCollection allows CLIENT role or password-protected client gallery with content (written)
- **Decision:** 

## edens-zac-backend (edens.zac.backend @ f569f40)

### ezb-03

- **Query** (identifiers): `UserPageAssembler MeResponse assembleForUser galleries collections role level`
- **Gold:** `src/main/java/edens/zac/portfolio/backend/services/UserPageAssembler.java`
- **Why:** src/main/java/edens/zac/portfolio/backend/services/UserPageAssembler.java:50-65 defines UserPageAssembler and assembleForUser, which builds the synthetic user page from member collection ids (sampled)
- **Decision:** 

### ezb-04

- **Query** (identifiers): `ReadCacheInvalidator markChanged CloudFront invalidation read surface after commit`
- **Gold:** `src/main/java/edens/zac/portfolio/backend/services/ReadCacheInvalidator.java`
- **Why:** src/main/java/edens/zac/portfolio/backend/services/ReadCacheInvalidator.java:22-48,74-76 describes after-commit invalidation and defines markChanged, which publishes ReadSurfaceChanged (sampled)
- **Decision:** 

### ezb-05 (holdout)

- **Query** (prose): `what max-age and s-maxage values do the public read endpoints send in Cache-Control`
- **Gold:** `src/main/java/edens/zac/portfolio/backend/config/ReadCachePolicy.java`
- **Why:** src/main/java/edens/zac/portfolio/backend/config/ReadCachePolicy.java:16-33 defines the policy and its defaults of 60s max-age and 300s s-maxage from app.cache.* properties (sampled)
- **Decision:** 

### ezb-06

- **Query** (identifiers): `PUBLIC_COLLECTION_MEMBERSHIP EXISTS collection_content visible LISTED gallery_password IS NULL`
- **Gold:** `src/main/java/edens/zac/portfolio/backend/dao/ContentRepository.java`
- **Why:** src/main/java/edens/zac/portfolio/backend/dao/ContentRepository.java:184 defines PUBLIC_COLLECTION_MEMBERSHIP, appended to queries at 443 and 492 (sampled)
- **Decision:** 

### ezb-07

- **Query** (identifiers): `findLocationsWithVisibleContent LISTED collection public orphan image count`
- **Gold:** `src/main/java/edens/zac/portfolio/backend/dao/LocationRepository.java`
- **Why:** src/main/java/edens/zac/portfolio/backend/dao/LocationRepository.java:335-346 defines findLocationsWithVisibleContent and documents the LISTED-only collection_count (sampled)
- **Decision:** 

### ezb-08

- **Query** (prose): `does login take the same time when the email does not exist, and what rate limit applies`
- **Gold:** `src/main/java/edens/zac/portfolio/backend/controller/auth/AuthController.java`
- **Why:** src/main/java/edens/zac/portfolio/backend/controller/auth/AuthController.java:47-85 login runs passwordEncoder.matches against DUMMY_HASH for unknown emails and checks AuthLoginLimiter (sampled, adapted from the AuthController login query)
- **Decision:** 

### ezb-09 (holdout)

- **Query** (identifiers): `SessionService resolve session token AuthPrincipal`
- **Gold:** `src/main/java/edens/zac/portfolio/backend/services/SessionService.java; src/main/java/edens/zac/portfolio/backend/config/SessionAuthenticationFilter.java`
- **Why:** src/main/java/edens/zac/portfolio/backend/services/SessionService.java:28 class with resolve(token); config/SessionAuthenticationFilter.java:33-35 reads the cookie and calls sessionService.resolve (sampled)
- **Decision:** 

### ezb-10

- **Query** (prose): `how does an admin set the password on a client gallery collection`
- **Gold:** `src/main/java/edens/zac/portfolio/backend/services/CollectionService.java; src/main/java/edens/zac/portfolio/backend/controller/admin/CollectionAdminController.java`
- **Why:** src/main/java/edens/zac/portfolio/backend/services/CollectionService.java:1661-1681 updateGalleryAccess calls saveGalleryAccess; controller/admin/CollectionAdminController.java:63 POST /{id}/gallery-access (sampled, adapted)
- **Decision:** 

### ezb-11

- **Query** (prose): `the github workflow that runs checkstyle and the tests before building the docker image`
- **Gold:** `.github/workflows/ci-cd.yml`
- **Why:** .github/workflows/ci-cd.yml:10-141 has lint (checkstyle), test, and build (mvn package then docker build) jobs (written)
- **Decision:** 

### ezb-12

- **Query** (prose): `why is port 8080 open to the whole internet on the EC2 security group`
- **Gold:** `terraform/security.tf`
- **Why:** terraform/security.tf:36-47 backend_api ingress rule on 8080 from 0.0.0.0/0 with the Amplify and Caddy comment (sampled, adapted from the Caddyfile/ingress query)
- **Decision:** 

## agent-orchestrator (agent-orchestrator @ 508df34)

### ao-01

- **Query** (identifiers): `load_settings ORCH_HOME ORCH_MAX_CLAUDE_JOBS ORCH_EXECUTOR env var db_path`
- **Gold:** `src/orch/settings.py`
- **Why:** src/orch/settings.py:27 db_path and :66-90 load_settings read the ORCH_* env vars, ORCH_HOME defaulting to ~/.orch (sampled)
- **Decision:** 

### ao-02

- **Query** (prose): `how does a Claude job get blocked from reading .env or key files, never_read enforcement in the permission callback`
- **Gold:** `src/orch/adapters/claude_sdk.py`
- **Why:** src/orch/adapters/claude_sdk.py:133-145 _never_read_match and :174-215 path_rules deny any tool touching a never_read pattern (sampled)
- **Decision:** 

### ao-03

- **Query** (identifiers): `_resumable failure_kind max_turns usage limit resume session`
- **Gold:** `src/orch/engine/runs.py`
- **Why:** src/orch/engine/runs.py:498-515 _resumes_after_max_turns and _resumable decide which earlier run a job resumes (sampled)
- **Decision:** 

### ao-04

- **Query** (prose): `what happens to a step's worktree on retry, is it rebased onto main before the next build attempt`
- **Gold:** `src/orch/engine/scripts.py`
- **Why:** src/orch/engine/scripts.py:336 _worktree and :359-395 rebase an existing worktree onto the land target before a new attempt, conflicts go to _conflict (sampled)
- **Decision:** 

### ao-05 (holdout)

- **Query** (identifiers): `build_options setting_sources skills plugins max_turns ClaudeAgentOptions`
- **Gold:** `src/orch/adapters/claude_sdk.py; tests/test_adapter_claude_sdk.py`
- **Why:** src/orch/adapters/claude_sdk.py:236-262 build_options sets setting_sources=[], skills, plugins, max_turns; tests/test_adapter_claude_sdk.py is its test file (sampled)
- **Decision:** 

### ao-06 (holdout)

- **Query** (prose): `how does the engine run a local model skill job such as triaging a failed check log`
- **Gold:** `src/orch/engine/skill_stage.py; src/orch/engine/steps.py`
- **Why:** src/orch/engine/skill_stage.py:33-60 run_skill runs one local skill job in app.local_slot; src/orch/engine/steps.py:444-460 calls it for log-triage after a failed verify (sampled)
- **Decision:** 

### ao-07

- **Query** (prose): `the macOS launch agent that keeps the orch server running in the background`
- **Gold:** `src/orch/commands/service.py`
- **Why:** src/orch/commands/service.py:1 module docstring (launchd agent running orch serve) and :57-70 plist_dict build the agent plist (written)
- **Decision:** 

### ao-08

- **Query** (identifiers): `create_server FastMCP /health submit repos repo_draft repo_add repo_check tools`
- **Gold:** `src/orch/mcp_server.py`
- **Why:** src/orch/mcp_server.py:40-110 create_server builds the FastMCP server with the request and repo tools at /mcp and GET /health (sampled)
- **Decision:** 

## memory (Memory @ eda101c)

### mem-03

- **Query** (identifiers): `SUMMARY_ITEM_CHARS user wing summary constants`
- **Gold:** `src/user_wing.py`
- **Why:** src/user_wing.py:30-33 defines SUMMARY_CHAR_BUDGET, SUMMARY_ITEM_CHARS, SUMMARY_OPEN_IDEAS, SUMMARY_HALL_ITEMS; :390-430 UserWing.summary uses them to trim the text (sampled)
- **Decision:** 

### mem-04

- **Query** (prose): `script that runs when the container starts and lets docker run execute any command instead of booting the server`
- **Gold:** `entrypoint.sh`
- **Why:** entrypoint.sh:23-29 is the CLI passthrough: when args are given it does exec "$@" instead of the server boot flow; the query does not name the file (adapted from the sampled docker-container query)
- **Decision:** 

### mem-05

- **Query** (identifiers): `MEMPALACE_FS_GATE_MODE warn block off pretooluse_fs_gate`
- **Gold:** `integration/claude_code/pretooluse_fs_gate.py`
- **Why:** integration/claude_code/pretooluse_fs_gate.py:29-37 documents the warn/block/off modes and env vars; :243-244 _mode() reads MEMPALACE_FS_GATE_MODE, default warn (sampled)
- **Decision:** 

### mem-06

- **Query** (prose): `how does mems doctor check whether agents searched the palace before touching the filesystem`
- **Gold:** `mems_cli/commands/palace_ops.py; mems_cli/protocol_audit.py`
- **Why:** mems_cli/commands/palace_ops.py:94-120 registers doctor with --protocol, :294 cmd_doctor runs it; mems_cli/protocol_audit.py:137 audit() and :186 format_report() do the session audit (adapted from sampled mems doctor query)
- **Decision:** 

### mem-07 (holdout)

- **Query** (identifiers): `_attach_health_route /health/deep custom_route`
- **Gold:** `src/mcp_http_server.py`
- **Why:** src/mcp_http_server.py:432-464 _attach_health_route mounts GET /health and GET /health/deep via server.custom_route (adapted from sampled mcp_http_server health query)
- **Decision:** 
