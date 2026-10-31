# Building and testing the local-client GUI on six platforms: options and scenarios

Prepared 2026-10-09 for the `aipotluck-local-client-gui` project. Covers Linux CPU, Linux + CUDA,
macOS CPU, macOS + Metal, Windows CPU and Windows + CUDA. All prices are list prices in USD, read on
the date above. Every derived dollar figure was computed by script from the cited unit prices
(`costs.json` beside this report).

## TL;DR

1. **Our existing CI infrastructure covers only one of the six legs as it stands.**
   - The aipotluck.org `ci-runners/` stack provisions ephemeral EC2 runners for GitHub Actions.[1]
   - It builds a single Ubuntu 24.04 image in two CPU-only sizes.[2]
   - So today it covers **Linux CPU** only.
   - The construct it is built on also supports Windows and GPU providers, so **Linux + CUDA and
     Windows (CPU and CUDA) are an extension of a stack we already run, not a new system**.[12]
2. **macOS is the one platform no AWS-native path covers cheaply.**
   - EC2 Macs are bare-metal Dedicated Hosts with a 24-hour minimum allocation.[14]
   - Our CDK construct has no macOS provider.[12]
   - The cheapest macOS legs are therefore GitHub's own hosted Mac runners, billed per minute.[11]
3. **"macOS + Metal" may be testable on GitHub's standard hosted Macs, but this is unproven for our
   workload.**
   - Those VMs expose an "Apple Paravirtual device" to Metal.[23]
   - llama.cpp's own CI builds and runs a Metal-enabled test with `-ngl 99` on `macos-latest`.[18]
   - The paravirtual GPU reports an older Metal feature set, so llama.cpp picks slower kernels than
     on bare metal.[25]
   - It is a functional test, not a performance test. Bare-metal Metal benchmarking needs real Apple
     hardware.[19]
4. **CUDA testing needs an NVIDIA GPU on the runner, and that is where costs diverge.**
   - GitHub's T4 GPU runners cost $0.052/min on Linux and $0.102/min on Windows, and require the
     Team plan.[11]
   - The same T4 class on EC2 (`g4dn.xlarge`) is $0.526/h on Linux and $0.71/h on Windows,
     on-demand in us-west-2.[15]
   - That makes AWS about **5.9×** cheaper than GitHub on Linux GPU and **8.6×** cheaper on Windows
     GPU.
5. **Recommended (updated 2026-10-09): scenario E, the AWS stack plus the incoming Mac mini M5.**
   - The existing AWS stack, extended, runs Linux CPU, Linux CUDA, Windows CPU and Windows CUDA.
   - A Mac mini M5 that is being bought anyway runs the two macOS legs as a self-hosted runner.
   - It is the only option here that gives **bare-metal Metal** (real performance numbers) at no
     recurring cost.
   - Cloud spend drops to about **$19/month** at one nightly run of all six legs (~20 min each).
     That compares with $93/month for scenario B (hosted Macs) and $211/month for an
     all-GitHub-hosted setup.
   - The cost moves into maintenance: one physical machine to keep patched, powered and online.
   - Scenario B's hosted Macs stay the fallback whenever the mini is offline.
6. **Two blockers exist regardless of where tests run.**
   - Upstream's newt checksums for macOS and Windows are still placeholders.[8]
   - Upstream auto-detection never selects a GPU backend on Windows: Windows CUDA is not wired into
     the installer yet.[7]
   - Until both are fixed upstream, a Windows CUDA or macOS pairing test has nothing correct to test.

## The constraints that shape every option

**C1. Each leg needs real hardware of its kind at test time, but not at build time.**
- The GUI does not compile llama.cpp. It downloads upstream's pinned prebuilt assets, one per
  platform and backend:
  - `linux-x64-cuda` uses CUDA 12.8;
  - `macos-arm64-cpu` has Metal built in;
  - there is a Windows CPU zip.[6]
- *Building* the six installers is therefore cheap and runs on any runner of the right OS. Tauri's
  own reference workflow builds macOS, Linux and Windows bundles on standard hosted runners.[37]
- *Testing* that the inference server actually uses the GPU needs that GPU present.
- So the matrix has two cost profiles, and every option should be judged on the test legs.

**C2. The GPU APIs differ by OS, and so does the hardware a cloud guest can reach.**
- **CUDA** needs an NVIDIA device inside the guest: EC2 G-family, GitHub's T4 runners, or Hugging
  Face T4 jobs.[10][15][33]
- **Metal** on a macOS VM goes through Apple's paravirtualized graphics, not the physical GPU.[26]
- GitHub's hosted Macs show up to WebGL as "ANGLE Metal Renderer: Apple Paravirtual device".[23]

**C3. Upstream readiness gates two legs.**
- Upstream's `detect_gpu_backend` returns `cpu` on Windows unconditionally ("GPU asset variants for
  Windows are not wired into the manifest yet"). The pinned manifest has no Windows CUDA asset.[7][6]
