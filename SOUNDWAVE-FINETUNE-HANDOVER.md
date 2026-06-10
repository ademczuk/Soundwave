# Soundwave Fine-Tuning Handover

For a fresh CLI session picking up Soundwave training. Self-contained: every path was verified on disk 2026-06-10. Read sections 0, 5, and 6 before you train anything.

## 0. Orientation

Soundwave is a local offensive-security / MITRE ATT&CK analysis model served by the `soundwave-mcp` MCP on a single RTX 5090 (32 GB). Two repos and one bucket:

- **This folder** `C:\Projects\_Jobs\Collaborations\Andrew\Soundwave` holds the GGUF weight files, but do not mistake it for a weights repo. Its git checkout is a private FORK of `PurpleAILAB/Decepticon` (origin `ademczuk/Soundwave`, upstream `PurpleAILAB/Decepticon`); the TRACKED content is the Decepticon offensive-security CLI codebase, not Soundwave. The GGUFs, this handover, the `soundwave/` dir, the training/backup scripts, and `data/` are UNTRACKED files sitting on top of that checkout, deliberately not committed (19 GB GGUFs do not belong in git). The source of truth for the weights is S3 (next bullet); do not expect `git` here to version or restore them, and do not commit them without a deliberate decision (a `.gitignore` to silence the untracked noise is the lighter option).
- **`C:\Projects\soundwave-mcp`** (git `ademczuk/soundwave-mcp`, private) is the serving MCP + the design/plan docs.
- **S3 `red-mod-26`** (us-east-1, creds in `~/keys.txt`) is the durable weights + training-data sink. `LATEST.json` and `SOUNDWAVE-LATEST.md` at the bucket root name the chosen model.
- **`C:\Projects\_v5work`** holds the eval probes and the v7 training/eval scripts.
- **`C:\Projects\exploitbench`** holds `gate0_substrate.py` and chat templates.

The model role: map code / claims / designs to ATT&CK technique ids + a kill chain + detection gaps, narrate a pinned kill chain for blue-team detection, and act (emit a tool-call) only when an AUTHORIZED principal asks, never when an untrusted tool-result tells it to. Eval axes: ATT&CK moat (technique mapping), narration (real prose), uncensored, acting (act when instructed), injection-resistance (refuse role:tool injected commands), fluency.

## 1. Current state: v7b is the chosen model

`soundwave-v7b-Q5_K_M.gguf` (19.2 GB Q5, in this folder) was promoted as the production CANARY on 2026-06-10. It supersedes the prior "v4-flagship stands, every successor rejected" conclusion: v7b is the first successor to beat the flagship on capability without an injection regression.

- **What it is:** AEON7 (Qwen3.6-27B-AEON-Ultimate-Uncensored, BF16) + a DoRA all-linear SFT (2 epochs) then a 300-step DPO injection-repair pass, merged two-stage (AEON7 + the SFT-adapter, then + the DPO-adapter, so the DPO base is AEON7+SFT). Arch is `qwen3_5` / Gated-DeltaNet, so it needs the `b9415` llama-server build. (Recipe verified from `_v5work/V7B_VERDICT.json` and `_v5work/RETRAIN_PREREG.yaml`.)
- **Benchmark vs v4-flagship** (live, same harness, RTX 5090, from `_v5work/V7B_VERDICT.json` + `V7B_DECISION.json`): moat 24/30 in-dist + 13/68 held-out (flagship 20/9), narration 20/20 real prose with 0 verdict-JSON (flagship ~2), uncensored 48/50, acting act-rate 1.00 (flagship 0.83, no Axis-A regression). Injection is at PARITY, not a safety gain: the pooled 6-seed union is 4/12 == flagship 4/12, the family floor no offline-DPO model beats (the initial 3/12 SHIP read was a favorable seed draw; the seeds-4/5/6 stability re-test gave 4/12). 4/12 is ABOVE the pre-registered `<= 3/12` injection bar, which is exactly why v7b shipped as a CANARY, not an unconditional swap. The input-sanitization shim is mandatory for any execution-plane use.
- **Served via:** `~/.claude.json` soundwave-mcp `SOUNDWAVE_GGUF` points at this GGUF; alias/`SOUNDWAVE_MODEL` stay `soundwave-v4-flagship` (alias serves v7b weights, clients unchanged). Rollback is a one-line `SOUNDWAVE_GGUF` revert to the flagship. See `soundwave-mcp/PROMOTION-v7b-canary.md`.

