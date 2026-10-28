# Protocol Traps, Misleading Function Names, and Recovery Patterns

This reference catalogues smart contract mechanics where user funds become hidden due to counter-intuitive naming, proxy indirection, keyed storage, multi-step state transitions, or un-exited cross-chain bridge proofs.

---

## 1. Deceptive Function Naming & Multi-Step Refunds

### A. SushiSwap MISO Auctions (`DutchAuction`, `BatchAuction`, `Crowdsale`)
* **Trap:** Users call `commitEth(address _beneficiary, bool agreed)` (`0x29762960`) or `commitTokens(uint256 _amount, bool agreed)` on an individual EIP-1167 minimal proxy auction contract. If the auction fails to meet its reserve (`auctionSuccessful() == false`), ETH is **not** automatically returned. Worse, the function to reclaim committed ETH is named **`withdrawTokens()`** (`0x8d8f2adb`) or **`withdrawTokens(address payable beneficiary)`** (`0x49df728c`).
* **How to Verify:**
  1. Check `commitments(address)` (`0x839df945`) $> 0$ and `claimed(address)` (`0xc884ef83`) $== 0$.
  2. Check `auctionSuccessful()` (`0x321c97b2`) $== \text{false}$ and `eth_getBalance(contract) >= commitments(user)`.
  3. Unwrap EIP-1167 bytecode (`363d3d373d3d3d363d73<impl>5af4...`) to verify the implementation (e.g., `0x1c5771e96c9d5524fb6e606f5b356d08c40eb194`).
  4. Simulate `withdrawTokens(user)` via `eth_call` and `eth_estimateGas`.

### B. Original MoonCatRescue (`0x60cd862c9c687a9de49aecdc3a99b74a4fc54ab6`)
* **Trap:** Pre-ERC721 contract (August 2017). Users lock ETH via `makeAdoptionRequest(bytes5 catId)` (`0xe65bbceb`), which is keyed by the 5-byte `catId`, **not** by the user's address (`adoptionRequests(bytes5)` returns `(bool exists, bytes5 catId, address requester, uint256 price)`).
* **Two Separate Refund Paths:**
  1. **Active Request (never accepted or outbid):** Stored in `adoptionRequests(bytes5 catId)` (`0xbec6bc67`). To recover, the user calls **`cancelAdoptionRequest(bytes5 catId)`** (`0x9d8df6dd`), which executes `msg.sender.transfer(price)` **immediately in the same transaction** (no separate `withdraw()` needed).
  2. **Outbid Request:** Moved into `pendingWithdrawals(address)` (`0xf3f43703`). To recover, the user calls **`withdraw()`** (`0x3ccfd60b`).
* **How to Find All `catId`s for a Wallet:**
  Query event logs on `0x60cd862c9c687a9de49aecdc3a99b74a4fc54ab6` where `topic0 = 0x0beedbd4ef5e50660fe5cf7b1274e5d826c6e496020c760b9509e1f21f696230` (`AdoptionRequested`) and `topic2 = 0x000000000000000000000000<user_address>`. Extract `topic1[:12]` (`bytes5 catId`).

### C. PartyBid V1 / PartyDAO (`contribute` $\to$ `expire` $\to$ `claim`)
* **Trap:** Users call `contribute()` (`0xd7bb99ba`) with ETH on a per-auction PartyBid proxy. After the underlying NFT auction ends:
  - If the Party lost (or won with excess ETH), contributors must call **`claim(address _contributor)`** (`0x1e83409a`) to recover their ETH and/or fractional tokens.
  - **Precondition Trap:** If *nobody* ever finalized the lost PartyBid, calling `claim(address)` reverts with `"Party::claim: party not finalized"`. Someone must first call **`expire()`** (`0x79599f96`), after which `claim(address)` succeeds and refunds the ETH.