- The macOS and Windows newt binaries carry `UNVERIFIED_DOWNLOAD_AND_COMPUTE_BEFORE_USE` checksums,
  so upstream refuses to pair there.[8]
- This is also the open scope of CUR-1963, the parent ticket for exactly this work.[5]

**C4. The GUI's own end-to-end test uses a different driver on each OS.**
- `tauri-driver` (used by `tools/e2e-smoke.py`) supports Windows and Linux.
- macOS needs WebdriverIO's embedded WebDriver service instead.[43]
- The macOS legs will need a second e2e harness.

## What you already have

| Asset | Verdict | Why |
|---|---|---|
| **aipotluck.org `ci-runners/`** (CDK, CloudSnorkel cdk-github-runners v0.17.1, EC2, us-west-2)[1] | **Primary fit for Linux CPU; extensible to Linux CUDA, Windows CPU and Windows CUDA** | Ephemeral one-job-per-instance runners already exist, along with alarms and a deploy script.[1] The construct supports Windows images and GPU instance types on its EC2 provider.[12] Today it has one Ubuntu 24.04 image and two CPU sizes.[2] |
| **That AWS account's 32-vCPU spot quota**[4] | ⚠️ Constraint | Bursts already overflow to on-demand. A quota raise to 256 was closed without being granted.[4] GPU instance families have their own quotas. ⚠️ Verify G-family vCPU quota before planning spot GPU runners. |
| **GitHub org `currentai-org`** | Partial | Hosted minutes are being bought (Linux billed at $0.006/min; Sept: 119,087 min).[3] The org is still on the `free` plan.[3] GitHub's GPU runners and larger Mac runners need Team or Enterprise.[11] Standard `macos-latest` (M1, 3 vCPU) and Windows runners need no upgrade.[9] |
| **Jelastic/Virtuozzo, Vercel, Fly** | Not usable | These host aipotluck.org's web previews and services. None offers desktop-OS or GPU CI runners (from the repo's environment docs). |
| **Local hardware you own** (this Pi, the Jetson boards upstream already tests on) | Partial, last resort | Useful as ad-hoc ARM and Jetson legs. None of it is x86 Windows, an NVIDIA desktop GPU, or a Mac. |
| **Linear CUR-1963 + children** (CUR-1966 macOS CPU, CUR-1968 macOS Metal, CUR-1967 Windows CPU, CUR-1970 Windows CUDA) | Tracking home | The backlog for exactly this work already exists, assigned to you.[5] |

## Capability matrix

✅ works · ⚠️ verify · ❌ not possible · — not offered

| Option | Linux CPU | Linux CUDA | macOS CPU | macOS Metal | Win CPU | Win CUDA | Billing shape |
|---|---|---|---|---|---|---|---|
| **Existing AWS stack, extended** | ✅ today[2] | ✅ add a `g4dn` provider[12] | ❌ no macOS provider[12] | ❌ | ✅ add a Windows image[12] | ⚠️ `g4dn` + Windows + NVIDIA driver, needs a custom image[41] | Per-second EC2, spot or on-demand[15] |
| **GitHub-hosted standard** | ✅ | ❌ no GPU[9] | ✅ M1, 3 vCPU[9] | ⚠️ paravirtual Metal, functional only[23][25] | ✅ | ❌ | Per minute[11] |
| **GitHub-hosted larger + GPU** (Team plan) | ✅ | ✅ T4[10] | ✅ M2 Pro 5-core[10] | ⚠️ same paravirtual caveat | ✅ | ✅ T4[10] | Per minute, no included minutes[11] |
| **EC2 Mac Dedicated Host** | — | — | ✅ bare metal[14] | ✅ physical GPU[14] | — | — | 24 h minimum per host[14] |
| **Cirrus Runners** | ✅ | ⚠️ "Linux GPU" listed; card unverified | ✅ M4 Pro[28] | ⚠️ VM (Tart), virtualized GPU, verify | — | — | $150/month per concurrent runner, unlimited minutes[28] |
| **Namespace** | ✅ | — | ✅ M4 Pro / M5 Max[30] | ⚠️ "hardware acceleration for graphics" claimed[30] | — | — | Plan plus unit-minutes[31] |
| **RunsOn** (in our AWS account) | ✅ | ✅ any EC2 GPU[27] | — | — | ✅ incl. license in spot price[27] | ⚠️ | EC2 cost plus a yearly license from ~$350[27] |
| **Hugging Face Jobs** (as llama.cpp uses) | — | ✅ T4 runner label[20] | — | — | — | — | T4-medium $0.60/h[33] |
| **Scaleway Mac mini M4** | — | — | ✅ dedicated[29] | ✅ no hypervisor[29] | — | — | €0.22/h, 24 h minimum[29] |
| **Local hardware** (Mac mini + NVIDIA PC) | ✅ | ✅ | ✅ | ✅ bare metal | ✅ | ✅ | Purchase plus your maintenance time |

## The options