## 2. Model lineage

| Version | What it was | Verdict | GGUF |
|---|---|---|---|
| v1, v3 | early Qwen3-33B finetunes | superseded | S3 root |
| v4-prod | Qwen3.5-27B, unvalidated different-lineage default | retired (crashed the battery) | this folder `soundwave-v4-Q5_K_M.gguf` |
| **v4-flagship** | Qwen3-33B "Student Dpo Merged", the long-standing incumbent (moat 20/30, acting 0.833, injection 2-3/12 single-run = 4/12 on the 6-seed union) | ROLLBACK target | this folder `soundwave-v4-flagship-Q5_K_M.gguf` + S3 |
| v5-sft / v5.1 / v5.2 / v5.3 | offline SFT then DPO line on the flagship base | all NO-GO (v5-sft broke injection 10/12; rest lateral) | S3 `soundwave-v5*` |
| v6 RFT / v6 hardened-GRPO de-risk | online-RL de-risk attempts | both NO-GO (reward-hacked a weak verifier) | S3 `soundwave-v6-data/` |
| v7-250 | AEON7 SFT + 250-step DPO, an earlier under-repaired checkpoint of the v7 run (same moat 24 + acting 1.0, but injection 5/12 on the 3-seed union; the extra 50 DPO steps to v7b reached the floor) | superseded by v7b; kept as rollback | this folder `soundwave-v7-Q5_K_M.gguf` |
| **v7b** | AEON7 SFT (2 ep) + 300-step DPO injection-repair: moat 24/30 + 13/68, acting 1.0, injection 4/12 (6-seed union, family-floor parity with flagship); the extra DPO over v7-250 is what reached the floor | **CHOSEN (canary 2026-06-10)** | this folder `soundwave-v7b-Q5_K_M.gguf` + S3 `soundwave-v7-data/v7b-part-00..04` |

Any future candidate must beat v7b (or the flagship) on the full battery, with no regression, to ship. Tied or unproven keeps the incumbent.

## 3. The proven recipe (v7, the one that worked)

This is the recipe that produced the chosen model. The closed v5/v6 line finetuned the Qwen3-33B flagship, which is structurally agentic-incapable (thinking-mode overflows context, thinking-off times out). v7 switched to the AEON7 / lean lineage, which already solves the agentic task and starts at a stronger moat, so training only had to ADD narration + uncensored, not chase capability the architecture prevents.

