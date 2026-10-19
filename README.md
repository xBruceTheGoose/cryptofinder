# EVM Hidden Funds & Unclaimed Asset Recovery — Universal Agent Skill

A portable, zero-dependency, model-agnostic skill that equips any AI coding or research agent (**Claude Code**, **Hermes**, **OpenAI Codex**, **Gemini / Antigravity**, **Cursor**, **Windsurf**, or web chat agents) to perform deep on-chain forensic audits and recover forgotten ETH, tokens, NFT bids, unfinalized cross-chain bridge exits, and failed auction commitments that static portfolio scanners (`hiddenfunds.xyz`, Debank, Zapper, Zerion) miss.

---

## Why Static Scanners Miss Funds (And How This Skill Finds Them)

Most recovery tools check a hardcoded list of popular contracts against a user's wallet address. They systematically miss:
1. **EIP-1167 Minimal Proxy Clones:** Crowdsales, Dutch auctions (e.g., SushiSwap MISO), and group-buy pools (e.g., PartyBid) deploy a brand-new minimal proxy contract for every single auction.
2. **Asset-Keyed Escrows (Pre-ERC-721):** Early contracts like **MoonCatRescue** (`adoptionRequests[bytes5 catId]`) and **CryptoPunks** (`punkBids[uint256 punkIndex]`) index ETH deposits by the *Asset ID* rather than the bidder's wallet address.
3. **Deceptive Recovery Function Names:** In contracts like MISO DutchAuctions, when an auction fails (`auctionSuccessful() == false`), calling `withdrawTokens()` actually refunds the user's **native ETH** commitment.
4. **Un-Tokenized Staking & MasterChef Pools:** Contracts that track balances inside `userInfo(uint256 pid, address user)` without minting an ERC-20 receipt token.
5. **Unfinalized Cross-Chain & Bridged NFT Escrows:** Assets burned or withdrawn on a child chain (e.g. `withdraw(tokenId)` on Polygon) whose cryptographic Merkle/RLP proof was never submitted to Ethereum L1 via `RootChainManager.exit(bytes inputData)`. The original L1 asset remains trapped in the L1 predicate escrow forever while appearing completely gone from the child chain.

Instead of relying only on a static contract list, this skill reconstructs the wallet's **historical net-value flow** across chains (`ETH sent in > ETH returned`), automatically unwraps EIP-1167 / EIP-1967 proxies, inspects live contract storage at `"latest"`, and **simulates the recovery transaction** via `eth_call` + `eth_estimateGas` before presenting copy-paste Etherscan recovery instructions.

---

## Real-World Battle-Tested Recoveries

This skill has directly recovered:
* **0.2 ETH (~$500)** trapped in the original 2017 **MoonCatRescue** smart contract via `cancelAdoptionRequest(bytes5)`.
* **0.312 ETH (~$781)** locked in a failed 2021 **SushiSwap MISO DutchAuction** via `withdrawTokens()`.
* **CryptoSkulls #8900 (~0.05+ ETH)** trapped in Polygon's **ERC721PredicateProxy** on Ethereum Mainnet since October 2023, recovered by generating the 10-field RLP exit proof and calling `RootChainManagerProxy.exit(bytes)`.
* **5 Unclaimed Staked NFTs** across Optimism (`DRGNTRNR #146`), Ethereum (`MAG #100906`, `AMP #790`, `KODA #7116000`), and Avalanche (`Premium #8`).

---

## Package Structure

```text
evm-hidden-funds-skill/
├── SKILL.md                                  # Standard Agent Skill definition (YAML frontmatter + 5-phase workflow)
├── PROMPT_SINGLE_FILE.md                     # All-in-one single-file edition for web chat / Claude Projects / custom instructions
├── README.md                                 # Cross-framework installation & usage guide
├── scripts/
│   ├── scan_evm_funds.py                     # Zero-dependency multi-chain balance sweep + tx history anomaly scanner
│   └── verify_recovery.py                    # Zero-dependency state inspector, proxy detector, & tx simulator
└── references/
    └── protocol-traps-and-patterns.md        # Deep-dive reference of selectors, ABIs, storage layouts, & traps
```

* **Zero external Python dependencies:** Both CLI scripts use **only the Python 3 standard library** (`urllib.request`, `json`, `argparse`) and free, keyless public RPCs and block explorer APIs (Blockscout, Routescan, Sourcify, PublicNode).
* **100% Read-Only & Safe:** Never asks for or accepts private keys or seed phrases.