**Extend the existing aipotluck.org AWS stack (recommended core).**
- The CDK app already handles the hard parts: the GitHub App, webhooks, one-job ephemeral instances,
  failure alarms and weekly image rebuilds.[1][2]
- CloudSnorkel's EC2 provider supports Windows images and GPU instances.[12]
- Adding a `g4dn.xlarge` Linux image with the NVIDIA driver and a Windows image (CPU, plus a
  `g4dn` variant with the NVIDIA driver) gives four of the six legs.
- On-demand rates in us-west-2:[15]
  - `g4dn.xlarge` (T4, 16 GB): $0.526/h Linux, $0.71/h Windows;
  - Windows `m6a.xlarge`: $0.3568/h.
- Spot `g4dn.xlarge` on Linux is $0.289/h.[16]
- Caveats:
  - the account's spot quota is already saturated by web CI;[4]
  - Windows NVIDIA drivers for EC2 come from AWS's own driver channel and need baking into an
    image;[41]
  - the stack lives in a repo with its own deploy gate (`deploy.sh` refuses unmerged code), so
    changes go through aipotluck.org's process.[1]
- The project already plans to move this stack into the Current AI account (SOL-96). That is
  another reason to coordinate rather than fork it.

**GitHub-hosted runners.**
- Standard runners need no infrastructure:
  - Linux: $0.006/min;
  - Windows: $0.010/min;
  - macOS M1 3-core: $0.062/min.[11]
- Larger runners add:[11]
  - M2 Pro 5-core macOS: $0.102/min;
  - T4 GPU Linux: $0.052/min;
  - T4 GPU Windows: $0.102/min.
- They require GitHub Team or Enterprise, and included minutes don't apply to them.[11]
- macOS 14 images retire on 2026-11-02, so target `macos-15`/`macos-latest` (26).[24]
- Hosted arm64 Macs have no nested virtualization.[9]

**Metal on hosted Macs: what can and can't be tested.**
- Hosted arm64 macOS VMs expose a paravirtual Metal device.[23]
- llama.cpp's own `build-apple.yml` builds with Metal on `macos-latest` and runs a model with all
  layers offloaded (`-ngl 99`).[18]
- So "the GUI's llama-server starts and offloads to Metal" is checkable there.
- Two limits:
  - the paravirtual device under-reports its Metal feature set, so llama.cpp selects slower kernels
    and throughput is not representative;[25]
  - memory is tight: a hosted-runner MPS workload hit an out-of-memory error at a 7.93 GB cap.[22]
- llama.cpp still keeps a separate **self-hosted** bare-metal Metal runner for real coverage.[19][17]

**EC2 Mac (bare metal).**
- Real Apple silicon, the physical GPU, and SSM integration.[13]
- Billed per Dedicated Host with a 24-hour minimum allocation; one Mac instance per host.[14]
- Host rates in us-west-2: M1 (`mac2`) $0.65/h, M2 $0.878/h, M4 $1.23/h, M4 Pro $1.97/h.[15]
- The 24 h minimum alone is $15.60 to $47.28 per allocation.
- Always-on is $474 to $1,438 per month: poor value for a nightly 20-minute leg.

**Third-party runner vendors.**
- **Cirrus Runners:** $150/month per concurrent runner with unlimited minutes, on M4 Pro macOS,
  Linux, and Linux GPU.[28] Its macOS runners are Tart VMs,[39] so Metal is still virtualized.
  ⚠️ Verify the GPU feature set.
- **Namespace:** M4 Pro/M5 Max macOS and claims graphics hardware acceleration.[30] Pricing is a
  plan plus unit-minutes.[31]
- **Blacksmith:** Linux and Windows Server 2025 runners, no GPU listed.[32]
- **RunsOn:** like our CloudSnorkel stack (runs in our AWS account, any EC2 type including GPU and
  Windows), with a commercial license.[27] It would duplicate what we already run.
- **MacStadium:** bare-metal Macs and Orka VMs, sales-quoted only.[40]
- **Scaleway:** dedicated, no-hypervisor Mac mini M4 from €0.22/h, also with a 24 h minimum.[29]
  As a monthly rental that is a cheap persistent bare-metal Metal box, though in Paris.

**Other GPU clouds.**
- Azure's T4 VM (NC4as T4 v3) lists at about $0.53 to $0.63/h, the same ballpark as `g4dn.xlarge`.[35]
- It would add a second cloud account and runner stack for no price advantage over the AWS stack we
  already run.

**Hugging Face Jobs (CUDA only).**
- llama.cpp runs its CUDA CI on a `hf-jobs-t4-medium` runner label.[20]
- HF prices a T4-medium at $0.60/h.[33]
- Hugging Face Jobs runs Docker images on chosen GPU hardware.[34] How that integrates with GitHub
  Actions outside the ggml org is ⚠️ unverified.
- Linux only, and not cheaper than our own `g4dn`.