### D. CryptoPunks Market (`0xb47e3cd837dDF8e4c57F05d70Ab865de6e193BBB`)
* **Two Separate Refund Paths:**
  1. **Outbid / Sale Proceeds:** Stored in `pendingWithdrawals(address)` (`0xf3f43703`), withdrawn via `withdraw()` (`0x3ccfd60b`).
  2. **Active Bid Still Open on a Punk:** Stored in `punkBids(uint256 punkIndex)` (`0x44268632`), which returns `(bool hasBid, uint256 punkIndex, address bidder, uint256 value)`. Find `punkIndex` from historical `enterBidForPunk(uint256)` (`0x091dbfd2`) calls or `PunkBidEntered` logs (`topic2 = user`), and recover via **`withdrawBidForPunk(uint256 punkIndex)`** (`0x29165b75`).

### E. KnownOrigin `ArtistAcceptingBidsV2` (`0x848b0ea643e5a352d78e2c0c12a2dd8c96fec639`)
* **Trap:** Collectors place ETH bids via `placeBid(uint256 _editionNumber)` (`0x9979ef45`). If an edition sells out before the artist accepts the bid, the auction stops and **does not auto-refund**—the bidder must manually call `withdrawBid(uint256 _editionNumber)` (`0x217fe6c6`).
* **How to Verify:**
  1. Extract `_editionNumber` from the 32-byte calldata argument of `placeBid(uint256)`.
  2. Call `highestBidForEdition(uint256 _editionNumber)` (`0x017b0d00`) -> returns `(address bidder, uint256 value)`.
  3. If `(bidder == user && value > 0)` and `paused() == false`, simulate `withdrawBid(_editionNumber)`.
  4. If `bidder == 0x0`, check `BidAccepted` logs (`topic0 = 0x77273c2a169296530c120eb6f1142012378aad0ed4337eac090eaf4223a1a2f1`, `topic2 = _editionNumber`)—if present, `topic3` is the `tokenId` minted to the user on KODA V2 (`0xfbeef911dc5821886e1dda71586d90ed28174b7d`).

### F. CryptoKitties Core (`0x06012c8cf97bead5deae237070f9587f8e7a266d`) & Pre-ERC721 Gas Traps
* **Trap 1 (Unindexed by `tokennfttx`):** Deployed in November 2017 prior to EIP-721 finalization (`supportsInterface` differs), so Etherscan/Routescan `tokennfttx` endpoints return `0` transfers for CryptoKitties, making owned kitties invisible to standard NFT transfer scans.
* **Trap 2 (`tokensOfOwner` Out-of-Gas Revert):** Calling `tokensOfOwner(address)` (`0x8462151c`) via `eth_call` reverts with `out of gas` on public RPCs because it loops linearly from `kittyId = 1` to `totalSupply()` ($>2,000,000$ storage reads).
* **How to Enumerate & Inspect:**
  1. Check `balanceOf(address)` (`0x70a08231`) first (`scan_evm_funds.py` does this automatically in Phase 1).
  2. Extract 32-byte arguments ($1 < \text{id} < 3,000,000$) from the user's historical transactions to `0x06012c8cf97bead5deae237070f9587f8e7a266d` (`breedWithAuto`, `createSaleAuction`, `bidOnSiringAuction`, `transfer`).
  3. Batch `ownerOf(uint256)` (`0x6352211e`) and `getKitty(uint256)` (`0xe98b7f4d`, where the 9th 32-byte word is `generation` and 3rd word is `cooldownIndex`) to identify valuable Gen 0 / Gen 1 / Fast-cooldown kitties.

---

## 2. Legacy ENS & Naming Registrars

