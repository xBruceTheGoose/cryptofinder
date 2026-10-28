---
name: evm-hidden-funds-recovery
description: >-
  Discovers, verifies, and guides users through recovering unclaimed, stuck, or forgotten
  cryptocurrency funds (native ETH/gas tokens, ERC-20s, LP positions, staking vaults,
  failed auction commitments, NFT bids, unfinalized cross-chain bridge exits, and escrow pull-payments)
  across Ethereum and EVM chains. Use this skill whenever a user asks to find missing/hidden/stuck crypto
  funds, audit a wallet or ENS name for unclaimed balances or old bids, or generate
  exact contract interaction parameters to withdraw funds via Etherscan or a wallet.
---

# EVM Hidden Funds Discovery & Recovery Skill

This skill provides a deterministic, model-agnostic workflow for auditing an Ethereum/EVM wallet across its complete historical footprint to uncover reclaimable value that static "known-contract" scanners (such as `hiddenfunds.xyz` or standard portfolio trackers) miss.

> **Path Resolution Note:** All file paths in this skill (`./scripts/...`, `./references/...`) are relative to the directory containing this `SKILL.md` file. Resolve them relative to this skill's folder before executing commands.

---

## Why Static Scanners Miss Funds (Core Principles)

Static portfolio and recovery scanners only query `balanceOf(user)` or `pendingWithdrawals(user)` against a hardcoded list of ~50 popular contracts. They systematically miss five high-value categories:

1. **Cloned / Factory Contracts (EIP-1167 & EIP-1967 Proxies):** Individual auction deployments (e.g., SushiSwap MISO Dutch/Batch auctions), PartyBid instances, Sudoswap LP pairs, 0xSplits clones, or custom raffles deployed per-event.
2. **Keyed Storage Mappings (`mapping(bytes5 => Request)` or `mapping(uint256 => Bid)`):** Legacy contracts like MoonCatRescue (`adoptionRequests[catId]`), CryptoPunks (`punkBids[punkIndex]`), or NFT marketplaces where deposits are keyed by an asset/auction ID rather than `msg.sender`.
3. **Deceptive Function Naming & Multi-Step State Transitions:**
   - Failed auction ETH refunds hidden inside functions named `withdrawTokens(address)` (MISO).
   - Direct ETH transfers triggered inside `cancelAdoptionRequest(bytes5)` (MoonCatRescue).
   - Unfinalized group bids where `claim(address)` reverts until someone calls `expire()` or `finalize()` first (PartyBid).
4. **Un-tokenized Staking, MasterChef Vaults & NFT Escrows:** Contracts where users deposited ERC-20, LP, WETH, or ERC-721 assets without receiving an ERC-20 receipt token (`userInfo(pid, user)` or `stakes(user)` instead of `balanceOf(user)`).
5. **Unfinalized Cross-Chain & L2 Bridge Exits (Polygon PoS Bridge, Arbitrum Outbox, OP Stack Portal):**
   - Assets burned/withdrawn on a child chain (e.g. `withdraw(tokenId)` on Polygon) whose cryptographic Merkle/RLP proof was never submitted to Ethereum L1 via `RootChainManager.exit(bytes inputData)`. The original L1 asset remains trapped in the L1 predicate escrow forever while appearing completely gone from the child chain.

---

## Execution Workflow (5 Phases)

Follow these five phases sequentially. **Do not** improvise fragile one-off network scripts that open dozens of sequential connections or hit explorer rate limits. Always use the bundled zero-dependency Python 3 tools in `./scripts/`.

### Phase 1: Target Resolution & Automated Historical Delta Scan

Run [`./scripts/scan_evm_funds.py`](./scripts/scan_evm_funds.py) against the target wallet address or `.eth` ENS name:

```bash
python ./scripts/scan_evm_funds.py --address <0xAddress_or_ENS> --chains Ethereum,Arbitrum,Optimism,Base,BSC,Polygon --output-dir ./scan_output
```