**Local hardware (last resort).**
- A Mac mini plus a Windows/Linux PC with an NVIDIA GPU, each registered as a persistent self-hosted
  runner, covers all six legs on bare metal. This is what llama.cpp does for Metal.[19]
- Costs:
  - persistent runners accumulate state between jobs (the CUR-1534 analysis requires ephemeral
    runners for this reason);[3]
  - OS, driver and Xcode updates become our job;
  - self-hosted runners must never serve a public repo, since any PR could run code on them.[36]

## Cost shape

Workload assumption (mine, not sourced): each leg is a build plus a GUI smoke test, about **20
minutes**. Costs below are computed from the cited unit prices[11][15][16][33] for two cadences.
"Nightly" is 30 runs/month; "per-merge" is about 120 runs/month.

| Leg | GitHub-hosted, nightly | AWS on-demand, nightly | GitHub-hosted, per-merge | AWS on-demand, per-merge |
|---|---|---|---|---|
| Linux CPU | $7.20 | $3.06 | $28.80 | $12.24 |
| Linux CUDA | $31.20 (Team) | $5.26 (spot $2.89; HF $6.00) | $124.80 | $21.04 |
| macOS CPU | $37.20 | — | $148.80 | — |
| macOS Metal (M2 Pro larger) | $61.20 (Team) | — | $244.80 | — |
| Windows CPU | $13.20 | $3.57 | $52.80 | $14.27 |
| Windows CUDA | $61.20 (Team) | $7.10 | $244.80 | $28.40 |
| **All six** | **$211.20** | n/a | **$844.80** | n/a |

Ratios that drive the decision:
- GitHub's GPU runner versus an on-demand `g4dn.xlarge`: **5.93×** more on Linux and **8.62×** more
  on Windows.
- A macOS M1 minute on GitHub costs **10.3×** a Linux 2-core minute.
- An always-on EC2 M4 Mac host costs **6.0×** a Cirrus runner per month.
- A Cirrus runner breaks even with GitHub's M2 Pro runner at **24.5 hours** of use per month.

Scenario monthly totals (nightly / per-merge):

| Scenario | Nightly | Per-merge |
|---|---|---|
| **A.** All GitHub-hosted (Team plan) | $211.20 | $844.80 |
| **B.** AWS stack for Linux and Windows (4 legs) + GitHub standard `macos-latest` for macOS CPU and functional Metal | **$93.39** | $373.55 |
| **C1.** B, but Metal on a Cirrus M4 Pro runner | $206.19 | — |
| **C2.** B, but Metal on an always-on EC2 M4 host | $954.09 | — |
| **D.** Local hardware for all six | one-off hardware + maintenance time | same |
| **E.** AWS stack for Linux and Windows (4 legs) + the incoming Mac mini M5 for macOS CPU and bare-metal Metal | **$18.99** + Mac upkeep | $75.95 + Mac upkeep |

The AWS rows are on-demand, before spot savings. Scenario B's macOS legs use the standard M1 runner
($0.062/min), which needs no Team plan. Scenario E removes the $74.40/month (nightly) or $297.60/month
(per-merge) of hosted macOS minutes that B would bill. Its macOS legs cost electricity and time,
not minutes.

## Scenarios

**Scenario A: all GitHub-hosted.** Pros:
- fastest to set up: Tauri's reference workflow is a three-OS matrix, using the `tauri-action` GitHub Action;[37][38]
- nothing to maintain.

Cons:
- requires upgrading the org to Team;[11]
- GPU legs are 6 to 9× the cost of AWS;
- Metal is paravirtual.

**Scenario B (recommended): extend our AWS stack, use hosted Macs.** Pros:
- reuses infrastructure, alarms and process the team already runs;[1]
- GPU legs at EC2 prices;
- no plan upgrade needed;
- cheapest complete coverage.

Cons:
- Windows and GPU AMIs to build and maintain;
- contention with the already-saturated spot quota;[4]
- the macOS Metal leg proves function, not speed.[25]

**Scenario C: B plus one bare-metal Mac for Metal performance.** Adds real Metal benchmark numbers,
the gap llama.cpp itself closes with a self-hosted Mac.[19] Choose this when you need:
- the GUI's benchmark and LocalScore numbers on macOS; or
- regressions caught in Metal kernel selection.

Cheapest steady option: a fixed-price vendor runner (Cirrus) or a monthly Scaleway Mac.[28][29]
EC2 Mac's 24 h minimum makes it the most expensive per test hour.[14]

**Scenario E (recommended): the AWS stack plus the incoming Mac mini M5.**
Scenario B for the four Linux and Windows legs, with the macOS legs moved onto the Mac mini M5
Andrew is already buying. It is local hardware (the last-resort class), but limited to the one
platform where every cloud option is either virtualized or expensive.

Pros:
- **Bare-metal Metal**: the only option here that measures real Metal kernel selection and
  throughput. Hosted and Tart-based Macs go through the paravirtual GPU.[25][23]
- **No recurring cloud cost** for macOS, which removes the most expensive per-minute legs;[11]
  EC2 Mac's 24 h minimum avoided.[14]