### A. Old ENS Interim Registrar Deeds (2017–2019 Vicky Auctions)
* **Contract:** `0x6090A6e47849629b7245Dfa1Ca21D94cd15878Ef`
* **Trap:** Between 2017 and May 2019, registering a `.eth` name locked ETH inside an individual **Deed** contract via `unsealBid(bytes32 _hash, uint256 _value, bytes32 _salt)` (`0x47872b42`). Even if the `.eth` name later expired or was migrated to the permanent registrar, the locked ETH remains inside the Deed until `releaseDeed(bytes32 _hash)` (`0x0230a07c`) is called.
* **How to Find:**
  Query `BidRevealed(bytes32 indexed hash, address indexed owner, uint256 value, uint8 status)` logs on `0x6090A6e47849629b7245Dfa1Ca21D94cd15878Ef` where `topic2 = padded_user_address`. For each `hash` (`topic1`), call `entries(bytes32)` (`0x267b6922`) on `0x6090A6e4...` to get the `Deed` contract address (`second return value`) and check `eth_getBalance(deedAddress)`.

---

## 3. NFT Marketplaces, Creator Splits & Royalty Escrows

| Protocol | Contract Address (Mainnet) | State Getter | Withdrawal Function |
| :--- | :--- | :--- | :--- |
| **Foundation (FETH)** | `0x3B3ee1931Dc30C1957379FAc9aba94D1C48a5405` | `balanceOf(address)` & `totalBalanceOf(address)` | `withdrawAvailableBalance()` |
| **Blur Pool** | `0x0000000000A39bb272e79075ade125fd351887Ac` | `balanceOf(address)` | `withdraw(uint256 amount)` |
| **0xSplits (`SplitMain`)** | `0x2ed6c4B5dA6378c7897AC67Ba9e43102Feb694EE` | `getETHBalance(address)` / `getERC20Balance(address,token)` | `withdraw(address,uint256,ERC20[])` |
| **Zora Protocol Rewards** | `0x7777777F279eba3d3Ad8F4E708545291A6fDBA8B` *(Mainnet, Base, OP, Arb, Zora)* | `balanceOf(address)` | `withdraw(address to, uint256 amount)` |
| **Zora V1/V2/V3 Asks & Auctions** | `0x5f7072E1fA7c01dfAc7Cf54289621AFAaD2184d0` | `auctions(uint256)` | `endAuction(uint256)` / `cancelAuction(uint256)` |
| **AsyncArt V2 Market** | `0xb6dAe651468E9593E4581705a09c10A76AC1e0c8` | `pendingPayments(address)` / active `bids` | `withdrawPendingPayments()` / `withdrawBid(address,uint256)` |
| **SuperRare V1 / Bazaar** | `0x41A322b28D0fF354040e2CbC676F0320d8c8850d` / `0x6D7c44773C52D396F43c2D511B81aa168E9a7a42` | `currentBidDetailsOfToken(uint256)` / `payments(address)` | `cancelBid(...)` / `withdrawPayments(address)` |
| **Sudoswap V1 LSSVM** | Factory `0xb16c1342E617A5B6E4b631EB114483FDB289c0A4` | Pair contracts created via `createPairETH` where `owner() == user` | `withdrawAllETH()` / `withdrawERC721(...)` on the pair clone |

---

## 4. DeFi, Bridges & Staking Vault Patterns

1. **MasterChef / Liquidity Mining (`deposit(uint256 pid, uint256 amount)`):**
   - Does **not** mint an ERC-20 receipt token (`balanceOf(user)` is nonexistent or 0).
   - Inspect historical `deposit(uint256 _pid, uint256 _amount)` (`0xe2bbb158`) calldata to extract the `pid` (first 32-byte argument), then call `userInfo(uint256 pid, address user)` (`0x93f1a40b`) to check if `amount > 0`.
2. **Bancor V3 Delayed Withdrawals (`0xeef417e1d5cc832e619ae18d2f140de2999dd4fb`):**
   - Users call `initWithdrawal(address poolToken, uint256 amount)` which mints a withdrawal request ID. Compare total `initWithdrawal` calls against `cancelWithdrawal(uint256 id)` + `withdraw(uint256 id)` calls.
3. **Unclaimed Bridge / Cross-Chain Escrow Refunds:**
   - Across, Hop, Stargate, cBridge (`0x5427FEFA711Eff984124bFBB1AB6fbf5E3DA1820`), or Connext where a cross-chain transfer failed slippage on the destination chain and awaits a refund signature or `withdraw` on the source/destination bridge contract.