**What `scan_evm_funds.py` does automatically:**
- **ENS Resolution:** Resolves `.eth` names directly on-chain via Ethereum Mainnet ENS Registry (`0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e`).
- **Batched Multi-Chain & Legacy Keyed Triage:** Sends batched JSON-RPC requests per chain across 11 EVM networks (Ethereum, Arbitrum, Optimism, Base, BSC, Polygon, Avalanche, Fantom, Gnosis, Zora, Blast) and automatically checks MoonCatRescue (`adoptionRequests` + `pendingWithdrawals`), CryptoPunks, Old ENS Interim Registrar Deeds (`2017–2019`), 0xSplits `SplitMain`, and pre-ERC721 CryptoKitties Core.
- **Cloudflare & 10,000-Tx Cap Bypass:** Uses native `curl` fallback and sweeps both `sort=asc` and `sort=desc` in parallel across explorer APIs (`txlist`, `txlistinternal`, `tokentx`, `tokennfttx`) so wallets with $>10,000$ transactions have zero blind spots.
- **Phishing & Airdrop Spam Filtering:** Automatically strips unsolicited phishing ERC-20 spam (URL symbols, Telegram links, Cyrillic homoglyphs) so reports contain only legitimate tokens.
- **Automated Candidate State Probing & Proxy Unwrapping:** Automatically detects EIP-1167 and EIP-1967 proxies, resolves on-chain `name()`/`symbol()`/`decimals()`, and probes `balanceOf(user)`, `pendingWithdrawals(user)`, `balances(user)`, `commitments(user)`, and `checkDepositorBalance()` on every Bucket A candidate contract—distinguishing 18-decimal token dust from integer NFT holdings.
- **Live NFT Custody & Child-Chain Bridge Burn Detection:** Verifies live `ownerOf(tokenId)` on escrowed NFTs (Bucket C) and detects child-chain `withdraw(tokenId)` / bridge burns to `0x000...000` (Bucket E).
- **UTF-8 Reporting:** Outputs `./scan_output/candidates_report.md` and `./scan_output/scan_results.json`.

---

### Phase 2: Candidate Triage (The 5 High-Signal Buckets)

Read `./scan_output/candidates_report.md` and evaluate every flagged contract across five buckets:

1. **Bucket A — Positive Net ETH Outflow to Live ETH-Holding Contracts:**
   $$\text{Net ETH}(C) = \sum \text{ETH Sent}(U \to C) - \sum \text{Internal ETH Returned}(C \to U) > 0$$
   Filtered strictly to contracts where **live on-chain `eth_getBalance(C) > 0`** and excluding pure swaps/mints.
2. **Bucket B — Unwithdrawn ERC-20 / LP / WETH Custody (`tokentx` Delta):**
   Contracts where the user sent ERC-20 tokens (especially `WETH`, `USDC`, `DAI`, or LP tokens) in non-swap transactions (`stake`, `deposit`, `lock`, `commit`, `bid`, `contribute`), received less back than sent, and **`Token.balanceOf(C) > 0` today**.
3. **Bucket C — Unwithdrawn NFT Custody (`tokennfttx` Delta):**
   Vaults, staking contracts, or fractionalizers where ERC-721/ERC-1155 tokens were sent via `stake`, `depositERC721`, or `multi721Deposit` and never returned.
4. **Bucket D — Keyed Legacy Contracts & Event Log Audit:**
   Check `./scan_output/candidates_report.md` (and consult [`./references/protocol-traps-and-patterns.md`](./references/protocol-traps-and-patterns.md)) for keyed contracts (MoonCatRescue, CryptoPunks, Old ENS Registrar Deeds, Zora/SuperRare/Foundation/AsyncArt escrows).
5. **Bucket E — Unfinalized Cross-Chain & Bridged Escrow:**
   Child-chain burns (`withdraw(tokenId)` or transfers to `0x000...000` on Polygon, Arbitrum, Optimism) where the L1 release proof was never submitted to L1 bridges (e.g. Polygon `RootChainManager` `0xA0c68C638235ee32657e8f720a23ceC1bFc77C77`, Arbitrum `Outbox`, OP Stack `OptimismPortal`).

---

### Phase 3: Contract Inspection & Protocol Trap Lookup