- A newer, larger chip than any hosted or EC2 Mac in this report (M1 to M4 Pro).[9][15]
- Matches how llama.cpp itself covers Metal: one self-hosted Apple-silicon runner.[19]

Cons:
- **Persistent hardware.** GitHub recommends ephemeral runners, which unregister after each
  job.[44][45] A bare-metal persistent runner otherwise carries state between jobs, which
  is why CUR-1534 required ephemeral cloud runners.[3]
- **A single point of failure.** If the mini sleeps, reboots for an update or loses network, the macOS
  legs queue. Keep a hosted-Mac fallback.
- **Security.** Never attach it to a public repo, since fork PRs could run code on a machine in your
  home or office.[36]
- **Maintenance is yours**: macOS and Xcode updates, the runner agent, disk space, power.
  The runner agent self-updates by default.[44]

How to run it with the least upkeep (the plan; scripts not yet written):
1. **Two runner modes on one machine:**
   - **macOS Metal leg:** bare metal, under a dedicated non-admin macOS user, registered as an
     ephemeral runner and re-registered after every job. Bare metal is the only way to get real
     Metal numbers.[45]
   - **macOS CPU leg:** inside a throwaway Tart VM cloned from a golden image per job. That gives a
     clean install every time, like the cloud runners.[39]
2. **At most two macOS VMs at a time.** Apple's licence caps a Mac at two concurrent macOS VMs, which
   bounds how many CPU-leg jobs can run in parallel.[46][47]
3. **Labels:** `[self-hosted, macOS, ARM64, metal-baremetal]` and `[self-hosted, macOS, ARM64,
   tart-vm]`, so workflows pick a mode explicitly.
4. **Scope:** register at the GUI repo, or a private org runner group, only.
5. **Unattended operation:**
   - no sleep;
   - restart after power failure;
   - automatic login for the runner user;
   - macOS updates on a manual schedule, so an update can't reboot it mid-job.
6. **Fallback:** a workflow input (or repo variable, as aipotluck.org does with `CI_CLIENT_RUNS_ON`)
   flips the macOS legs back to `macos-latest` when the mini is down.[1]

**Scenario D: local hardware.** Pros:
- lowest marginal cost;
- real GPUs everywhere.

Cons:
- persistent, stateful runners;
- your maintenance time;
- must stay off public repos;[36]
- a single point of failure.

Keep it for exploratory work, not as the gate.

## Recommended architecture

- **Every push (fast, ~$0):** unit, contract and conformance tests plus a compile check on all three
  OSes. CPU-only, no GPU:
  - Linux on the existing `aipotluck-2cpu` label;
  - Windows and macOS on standard hosted runners.

  Upstream llama.cpp does the same: compile-only Windows CUDA builds on hosted `windows-2022`.[21]
- **Nightly or on bump (scenario E; scenario B when the Mac mini is offline):**
  - the full six-leg matrix;
  - a real installer run;
  - a real model load;
  - on GPU legs, an assertion that layers were offloaded to the GPU (from llama-server's log or
    `/props`).

  Run it on every `chore/upstream-bump-*` branch the sync job prepares. That turns the existing
  upstream watchdog into a real compatibility gate.
- **Metal performance:** the GUI's benchmark and LocalScore run on the Mac mini's bare-metal leg, so
  a Metal kernel regression shows up as a number, not a guess.
- **Before a release:** a manual pass on real Linux and Windows desktops with NVIDIA GPUs (the
  macOS one is already covered by the mini). A rented bare-metal Mac (scenario C) is only needed if
  the mini is unavailable for a long period.

## Best-practice checklist

- **Ephemeral, one job per runner.** Persistent runners accumulate cross-job state. The aipotluck.org
  stack already works this way, and this project should inherit it.[3][1]
- **Never use self-hosted runners on a public repo.** Fork PRs can run code on them.[36] The GUI repo
  is private today; revisit before open-sourcing.
- **Build Linux release artifacts on the oldest supported base.** Tauri's AppImage guidance is to
  build on Ubuntu 22.04 for glibc compatibility.[42] The current CI image is 24.04, so add a 22.04
  image or container for the release build.[2]
- **Separate "builds" from "runs on the GPU."** Assert offload explicitly in the test. Hosted Metal
  will load a model whether or not the kernel path is representative.[25]
- **Pin macOS images.** macOS 14 retires 2026-11-02, with brownouts before then.[24]
- **Put the matrix where the cadence is cheap.** GPU minutes are the expensive ones: run them nightly
  and on upstream bumps, not on every push.

## Verify these before committing

1. **GPU quota.** In the aipotluck AWS account, list the G-family quotas by name rather than trusting a
   remembered code: `aws service-quotas list-service-quotas --service-code ec2 --region us-west-2
   --query "Quotas[?contains(QuotaName,'G and VT')].[QuotaName,QuotaCode,Value]"`. Expected: the
   on-demand quota is ≥ 4 vCPU, or `g4dn.xlarge` can't launch at all. Check the spot G-quota in the
   same output.[4]
