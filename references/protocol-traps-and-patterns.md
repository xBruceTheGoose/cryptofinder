# Protocol Traps, Misleading Function Names, and Recovery Patterns

This reference catalogues smart contract mechanics where user funds become hidden due to counter-intuitive naming, proxy indirection, keyed storage, or multi-step state transitions.

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

## 5. Etherscan Proxy Interaction Cheatsheet

Many factory-deployed contracts (MISO auctions, PartyBids, Sudoswap pairs, Gnosis Safes, 0xSplits) are **EIP-1167 minimal proxies** whose bytecode is:
```text
0x363d3d373d3d3d363d73<20-byte-implementation-address>5af43d82803e903d91602b57fd5bf3
```
* If Etherscan only shows a raw bytecode tab (no **Write as Proxy** tab), instruct the user to visit:
  `https://etherscan.io/proxyContractChecker?a=<ProxyAddress>`
  Clicking **Save** immediately links the implementation ABI on Etherscan and unlocks `#writeProxyContract`.
* Always provide the **raw hex calldata** (`Selector + ABI-encoded arguments`) alongside Etherscan instructions so advanced users can submit a `0 ETH` transaction with raw hex data directly from Rabby, MetaMask, or Frame without waiting on Etherscan's UI.