For each candidate contract identified in Phase 2:
1. Consult [`./references/protocol-traps-and-patterns.md`](./references/protocol-traps-and-patterns.md) to check if the contract matches a known deceptive pattern (e.g., MISO `withdrawTokens`, MoonCat `cancelAdoptionRequest`, PartyBid `expire` $\to$ `claim`, MasterChef `userInfo`, Polygon PoS Bridge `exit`).
2. Inspect the contract's verified source code, ABI, or unverified bytecode selectors using [`./scripts/verify_recovery.py`](./scripts/verify_recovery.py) in `--inspect` mode:
   ```bash
   python ./scripts/verify_recovery.py --chain Ethereum --contract <0xContract> --user <0xUserAddress> --inspect
   ```
   This automatically:
   - Unwraps EIP-1167/EIP-1967 proxies and fetches the verified contract name + categorized Read/Recovery Write functions from Routescan/Blockscout.
   - **Decompiles unverified contracts automatically** by extracting `PUSH4` 4-byte selectors from bytecode and resolving human-readable signatures via OpenChain.
   - Probes common user-balance getters (`commitments`, `balances`, `pendingWithdrawals`, `deposits`, `claimed`, `checkDepositorBalance`, `getETHBalance`, and `userInfo(0..3, user)`).

---

### Phase 4: Mandatory On-Chain Dry-Run Verification (Zero False Positives)

**NEVER** report claimable funds to a user based solely on historical transactions. You **MUST** verify that the withdrawal/refund transaction succeeds at the `latest` block using [`./scripts/verify_recovery.py`](./scripts/verify_recovery.py):

```bash
# Standard contract recovery simulation:
python ./scripts/verify_recovery.py \
  --chain Ethereum \
  --contract <0xContract> \
  --user <0xUserAddress> \
  --sig "withdrawTokens(address)" \
  --args "<0xUserAddress>"

# Automated Polygon PoS Bridge exit proof generation & L1 simulation:
python ./scripts/verify_recovery.py \
  --user <0xUserAddress> \
  --polygon-burn-tx <0xPolygonBurnTxHash>

# Automated Gnosis -> Ethereum AMB cross-chain relay & L1 NFT check:
python ./scripts/verify_recovery.py \
  --user <0xUserAddress> \
  --amb-tx <0xGnosisRelayTxHash>
```

**Verification Checklist:**
1. **`eth_call` Simulation:** Must succeed without revert. If it reverts with a state precondition (e.g., `"Party::claim: party not finalized"`), test the prerequisite transition function (e.g., `--sig "expire()"`).
2. **`eth_estimateGas` Check:** Confirm gas cost and compare against the USD value of the recovered asset.
3. **Bridge Proof Validation:** For cross-chain exits (e.g., Polygon `RootChainManager.exit`), verify that the 10-field RLP payload is generated via the proof generator API and simulates successfully on Ethereum L1 without reverting (`jsonrpc: "2.0", result: "0x"`).

---

### Phase 5: User Recovery Guidance

Present verified recoveries clearly, ordered from highest net USD value to lowest:

1. **Executive Summary:** State the exact recoverable amount (in token + USD), the contract name/type, and the original deposit transaction hash + date.
2. **Why It Was Hidden:** Briefly explain the mechanic that trapped the funds (e.g., failed reserve auction requiring `withdrawTokens()`, active `bytes5` offer in `adoptionRequests`, unfinalized PartyBid, un-exited Polygon child burn).
3. **Step-by-Step Instructions:**
   - Direct URL to `#writeContract` or `#writeProxyContract` on Etherscan, Snowtrace, Polygonscan, or Arbiscan.
   - For bridged assets, provide both the official Portal Bridge UI link (e.g. `https://portal.polygon.technology/bridge`) and the direct L1 contract call.
   - If the contract is an unflagged proxy on Etherscan, include the one-click proxy linker URL: `https://etherscan.io/proxyContractChecker?a=<ContractAddress>`.
   - Exact function name and copy-pasteable parameter values.
   - Clarify whether the function transfers funds **immediately** in the same transaction or credits `pendingWithdrawals` requiring a follow-up `withdraw()` call.
4. **Raw Calldata Fallback:** Always provide the `to` address, `0 ETH` value, and exact hex calldata (`0x...`) from `verify_recovery.py` so the user can execute directly from Rabby, MetaMask, or Frame if desired.