2. **Metal on a hosted Mac.**
   - Run one `macos-latest` job that installs the GUI's pinned llama.cpp asset.
   - Run `llama-server --list-devices`, then load a small GGUF with `-ngl 99`.
   - Expected: a Metal device listed (likely "Apple Paravirtual device") and layers offloaded.[23][18]
3. **CloudSnorkel Windows + GPU.**
   - `cdk synth` a provider using `Os.WINDOWS` with `instanceType: g4dn.xlarge` and an image component
     that installs the NVIDIA Windows driver.[12][41]
   - Expected: synth succeeds and `nvidia-smi` runs in a probe job.
4. **Upstream Windows CUDA.** Confirm whether llama.cpp's release has a Windows CUDA asset for the
   pinned tag. If so, file the upstream change: add it to `llama_version.json`, and make
   `detect_gpu_backend` return `cuda` on Windows.[6][7]
5. **macOS e2e driver.** Add `@wdio/tauri-service` to the GUI repo and run the smoke flow on a hosted
   Mac.[43]

6. **Mac mini runner, once it arrives** (no scripts yet, by request):
   - register it as an ephemeral runner on the GUI repo only;
   - run the Metal smoke test with `-ngl 99`, then one `llama-bench`;
   - expected: `--list-devices` shows the M5 GPU by name, not "Apple Paravirtual device", and the
     generation speed is well above the same run on `macos-latest`.[23][25]

## Open questions for you

1. Is upgrading the GitHub org to Team on the table? It unlocks GPU and larger Mac runners as a
   zero-maintenance fallback, but scenario B doesn't need it.[11]
2. Should this project's runners live in aipotluck.org's `ci-runners/` stack (shared with web CI, its
   deploy gate and the SOL-96 account move), or in a sibling stack in the same account?[1]
3. Do you need Metal and CUDA *performance* numbers in CI (benchmark and LocalScore), or only "it
   loads on the GPU"? The answer decides whether scenario C is needed.
4. Is the GUI repo staying private? Public repos rule out self-hosted runners for untrusted PRs.[36]

## Addendum (2026-10-09): build-only automation

Scope narrowed to producing release installers; testing on GPUs is deferred.

### Which build targets are actually needed

GPU support is **not** a GUI build dimension:
- The GUI binary contains no CUDA or Metal code. It ships a CPU-only shell (Tauri), a bundled Python
  and the pinned CLI source.
- The CLI's installer picks and downloads the right llama.cpp asset (CPU, CUDA, Vulkan, ROCm; Metal
  built into the macOS asset) on the user's machine at setup time.[6][7]
- So one GUI binary per **OS × CPU architecture** covers every GPU variant on that platform.

The architecture list is bounded by what the bundled pieces exist for:

| Component | Targets with an asset |
|---|---|
| Bundled Python (`runtime/python_version.json`) | linux-x64, linux-arm64, macos-arm64, macos-x64, windows-x64 |
| newt tunnel client[8] | linux-x64, linux-arm64, macos-arm64, macos-x64, windows-x64 |
| llama.cpp release assets[6] | the same five plus windows-arm64 (CPU only) |

**Five build targets:**