---

## 5. Cross-Chain & Bridged NFT Escrow Traps

One of the most persistent and high-value categories of lost assets are **NFTs bridged across L1 and L2 chains where the withdrawal process was started on the child chain but never finalized on L1**.

### A. Polygon PoS Bridge (`RootChainManager` & Predicates)
* **Architecture:**
  - Ethereum L1 `RootChainManagerProxy`: `0xA0c68C638235ee32657e8f720a23ceC1bFc77C77`
  - Ethereum L1 `ERC721PredicateProxy`: `0xE6F45376f64e1F568BD1404C155e5fFD2F80F7AD`
  - Ethereum L1 `MintableERC721PredicateProxy`: `0x932532a44c011c86b3e1342b2362a4b68c08390a`
  - Ethereum L1 `ERC1155PredicateProxy`: `0x0B9020d4E32990D67559b1317c7BF0C15D6EB88f`
* **The Trap:**
  1. An NFT is deposited into the bridge (either directly by the user via `RootChainManager.depositFor`, or by the collection creator/deployer to distribute on Polygon OpenSea, e.g. *CryptoSkulls* in May 2021). The original NFT is locked in `ERC721PredicateProxy`.
  2. The user calls `withdraw(uint256 tokenId)` on the Polygon child token contract (e.g. `0xd5a5ddd6f4e7d839db2978e8a4ee9923ac088cb3`). This **burns** the child NFT on Polygon.
  3. The bridge requires submitting a cryptographic proof to Ethereum L1 via `RootChainManagerProxy.exit(bytes inputData)` (`0x3805550f`).
  4. If the user never executes `exit(bytes)` on L1 (e.g. due to high L1 gas fees or lack of awareness), the NFT remains **permanently locked in the L1 predicate** while appearing completely gone from the child chain!
* **How to Detect & Recover:**
  1. Inspect Polygon child-chain outgoing token transfers for burns (`to == 0x0000000000000000000000000000000000000000` or method `withdraw(uint256)`).
  2. For the root token on Ethereum Mainnet, check `ownerOf(tokenId)`. If the current owner is `ERC721PredicateProxy` (`0xE6F45376f64e1F568BD1404C155e5fFD2F80F7AD`), the NFT is still trapped and claimable!
  3. Generate the 10-field RLP exit proof via Polygon's official proof API:
     ```text
     GET https://proof-generator.polygon.technology/api/v1/matic/exit-payload/<burnTxHash>?eventSignature=0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef
     ```
  4. The returned payload contains the 10 RLP fields:
     - `0 - headerNumber`: Checkpoint block number
     - `1 - blockProof`: Merkle leaf proof of child block in checkpoint
     - `2 - blockNumber`: Child block number
     - `3 - blockTime`: Child block timestamp
     - `4 - txRoot`: Transactions root
     - `5 - receiptRoot`: Receipts root
     - `6 - receipt`: RLP-encoded receipt of the burn tx
     - `7 - receiptProof`: Merkle Patricia proof of receipt
     - `8 - branchMask`: Receipt index path mask
     - `9 - receiptLogIndex`: Log index of the Transfer/burn event
  5. Call `exit(bytes inputData)` on `0xA0c68C638235ee32657e8f720a23ceC1bFc77C77` on Ethereum Mainnet to unlock and receive the NFT.

### B. Arbitrum Rollup Classic & Nitro Bridge (`L2ERC721Gateway` $\to$ `Outbox`)
* **Architecture:**
  - Ethereum L1 `L1ERC721Gateway`: `0x6c411a0516379304461ec1eac050411d78966ec4`
  - Ethereum L1 `Outbox`: `0x0B9857ae2D4A3DBe74ffE1d7DF045bb7F96E4840`
  - Arbitrum L2 `L2ERC721Gateway`: `0x09e9222e96e7b4ae2a40745346391a59535386bf`
