---
name: evm-hidden-funds-recovery
description: >-
  Discovers, verifies, and guides users through recovering unclaimed, stuck, or forgotten
  cryptocurrency funds (native ETH/gas tokens, ERC-20s, LP positions, staking vaults,
  failed auction commitments, NFT bids, and escrow pull-payments) across Ethereum and
  EVM chains. Use this skill whenever a user asks to find missing/hidden/stuck crypto
  funds, audit a wallet or ENS name for unclaimed balances or old bids, or generate
  exact contract interaction parameters to withdraw funds via Etherscan or a wallet.
---

# EVM Hidden Funds Discovery & Recovery Skill

This skill provides a deterministic, model-agnostic workflow for auditing an Ethereum/EVM wallet across its complete historical footprint to uncover reclaimable value that static "known-contract" scanners (such as `hiddenfunds.xyz` or standard portfolio trackers) miss.

> **Path Resolution Note:** All file paths in this skill (`./scripts/...`, `./references/...`) are relative to the directory containing this `SKILL.md` file. Resolve them relative to this skill's folder before executing commands.

---

## Why Static Scanners Miss Funds (Core Principles)

Static portfolio and recovery scanners only query `balanceOf(user)` or `pendingWithdrawals(user)` against a hardcoded list of ~50 popular contracts. They systematically miss four high-value categories:

1. **Cloned / Factory Contracts (EIP-1167 & EIP-1967 Proxies):** Individual auction deployments (e.g., SushiSwap MISO Dutch/Batch auctions), PartyBid instances, Sudoswap LP pairs, 0xSplits clones, or custom raffles deployed per-event.
2. **Keyed Storage Mappings (`mapping(bytes5 => Request)` or `mapping(uint256 => Bid)`):** Legacy contracts like MoonCatRescue (`adoptionRequests[catId]`), CryptoPunks (`punkBids[punkIndex]`), or NFT marketplaces where deposits are keyed by an asset/auction ID rather than `msg.sender`.
3. **Deceptive Function Naming & Multi-Step State Transitions:**
   - Failed auction ETH refunds hidden inside functions named `withdrawTokens(address)` (MISO).
   - Direct ETH transfers triggered inside `cancelAdoptionRequest(bytes5)` (MoonCatRescue).
   - Unfinalized group bids where `claim(address)` reverts until someone calls `expire()` or `finalize()` first (PartyBid).
4. **Un-tokenized Staking, MasterChef Vaults & NFT Escrows:** Contracts where users deposited ERC-20, LP, WETH, or ERC-721 assets without receiving an ERC-20 receipt token (`userInfo(pid, user)` or `stakes(user)` instead of `balanceOf(user)`).

---

## Execution Workflow (5 Phases)

Follow these five phases sequentially. **Do not** improvise fragile one-off network scripts that open dozens of sequential connections or hit explorer rate limits. Always use the bundled zero-dependency Python 3 tools in `./scripts/`.

### Phase 1: Target Resolution & Automated Historical Delta Scan

Run [`./scripts/scan_evm_funds.py`](./scripts/scan_evm_funds.py) against the target wallet address or `.eth` ENS name:

```bash
python ./scripts/scan_evm_funds.py --address <0xAddress_or_ENS> --chains Ethereum,Arbitrum,Optimism,Base,BSC,Polygon --output-dir ./scan_output
```

**What `scan_evm_funds.py` does automatically:**
- **ENS Resolution:** Resolves `.eth` names to their canonical `0x` address.
- **Batched Multi-Chain Triage:** Sends a single batched JSON-RPC request per chain across 11 EVM networks (Ethereum, Arbitrum, Optimism, Base, BSC, Polygon, Avalanche, Fantom, Gnosis, Zora, Blast) to check native balances, transaction counts (`nonce`), and major wrapped/stable/governance tokens.
- **10,000-Tx Cap Bypass:** Sweeps both `sort=asc` and `sort=desc` in parallel across Etherscan-compatible APIs (`txlist`, `txlistinternal`, `tokentx`, `tokennfttx`) so wallets with $>10,000$ transactions have zero blind spots.
- **Proxy Unwrapping:** Automatically detects EIP-1167 minimal proxy clones and EIP-1967 proxy storage slots on candidate contracts.
- **UTF-8 Reporting:** Outputs `./scan_output/candidates_report.md` and `./scan_output/scan_results.json`.

---

### Phase 2: Candidate Triage (The 4 High-Signal Buckets)

Read `./scan_output/candidates_report.md` and evaluate every flagged contract across four buckets:

1. **Bucket A — Positive Net ETH Outflow to Live ETH-Holding Contracts:**
   $$\text{Net ETH}(C) = \sum \text{ETH Sent}(U \to C) - \sum \text{Internal ETH Returned}(C \to U) > 0$$
   Filtered strictly to contracts where **live on-chain `eth_getBalance(C) > 0`** and excluding pure swaps/mints.
2. **Bucket B — Unwithdrawn ERC-20 / LP / WETH Custody (`tokentx` Delta):**
   Contracts where the user sent ERC-20 tokens (especially `WETH`, `USDC`, `DAI`, or LP tokens) in non-swap transactions (`stake`, `deposit`, `lock`, `commit`, `bid`, `contribute`), received less back than sent, and **`Token.balanceOf(C) > 0` today**.
3. **Bucket C — Unwithdrawn NFT Custody (`tokennfttx` Delta):**
   Vaults, staking contracts, or fractionalizers where ERC-721/ERC-1155 tokens were sent via `stake`, `depositERC721`, or `multi721Deposit` and never returned.
4. **Bucket D — Keyed Legacy Contracts & Event Log Audit:**
   Check `./scan_output/candidates_report.md` (and consult [`./references/protocol-traps-and-patterns.md`](./references/protocol-traps-and-patterns.md)) for keyed contracts (MoonCatRescue, CryptoPunks, Old ENS Registrar Deeds, Zora/SuperRare/Foundation/AsyncArt escrows).

---

### Phase 3: Contract Inspection & Protocol Trap Lookup

For each candidate contract identified in Phase 2:
1. Consult [`./references/protocol-traps-and-patterns.md`](./references/protocol-traps-and-patterns.md) to check if the contract matches a known deceptive pattern (e.g., MISO `withdrawTokens`, MoonCat `cancelAdoptionRequest`, PartyBid `expire` $\to$ `claim`, MasterChef `userInfo`).
2. Inspect the contract's verified source code and state getters using [`./scripts/verify_recovery.py`](./scripts/verify_recovery.py) in `--inspect` mode:
   ```bash
   python ./scripts/verify_recovery.py --chain Ethereum --contract <0xContract> --user <0xUserAddress> --inspect
   ```
   This automatically unwraps EIP-1167/EIP-1967 proxies, fetches the implementation contract's verified source/ABI, and probes common user-balance getters (`commitments`, `balances`, `pendingWithdrawals`, `deposits`, `claimed`, `userInfo`).

---

### Phase 4: Mandatory On-Chain Dry-Run Verification (Zero False Positives)

**NEVER** report claimable funds to a user based solely on historical transactions. You **MUST** verify that the withdrawal/refund transaction succeeds at the `latest` block using [`./scripts/verify_recovery.py`](./scripts/verify_recovery.py):

```bash
python ./scripts/verify_recovery.py \
  --chain Ethereum \
  --contract <0xContract> \
  --user <0xUserAddress> \
  --sig "withdrawTokens(address)" \
  --args "<0xUserAddress>"
```

**Verification Checklist:**
1. **`eth_call` Simulation:** Must succeed without revert. If it reverts with a state precondition (e.g., `"Party::claim: party not finalized"`), test the prerequisite transition function (e.g., `--sig "expire()"`).
2. **`eth_estimateGas` Check:** Confirm gas cost and compare against the USD value of the recovered asset.
3. **`eth_createAccessList` Check:** Confirm the call touches the expected storage slots or token contracts.

---

### Phase 5: User Recovery Guidance

Present verified recoveries clearly, ordered from highest net USD value to lowest:

1. **Executive Summary:** State the exact recoverable amount (in token + USD), the contract name/type, and the original deposit transaction hash + date.
2. **Why It Was Hidden:** Briefly explain the mechanic that trapped the funds (e.g., failed reserve auction requiring `withdrawTokens()`, active `bytes5` offer in `adoptionRequests`, unfinalized PartyBid).
3. **Step-by-Step Etherscan Instructions:**
   - Direct URL to `#writeContract` or `#writeProxyContract`.
   - If the contract is an unflagged proxy on Etherscan, include the one-click proxy linker URL: `https://etherscan.io/proxyContractChecker?a=<ContractAddress>`.
   - Exact function name and copy-pasteable parameter values.
   - Clarify whether the function transfers funds **immediately** in the same transaction or credits `pendingWithdrawals` requiring a follow-up `withdraw()` call.
4. **Raw Calldata Fallback:** Always provide the `to` address, `0 ETH` value, and exact hex calldata (`0x...`) from `verify_recovery.py` so the user can execute directly from Rabby, MetaMask, or Frame if desired.