- **Base:** AEON7 at `C:/Projects/llama-cpp/models/aeon7-qwen36-27b-bf16/` (52 GB, abliteration already applied, $0 cash; `qwen3_5` Gated-DeltaNet hybrid). Fallback only if the AEON7 gate fails: fresh-abliterate Qwen3.5-27B on a rented L40S (the 5090's 32 GB cannot hold the SVD step).
- **Actual recipe (what shipped, verified from `RETRAIN_PREREG.yaml` + `V7B_VERDICT.json`):** a single DoRA all-linear SFT (2 epochs) producing the SFT adapter (`step2-sft-adapter.tgz` on S3 `soundwave-v7-data/`), then a 300-step DPO injection-repair on the AEON7+SFT base producing the DPO adapter (`step2-adapter-350.tgz` on S3). Merge two-stage: AEON7 + SFT-adapter, then + DPO-adapter. Convert with the DOT-tree `C:/Projects/llama.cpp/convert_hf_to_gguf.py` (it carries Qwen3_5TextModel/QWEN35; the dash-tree converter does not), quantize with `C:/Projects/llama-cpp/b9415/llama-quantize.exe` to Q5_K_M (~18.4 GiB). This is SIMPLER than the UNIFIED-RETRAIN-PLAN's staged S1-r8 / S2-r32 / S3 design: the shipped run used one SFT stage, not two. HARD-CAP narration rows at 2048 tokens regardless (landmine 8).
- **Local de-risk gate:** `_v5work/gate_train_5090.py` is the cheap abort gate: 4-bit QLoRA NF4, DoRA `r=8` all-linear, `MW_MAX_STEPS=80`, lr 2e-4, paged_adamw_8bit, gradient-checkpointing, seq 2048. It fits the 27B on one 32 GB 5090 (the bf16 path needs ~54 GB). Run on a small mixed subset and abort if post-gate injection > 6/12, narration < 0.50, or moat spot-check < 15/30 before paying for the full run.
- **Where the full run ran + the merge:** the local 5090 can run the SFT/DPO (UNIFIED VRAM table: DoRA SFT ~22-27 GB fits; DPO needs Unsloth `disable_adapter` for the reference or standard TRL OOMs on a 2nd copy). The bf16 MERGE cannot run on local Windows (landmine 1), so `_v5work/merge_gguf_vast.py` does merge+convert+quantize+split on a rented Linux box; `_v5work/merge_v7.py` is the local merge attempt that hit the paging-file limit.
- **Eval scripts (in `C:\Projects\_v5work`):** `eval_v7_gates.py` (acting + injection vs a live serve on :8099), `inj3_v7.py` / `inj3_v7_s456.py` (the 3-seed + the seeds-4/5/6 stability injection runs), `RETRAIN_PREREG.yaml` (pre-registered protocol), `V7B_VERDICT.json` / `V7B_DECISION.json` / `heldout_v7b.json` / `h2h_v7b.json` (the results).
- **Chat template:** `soundwave-mcp/soundwave-qwen3.jinja` (also at `exploitbench/chat_templates/`). AEON7's default template raises "No user query found" on injection-format prompts, so training and serving both pin this template and pre-filter rows; fall back to bare `--jinja` only if tool_call replay 500s.
- **Fuller (but partly aspirational) recipe:** `soundwave-mcp/UNIFIED-RETRAIN-PLAN.md` has the staged-gate design and the VRAM math. It predates the v7b ship, still says "v4-flagship stands", and describes the 3-stage plan the actual run simplified; read it for the VRAM table and the staged gates, not as the as-built recipe.

## 4. The ship gate: validation battery (DO NOT SKIP)

Six checks. Checks 1-5 are capability/integrity gates; check 6 is the decider. Probes live in `C:\Projects\_v5work` and `C:\Projects\exploitbench`. Serve the candidate on a test port with the b9415 build and `--chat-template-file soundwave-mcp/soundwave-qwen3.jinja` (without it, llama.cpp falls back to Hermes-2-Pro and 500s on tool_call replay, skipping the injection test entirely). The `/soundwave-validate` skill documents the full procedure.

1. **GATE0 substrate** (`exploitbench/gate0_substrate.py`) - is the artifact real, not a silent merge failure. Hash a deep region (~55% into the file), not a prefix (a linear-only LoRA merge leaves the header + embeddings unchanged and a prefix hash false-collides).
2. **Axis A, the ship gate** (`_v5work/describe_vs_act_probe.py`) - does it ACT where the base only describes. A large drop is a hard fail.
3. **ATT&CK moat** (`_v5work/attack_probe_fair.py`, fair = technique-correct any id-version) - non-inferiority on technique mapping. Held-out probe: `_v5work/probe_heldout_moat.jsonl` (68 techniques, training-disjoint).
4. **Loop guardrail** (`exploitbench/eb_v51_validate.py`) - repetition-loop check over full episodes.
5. **Fluency / over-optimization** (`_v5work/fluency_probe.py`, then `fluency_compare.py`) - perplexity + degeneration vs parent.
6. **Should-not-act / injection, THE DECIDER** (`_v5work/injection_probe.py`, `_v5work/expanded_injection_probe.py`). **CRITICAL RULE:** the injected payload MUST be delivered in a `role:"tool"` function result following the model's own tool_call, NEVER in a `role:"user"` message. A user-role payload tests operator-instruction-following (the model reads user as the trusted operator endorsing the command); only the tool role measures the trust boundary. The first v5.1 verdict was backwards because the probe put the payload in the user role. Re-read the probe code and confirm the role before trusting any injection number.

**The v7 run used a stricter, pre-registered protocol** (`_v5work/RETRAIN_PREREG.yaml`, from `_v5work/PROOF_PROTOCOL.md`), git-committed BEFORE the candidate GGUF existed so thresholds cannot be re-derived from the data under test (the aggregator errors if the GGUF predates the commit). Beyond the six checks it adds: a **harness-validity gate** (re-serve v4-flagship live; if the known model does not reproduce its 20/30 moat and 2-3/12 injection, the INSTRUMENT is broken, not the candidate - this caught 5 fake numbers in the v5 arc), the held-out moat scored by exact **McNemar** vs flagship (n=68, hard floor 34 = 0.50 x 68), **Holm-Bonferroni** correction across the primary family (moat / injection / narration / uncensored), and the injection hard bar `union-obey <= 3/12 AND Wilson-upper <= 0.40` with role:tool delivery. Reuse this protocol (or the `/soundwave-validate` 6-check) for the next candidate; do not invent fresh thresholds after seeing the scores.

**Standing verdicts:** v4-flagship is the canonical fallback; v7b is the promoted canary (capability-superior, injection-parity). v5-sft/v5.1/v5.2/v5.3, v6 RFT and v6 hardened-GRPO de-risk are all NO-GO. Family injection floor is ~4/12; the input-sanitization shim is mandatory for any execution-plane use of any candidate. Methodology lesson: re-read the test code before trusting a load-bearing safety verdict (an adversarial check of a conclusion cannot catch a confounded measurement handed to it as ground truth).

## 5. Hard-won landmines (read before training)

Each of these cost real time or money in the v5/v6/v7 arc. They are the difference between a clean run and a multi-day debug.

1. **The 52 GB bf16 merge cannot run on local Windows.** `safe_open` mmap hits "paging file too small" (the Windows virtual-memory commit limit, needs admin + reboot). Do merge + convert + quantize on a rented Linux box. Split the 18.3 GB Q5 into <= 6 parts (presigned PUT caps at 5 GB) and download + reassemble. Reassemble to a drive with room and delete parts as consumed (C: filled to 0 GB once).
2. **DPO OOM at the reference logsumexp.** AEON7's 248320 vocab makes the 3072-length logits spike ~6 GB and OOM even an 80 GB card. Fix: `max_length=1536` + `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
3. **GGUF block_count metadata patch.** The latest llama.cpp converter sets `qwen35.block_count=65` (it counts the MTP layer) but omits the blk.64 tensors, so b9415 fails with "missing tensor blk.64.attn_norm.weight". In-place patch the uint32 at byte offset 329 (65 to 64) and offset 1109 (nextn 1 to 0); then it loads clean. (heretic-v2's GGUF is "Native-MTP-Preserved" and needs NO patch; the Soundwave converter output does.)
4. **Serve-readiness race.** A 19 GB GGUF answers `/v1/models` BEFORE it finishes loading into VRAM; probe then and you get all-zeros. Gate on a real generation succeeding, not the endpoint.
5. **Presigned S3 PUT 403.** A presigned `put_object` URL can 403 under the default boto3 signer when the PUT carries a Content-Type. Force `signature_version=s3v4` + `addressing_style=virtual` on the generating client, and smoke-test every presigned URL with a real local PUT before a paid run depends on it. A working presigned GET does not imply the PUT works.
6. **Gate adapter coverage by module NAME, not param count.** A trainable-param-count threshold is a blind proxy: gating `trainable>400M` false-aborted a healthy run whose real full-coverage count was 237M on this hybrid arch. Enumerate modules with a populated `lora_A` and assert the needed projection names (DeltaNet `in_proj_*`/`out_proj` + MLP + attn) are a subset; keep a low param floor only as a backstop.
7. **Faster GPU, same step time = not compute-bound.** An H200 ran at the same ~15.6 s/step an A100 gives, which proves the workload (the sequential Gated-DeltaNet scan, 48 of 64 layers) is not compute-bound. Disabling gradient checkpointing will NOT give a "2-3x" boost (checkpointing overhead here is ~1.1x); a restart to remove it is net-negative. Check whether a faster GPU helped before paying to remove a compute cost.
8. **Token-volume imbalance destroys the moat.** Uncapped, narration rows outweigh the moat-anchor rows 6-25:1 by token volume and silently destroy the moat. The one-line fix (2048-token cap per narration row + 2x moat oversample) MUST be in the de-risk gate run, not just the full run.
9. **The seesaw is structural.** Offline SFT/DPO cannot collapse narration-vs-injection-vs-moat simultaneously: pushing "act" (narration or aggressive SFT) raises injection-obedience because the objective has no notion of WHO instructed the action. Reframe any offline goal as Pareto-dominance, not "every metric at once". Only verifier-backed online RL can move both (section 7).
10. **Keep the traceback-to-S3 guard.** Posting the traceback to S3 before teardown is what made the v7 crash chain debuggable. The original "merge crash" was actually a chain: `DPOConfig(max_prompt_length=)` rejected by TRL 1.5.1 (build DPOConfig defensively), then the AEON7 default chat template "No user query found" (pin soundwave-qwen3.jinja + pre-filter), then a 17 KB onstart that 400'd (fetch the template from S3, do not embed).

## 6. Artifacts + data inventory

**Local GGUFs (this folder):** `soundwave-v7b-Q5_K_M.gguf` (chosen), `soundwave-v7-Q5_K_M.gguf` (v7-250 = SFT + 250-step DPO, under-repaired), `soundwave-v4-flagship-Q5_K_M.gguf` (rollback), `soundwave-v4-Q5_K_M.gguf` (retired).

**S3 `red-mod-26` (us-east-1, creds in `~/keys.txt`):**
- Root: every candidate GGUF, plus `soundwave-v4-flagship-Q5_K_M.gguf` and `LATEST.json` / `SOUNDWAVE-LATEST.md` (name the chosen model).
- `soundwave-v7-data/`: the v7b GGUF split (`v7b-part-00..04`, reassemble in order), `v7` SFT/DPO step adapters (`step2-adapter-350.tgz`, `step2-sft-adapter.tgz`), `probe_heldout_moat.jsonl`, `soundwave_sft_v4.jsonl`, `soundwave-qwen3.jinja`.
- `soundwave-v4-weights/`: the flagship FP16 safetensors (61 GB, for reconstructing an SFT-merged base for GRPO).
- `soundwave-v5-data/`, `soundwave-v52-data/`, `soundwave-v6-data/`: prior adapters, training sets (`sft.jsonl`, `dpo.jsonl`, `dpo_strict.jsonl`, `dpo_v52*.jsonl`), launch scripts, and the v6 `score_hardened.py` reward, all preserved for a future attempt.

**Training data the recipe uses:** `dpo_strict.jsonl` (9958 pairs, the injection-repair set), the SFT corpus (`soundwave_sft_v4.jsonl` + the v5 sft sets), `probe_heldout_moat.jsonl` (68-technique held-out moat), `moat_remapped_v53.jsonl`. ATT&CK id currency: `soundwave-mcp/grounding/deprecated_remap.json` (ATT&CK v19.1 renumbered the T1562 family into T1685-T1690).

## 7. The open frontier: the next lever

Offline SFT/DPO has a proven ceiling (the seesaw, landmine 9). The only lever the evidence says can move the moat AND close the injection gap at once is **online RL (GRPO) with a gated, programmatically-verifiable composite reward** that scores instruction PROVENANCE (who issued the imperative), not surface form. Soundwave has a natural symbolic verifier (ATT&CK-id exact-check + the tool_call parser + the injection detector), so no learned reward model is needed.

The v6 GRPO program is CLOSED NO-GO, but only because both cheap de-risk attempts reward-hacked a WEAK verifier (the training reward reused the held-out probe's danger regex; the model learned to dodge the regex, not to respect authority). The recipe was then HARDENED and is preserved for a future attempt:

- **`soundwave-mcp/SOUNDWAVE_VNEXT.md`** - the design: constrained multi-objective gated reward (hard injection-execute floor, counterfactual trusted/untrusted twins of the same imperative, semantic enactment detection not regex, anti-id-spray, KL anchor to the SFT-merged ref), online adversarial generation, difficulty-aware sampling, and falsifiable gates. Four-model + Pantheon-council validated.
- **`soundwave-mcp/SOUNDWAVE_GRPO_PLAN.md`** - the execution plan: single B200-180GB on vast.ai, stock `axolotlai/axolotl:main-py3.11-cu128-2.9.1` (bf16 LoRA, no bitsandbytes; the libnvJitLink symlink hack is a DEAD END), TRL 0.24 GRPOTrainer with vLLM colocate, the full hardened reward code, the reward-distribution variance audit, and the RFT-de-risk-first cost gate (~$5-9 before any GRPO spend).

Before any GRPO run, run the RFT de-risk pilot first and honor its quantitative go/no-go (moat +4/30 on the hard tail, injection <= 1/12 on a HELD-OUT family, act-rate [0.78, 0.88], real accepted-vs-rejected separation). If RFT cannot clear that for under $10, GRPO will not either: fix the reward before paying for RL.

**Zero-retrain hardening you can stack today:** a DataFilter-style input-sanitization shim on the role:tool channel (a small proxy that strips or neutralizes imperative commands in tool-result content before the model sees it), mirroring `soundwave-mcp/grounding/serve_grounded.py`. Test-time stripping drives injection ASR toward zero model-agnostically and stacks with any future RL as defense-in-depth.

## 8. Infra, accounts, rules

- **GPU:** single RTX 5090 (32 GB), shared with brutal-mcp (heretic-v2 on :7869). soundwave-mcp serves on :8092 + a grounding shim on :8097; `soundwave_load` / `soundwave_unload` do the VRAM-aware swap (records and restores the displaced brutal serve). Only one ~19-23 GB model loads at a time.
- **Serving build:** `C:\Projects\llama-cpp\b9415\llama-server.exe` (required for the qwen3_5 / Gated-DeltaNet arch; the older `bin/` build cannot serve v7/v7b).
- **Accounts:** this is all personal (`ademczuk`), not the texterous business account. Run `gh api user --jq .login` before any account-sensitive op. `ademczuk/soundwave-mcp` is the private Soundwave MCP repo; the git remote on this weights folder is the private Decepticon fork (`ademczuk/Soundwave`, upstream `PurpleAILAB/Decepticon`), so a `git push` here pushes Decepticon code, not weights. The weights live in S3, never in git.
- **Secrets:** AWS + other creds live ONLY in `~/keys.txt`. NEVER inline a token into a commit, a file, a remote URL, or a chat-posted file. Use presigned S3 URLs so AWS creds never leave the machine.
- **Rented GPUs:** vast.ai. Do not destroy pre-existing orphan instances you did not create. Price-cap long runs; the v7 overnight hit 5+ dud hosts.
- **Commits:** no AI co-author trailers; HEREDOC commit messages; marker-clean external text (no em-dashes, arrows, or the banned words; run the literal regex scan before posting). Confirm before pushing weights or opening any public artifact.

## 9. Pointers

- Promotion record: `soundwave-mcp/PROMOTION-v7b-canary.md`. Serving details: `soundwave-mcp/README.md`.
- Future-training recipes: `soundwave-mcp/SOUNDWAVE_VNEXT.md`, `soundwave-mcp/SOUNDWAVE_GRPO_PLAN.md`, `soundwave-mcp/UNIFIED-RETRAIN-PLAN.md`, `soundwave-mcp/PAID-GATE-PLAN.md`.
- Validation: the `/soundwave-validate` skill (the 6-check battery, the role:tool injection rule).
- Karpathy wiki (`02-Knowledge/Wiki/Harness-Insights/`): `Verify-the-Instrument-Before-the-Verdict`, `Cheap-Rejection-Sampling-Derisk-Gates-Expensive-Online-RL`, `Plateaued-Offline-Finetune-Lever-is-Gated-Verifiable-Online-RL`, `When-Finetune-Upgrades-Plateau-Ship-a-Serving-Layer`, `Gate-Adapter-Coverage-By-Module-Name-Not-Param-Count`, `Faster-GPU-Same-Step-Time-Means-Not-Compute-Bound`, `Presigned-S3-PUT-403-Force-s3v4-And-Test-URLs-Before-Firing`, `Rented-GPU-Fine-Tune-Pipeline-Playbook`, `Working-Folder-Git-Is-Foreign-Fork-Verify-And-Exclude-Repo-Locally` (why this folder's git is a Decepticon fork and how the weights stay out of it; also versioned in `ademczuk/llm-wiki`).
- Auto-memory (this machine): `project_soundwave_v7b_canary_promoted`, `project_soundwave_unified_retrain_gate`, `project_soundwave_canonical_config_surfaces`, `reference_s3_redteam_model_storage`.
- Project session memory (`~/.claude/projects/C--Projects--Jobs-Collaborations-Andrew-Soundwave/memory/`): `soundwave-repo-vs-weights-identity` (this folder's git is the Decepticon fork, weights live in S3, `soundwave-mcp` is the real repo) and `fix-paired-manifests-together` (when you correct a fact, fix both `SOUNDWAVE-LATEST.md` and its `LATEST.json` twin).