---

## Quick Installation by Agent Framework

### 1. Claude Code (`claude`)
Copy this folder into your global or project-level `.claude/skills/` directory:
```bash
mkdir -p ~/.claude/skills
cp -r evm-hidden-funds-skill ~/.claude/skills/evm-hidden-funds-recovery
```
*(Claude Code automatically discovers `SKILL.md` and invokes `./scripts/scan_evm_funds.py` and `./scripts/verify_recovery.py` when you ask to scan a wallet for hidden or unclaimed funds.)*

### 2. Hermes Agent (`hermes`)
Drop the skill directory into your Hermes skills folder or register it in your agent config:
```bash
mkdir -p ~/.hermes/skills
cp -r evm-hidden-funds-skill ~/.hermes/skills/evm-hidden-funds-recovery
```
*(Or, if using a single-file Hermes prompt slot, load `PROMPT_SINGLE_FILE.md` directly.)*

### 3. OpenAI Codex CLI (`codex`)
Copy the folder into `.codex/skills/` or append `SKILL.md` to your workspace `AGENTS.md`:
```bash
mkdir -p ~/.codex/skills
cp -r evm-hidden-funds-skill ~/.codex/skills/evm-hidden-funds-recovery
# Or for repo-level AGENTS.md:
cat evm-hidden-funds-skill/SKILL.md >> AGENTS.md
```

### 4. Gemini CLI / Google Antigravity
Copy the folder into your global skills directory:
```bash
cp -r evm-hidden-funds-skill ~/.gemini/config/skills/evm-hidden-funds-recovery
```

### 5. Cursor / Windsurf
Copy `SKILL.md` (or `PROMPT_SINGLE_FILE.md`) into `.cursor/rules/evm-hidden-funds-recovery.mdc` and place the `scripts/` folder in your workspace root.

### 6. Web Chat UIs (Claude Projects, ChatGPT Custom GPTs, Gemini Gems)
Upload [`PROMPT_SINGLE_FILE.md`](./PROMPT_SINGLE_FILE.md) and [`references/protocol-traps-and-patterns.md`](./references/protocol-traps-and-patterns.md) directly into the project knowledge base or system instructions.

---

## Standalone CLI Usage (Human or Agent)

You can also run the bundled forensic scripts directly from any terminal with Python 3.8+:

### 1. Scan an Address or ENS Name
```bash
# Fast 11-chain balance sweep + Mainnet historical anomaly scan + legacy bid scan (MoonCats, CryptoPunks)
python3 scripts/scan_evm_funds.py brucethegoose.eth

# Scan transaction history anomalies across multiple L2s simultaneously
python3 scripts/scan_evm_funds.py 0xYourAddress --chains ethereum,arbitrum,optimism,base,polygon --output-dir ./scan_results

# Export structured JSON report for downstream agent analysis
python3 scripts/scan_evm_funds.py brucethegoose.eth --output-dir ./audit_out
```

### 2. Inspect a Candidate Contract & Simulate Recovery
```bash
# Auto-detect EIP-1167/1967 proxies, fetch ABI, and probe common refund/escrow getters at "latest"
python3 scripts/verify_recovery.py \
  --wallet 0x18C6A47AcA1c6a237e53eD2fc3a8fB392c97169b \
  --contract 0x6727e26a7a9a5f3f1485f64a1379e73652c78355 \
  --inspect

# Dry-run a recovery call (eth_call + eth_estimateGas + eth_createAccessList) and generate Etherscan guide
python3 scripts/verify_recovery.py \
  --wallet 0x18C6A47AcA1c6a237e53eD2fc3a8fB392c97169b \
  --contract 0x6727e26a7a9a5f3f1485f64a1379e73652c78355 \
  --sig "withdrawTokens(address)" \
  --args "0x18C6A47AcA1c6a237e53eD2fc3a8fB392c97169b" \
  --guide

# Simulate arbitrary raw calldata (e.g. Polygon RootChainManager.exit with Merkle proof)
python3 scripts/verify_recovery.py \
  --wallet 0x18C6A47AcA1c6a237e53eD2fc3a8fB392c97169b \
  --contract 0xa0c68c638235ee32657e8f720a23cec1bfc77c77 \
  --calldata 0x3805550f... \
  --guide
```