* **The Trap:**
  1. User calls `withdrawERC721` on Arbitrum L2. The L2 token is burned and placed in the L2 outbox message queue.
  2. After the 7-day challenge period passes, an L1 execution transaction calling `Outbox.executeTransaction(...)` must be submitted.
  3. If not submitted, the original NFT stays locked in `L1ERC721Gateway`.
* **Detection:** Query the user's Arbitrum withdrawal history against the Arbitrum Outbox tracker; execute the claim transaction on L1 once the assertion is confirmed.

### C. Optimism & OP Stack Rollups (Optimism, Base, Zora, Blast)
* **Architecture:**
  - Ethereum L1 `L1ERC721Bridge`: `0x5A7749f83b81B301cAb5f48EB8516B986DAda23D` (Optimism), `0x608d943668a5b306b3a2a6b2520c1598f828a2a7` (Base)
  - Ethereum L1 `OptimismPortal`
* **The Trap:**
  - 2-step withdrawal process:
    1. `OptimismPortal.proveWithdrawalTransaction(...)` (after output root is proposed).
    2. Wait 7-day fault dispute window.
    3. `OptimismPortal.finalizeWithdrawalTransaction(...)`.
  - Countless users initiate step 1 (or do neither) and never submit step 3 on L1, leaving the NFT locked in `L1ERC721Bridge`.

### D. Gnosis Chain $\to$ Ethereum Arbitrary Message Bridge (AMB) & NFT Mediators (`Nifty.Ink`)
* **Architecture:**
  - Gnosis Chain Home AMB: `0x75Df5AF045d91108662D8080fD1FEFAd6aA0bb59`
  - Ethereum Mainnet Foreign AMB: `0x4C36d2919e407f0Cc2Ee3c993ccF8ac26d9CE64e`
  - Nifty.Ink Gnosis Mediator: `0x73cA9C4e72fF109259cf7374F038faf950949C51` $\to$ Ethereum L1 NFT: `0xc02697c417DdAcfbe5Edbf23eDad956BC883F4fb`
* **The Trap:**
  - When a user calls `relayToken(uint256 _tokenId)` (`0xd4375104`) on Gnosis Chain, the NFT is transferred into the Gnosis mediator (`ownerOf(tokenId) == mediator`), so it looks "escrowed" on Gnosis forever.
  - Meanwhile, the Home AMB emits `UserRequestForSignature(bytes32 indexed messageId, bytes encodedData)` (`topic0 = 0x520d2afde79cbd5db58755ac9480f81bc658e5c517fcae7365a3d832590b0183`).
  - If `ForeignAMB.relayedMessages(bytes32 messageId)` (`0x21d800ec`) on Ethereum Mainnet is `false`, the user never called `executeSignatures(bytes _data, bytes _signatures)` on L1 to claim their bridged NFT! If `true`, the NFT was already minted on Ethereum L1.
* **Automated Verification:**
  Run `python scripts/verify_recovery.py --amb-tx <GnosisRelayTxHash> --user <0xUserAddress>` to automatically extract `messageId`, check `relayedMessages(messageId)` on Ethereum L1, and locate the minted L1 NFT and current owner.

---

## 6. Etherscan Proxy Interaction Cheatsheet

Many factory-deployed contracts (MISO auctions, PartyBids, Sudoswap pairs, Gnosis Safes, 0xSplits) are **EIP-1167 minimal proxies** whose bytecode is:
```text
0x363d3d373d3d3d363d73<20-byte-implementation-address>5af43d82803e903d91602b57fd5bf3
```
* If Etherscan only shows a raw bytecode tab (no **Write as Proxy** tab), instruct the user to visit:
  `https://etherscan.io/proxyContractChecker?a=<ProxyAddress>`
  Clicking **Save** immediately links the implementation ABI on Etherscan and unlocks `#writeProxyContract`.
* Always provide the **raw hex calldata** (`Selector + ABI-encoded arguments`) alongside Etherscan instructions so advanced users can submit a `0 ETH` transaction with raw hex data directly from Rabby, MetaMask, or Frame without waiting on Etherscan's UI.