| Target | Priority | Notes |
|---|---|---|
| linux-x64 | must | Ubuntu/Debian desktops; also covers Linux CUDA, Vulkan and ROCm users |
| windows-x64 | must | also covers Windows CUDA users once upstream wires it |
| macos-arm64 | must | all Apple-silicon Macs; Metal comes from the llama.cpp asset |
| linux-arm64 | nice | Jetson boards (upstream's confirmed hardware), Pi-class devices |
| macos-x64 | optional | Intel Macs. Cross-compiles on an Apple-silicon Mac, so no Intel hardware is needed.[37] |

Two notes on the list:
- windows-arm64 is skipped: there is no bundled Python or newt for it yet.
- Linux targets must be built on **Ubuntu 22.04** (or in a 22.04 container) so the binary runs on
  22.04+. Building on a newer distro raises the glibc floor.[42] This repo's Debian 13 dev build
  needs GLIBC_2.39, measured.

### Option 1: fully cloud-hosted (GitHub-hosted runners)

One workflow, a five-way matrix, `tauri-action` (or the repo's own `tools/build.sh`), triggered on a
version tag. It uploads the `.deb`, AppImage, `.dmg` and `.msi`/`.exe` to a GitHub Release.[37][38]

| Target | Runner label |
|---|---|
| linux-x64 | `ubuntu-22.04` |
| linux-arm64 | `ubuntu-22.04-arm` (GitHub-hosted arm64)[9] |
| windows-x64 | `windows-latest` |
| macos-arm64 and macos-x64 | `macos-latest`, two jobs, `--target` per arch[37] |

- **Setup effort:** one workflow file, roughly a day including fixing what breaks on the first
  Windows and macOS builds. No machines, no accounts beyond GitHub.
- **Maintenance:** essentially none. GitHub patches the images; we only bump labels when an image is
  retired (macOS 14 retires 2026-11-02).[24]
- **Cost,** computed at ~12 runner-minutes per target per build on standard runners:[11]
  - all five targets: about **$1.74 per release**;
  - **85.5%** of that is the two macOS jobs ($0.062/min);
  - 8 releases/month ≈ **$14**; a nightly build of everything ≈ **$52/month**;
  - without the macOS jobs, the same nightly build would be ≈ $7.56/month.
- **No GitHub plan upgrade** is needed: these are standard runners, not larger or GPU ones.[11]
- **Unsigned for now:**
  - macOS users will see a Gatekeeper warning until there is an Apple Developer ID;
  - Windows will show SmartScreen.

  Signing slots into the same workflow later, as secrets.

### Option 2: hybrid with your own hardware

The same workflow, with `runs-on` switched per target to self-hosted runners:

| Target | Machine | Caveat |
|---|---|---|
| macos-arm64 and macos-x64 | Mac mini M5 | Fastest builder of the lot. Cross-compiles x64. |
| windows-x64 | Linux/Windows PC (Windows side) | Needs VS Build Tools, Rust, Node, WebView2 SDK |
| linux-x64 | Same PC, via WSL2 Ubuntu 22.04 (or a 22.04 VM/container) | One box can't be a native Linux and a native Windows runner at the same time unless dual-runner via WSL2 |
| linux-arm64 | Raspberry Pi | Must build inside an Ubuntu 22.04 container to keep glibc compatible.[42] The Hermes container on this Pi has no Docker daemon, so this needs a separate OS install or a native 22.04 rootfs. Slowest builder: the release compile alone took ~8.5 min here. |

- **Setup effort:**
  - three machines × (OS prep, toolchains, runner agent, auto-start, no-sleep);
  - plus an Ubuntu 22.04 environment on two of them;
  - realistically 2 to 4 days, with Windows the most fiddly.
- **Maintenance:**
  - OS and toolchain updates on three boxes;
  - disk cleanup (Rust `target/` grows by GBs);
  - keeping them online;
  - a release blocks whenever one is down.

  GitHub recommends ephemeral runners;[44] persistent home-lab runners accumulate state between
  builds, so clean the workspace or use a container per job.
- **Security:** fine on a private repo. Never attach these runners to a public one.[36]
- **Cost:** about $0 in minutes. What you save is **≈ $14/month** at 8 releases, or ≈ $52/month if
  you build nightly, almost all of it from the macOS jobs.

### Recommendation

**Start with Option 1 (all hosted).** The money at stake is small: a few dollars to tens of dollars
a month. Option 2 costs days of setup and ongoing maintenance on three machines. And the hard parts
of Option 2 (glibc-compatible Linux builds, a clean Windows toolchain) come free on hosted images.

If anything moves on-prem later, move only the **macOS jobs to the Mac mini**:
- that is 85% of the hosted bill;
- the mini is already planned for Metal testing;
- it is the one machine whose toolchain (Xcode, Rust, Node) is easy to keep current.

Change one `runs-on` line to point the macOS jobs at the mini, and keep `macos-latest` as the
fallback. Leave the Pi and the PC out unless GitHub minutes become a real constraint.

## Sources

[1] https://github.com/currentai-org/aipotluck.org/blob/develop/ci-runners/README.md — aipotluck.org ci-runners/README.md (ephemeral self-hosted runners on EC2 spot)
[2] https://github.com/currentai-org/aipotluck.org/blob/develop/ci-runners/main.go — aipotluck.org ci-runners/main.go (CDK stack: sizes, Ubuntu 24.04 image)
[3] https://linear.app/currentai-org/issue/CUR-1534/ci-minutes-not-correctness-are-what-keeps-gates-off-prs-an-ephemeral — CUR-1534: ephemeral self-hosted runner on spot (cost analysis, billing observations)
[4] https://linear.app/currentai-org/issue/SOL-102/the-accounts-32-vcpu-spot-quota-sends-most-ci-runners-to-on-demand-at — SOL-102: 32-vCPU spot quota in the AWS account
[5] https://linear.app/currentai-org/issue/CUR-1963/build-test-architecture-support-for-various-local-inference-server — CUR-1963: Build + test architecture support for local inference targets
[6] https://github.com/currentai-org/aitpotluck-local-client/blob/main/llama_version.json — aitpotluck-local-client llama_version.json (pinned b10989 assets)
[7] https://github.com/currentai-org/aitpotluck-local-client/blob/main/aipotluck/installer/platform_detect.py — aitpotluck-local-client platform_detect.py (backend detection)
[8] https://github.com/currentai-org/aitpotluck-local-client/blob/main/newt_version.json — aitpotluck-local-client newt_version.json (UNVERIFIED mac/win checksums)
[9] https://docs.github.com/en/actions/reference/runners/github-hosted-runners — GitHub Docs: GitHub-hosted runners reference
[10] https://docs.github.com/en/actions/reference/runners/larger-runners — GitHub Docs: Larger runners reference (incl. GPU T4)
[11] https://docs.github.com/en/billing/reference/actions-runner-pricing — GitHub Docs: Actions runner pricing
[12] https://github.com/CloudSnorkel/cdk-github-runners — CloudSnorkel/cdk-github-runners README
[13] https://aws.amazon.com/ec2/instance-types/mac — AWS: Amazon EC2 Mac instances
[14] https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-mac-instances.html — AWS docs: Amazon EC2 Mac instances (Dedicated Host, 24h minimum)
[15] https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/us-west-2/index.json — AWS Price List API, EC2 us-west-2 (published 2026-10-08)
[16] https://instances.vantage.sh/aws/ec2/g4dn.xlarge — Vantage: g4dn.xlarge pricing (spot)
[17] https://github.com/ggml-org/llama.cpp/blob/master/ci/README.md — llama.cpp ci/README.md (self-hosted heavy CI)
[18] https://github.com/ggml-org/llama.cpp/blob/master/.github/workflows/build-apple.yml — llama.cpp build-apple.yml (Metal on macos-latest)
[19] https://github.com/ggml-org/llama.cpp/blob/master/.github/workflows/ci-self-hosted-metal.yml — llama.cpp ci-self-hosted-metal.yml
[20] https://github.com/ggml-org/llama.cpp/blob/master/.github/workflows/ci-self-hosted-cuda.yml — llama.cpp ci-self-hosted-cuda.yml (hf-jobs-t4-medium)
[21] https://github.com/ggml-org/llama.cpp/blob/master/.github/workflows/build-cuda-windows.yml — llama.cpp build-cuda-windows.yml (windows-2022 compile-only)
[22] https://github.com/actions/runner-images/issues/9918 — runner-images #9918: macOS runner MPS out of memory
[23] https://github.com/actions/runner-images/issues/14840 — runner-images #14840: macOS ARM64 paravirtual Metal device
[24] https://github.blog/changelog/2026-10-01-github-actions-macos-14-runner-image-retirement — GitHub changelog: macOS 14 runner image retirement
[25] https://cua.ai/blog/gpu-passthrough-macos-vms — Cua: llama.cpp in macOS VMs, paravirtual GPU capability gap
[26] https://developer.apple.com/documentation/paravirtualizedgraphics — Apple: ParavirtualizedGraphics framework
[27] https://runs-on.com — RunsOn: self-hosted runners in your AWS account
[28] https://cirrus-runners.app — Cirrus Runners: fixed-price macOS M4 Pro / Linux GPU runners
[29] https://www.scaleway.com/en/mac-mini-m4 — Scaleway: Mac mini M4 as a Service
[30] https://namespace.so/docs/architecture/compute/macos — Namespace: macOS compute (M4 Pro / M5 Max)
[31] https://namespace.so/pricing — Namespace pricing
[32] https://docs.blacksmith.sh/blacksmith-runners/overview — Blacksmith runner instance types
[33] https://huggingface.co/pricing — Hugging Face pricing (T4 hardware rates)
[34] https://huggingface.co/docs/huggingface_hub/guides/jobs — Hugging Face Jobs guide
[35] https://www.thundercompute.com/blog/azure-gpu-instances — Thunder Compute: Azure GPU instances and prices
[36] https://docs.github.com/en/actions/reference/security/secure-use — GitHub Docs: Secure use reference (self-hosted runners and public repos)
[37] https://v2.tauri.app/distribute/pipelines/github — Tauri: GitHub Actions pipeline (tauri-action matrix)
[38] https://github.com/tauri-apps/tauri-action — tauri-apps/tauri-action
[39] https://github.com/cirruslabs/tart — cirruslabs/tart (macOS VMs on Apple silicon)
[40] https://www.macstadium.com/pricing — MacStadium pricing (Orka, bare metal)
[41] https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/install-nvidia-driver.html — AWS docs: NVIDIA drivers for EC2 (incl. Windows)
[42] https://v2.tauri.app/distribute/appimage — Tauri: AppImage (glibc baseline; ARM build constraints)
[43] https://v2.tauri.app/develop/tests/webdriver — Tauri: WebDriver testing (tauri-driver Win/Linux; WebdriverIO embedded for macOS)
[44] https://docs.github.com/en/actions/reference/runners/self-hosted-runners — GitHub Docs: Self-hosted runners reference (ephemeral runners, auto-update)
[45] https://github.blog/changelog/2021-09-20-github-actions-ephemeral-self-hosted-runners-new-webhooks-for-auto-scaling — GitHub changelog: ephemeral (single-job) self-hosted runners
[46] https://www.jochendelabie.com/2023/09/20/macos-virtualization-framework — Virtualization.framework: 2 macOS VMs per Mac (EULA limit)
[47] https://tart.run/faq — Tart FAQ (Virtualization.framework limits)
