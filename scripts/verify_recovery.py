#!/usr/bin/env python3
"""
EVM Recovery Verifier, Proxy Decompiler & Cross-Chain Bridge Simulator
----------------------------------------------------------------------
Zero-dependency Python 3 script (stdlib only).
- Unwraps EIP-1167 / EIP-1967 proxies and fetches verified ABI / source names.
- Decompiles unverified contract bytecode via PUSH4 selector extraction + OpenChain lookup.
- Probes common escrow, auction, staking, and pull-payment state mappings.
- Simulates recovery calls via eth_call, eth_estimateGas, and eth_createAccessList.
- Generates & simulates Polygon PoS Bridge L1 exit proofs (--polygon-burn-tx).
- Verifies Gnosis -> Ethereum AMB cross-chain message execution & L1 NFT ownership (--amb-tx).
"""

import argparse
import json
import re
import sys
import urllib.request

RPC_BY_CHAIN = {
    "Ethereum": (1, "https://ethereum-rpc.publicnode.com", "https://etherscan.io", "https://eth.blockscout.com/api"),
    "Arbitrum": (42161, "https://arbitrum-one-rpc.publicnode.com", "https://arbiscan.io", "https://arbitrum.blockscout.com/api"),
    "Optimism": (10, "https://optimism-rpc.publicnode.com", "https://optimistic.etherscan.io", "https://optimism.blockscout.com/api"),
    "Base": (8453, "https://base-rpc.publicnode.com", "https://basescan.org", "https://base.blockscout.com/api"),
    "Polygon": (137, "https://polygon-bor-rpc.publicnode.com", "https://polygonscan.com", "https://polygon.blockscout.com/api"),
    "BSC": (56, "https://bsc-rpc.publicnode.com", "https://bscscan.com", None),
    "Avalanche": (43114, "https://api.avax.network/ext/bc/C/rpc", "https://snowtrace.io", None),
    "Fantom": (250, "https://rpcapi.fantom.network", "https://ftmscan.com", None),
    "Gnosis": (100, "https://rpc.gnosischain.com", "https://gnosisscan.io", "https://gnosis.blockscout.com/api"),
    "Zora": (7777777, "https://rpc.zora.energy", "https://explorer.zora.energy", "https://explorer.zora.energy/api"),
    "Blast": (81457, "https://rpc.blast.io", "https://blastscan.io", None),
}

EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"


def fetch_json(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def rpc_call(rpc_url, method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def sha3_selector(rpc_url, sig):
    hex_sig = "0x" + sig.encode("utf-8").hex()
    res = rpc_call(rpc_url, "web3_sha3", [hex_sig]).get("result", "")
    return res[:10]


def detect_proxy(rpc_url, contract):
    code = rpc_call(rpc_url, "eth_getCode", [contract, "latest"]).get("result", "0x").lower()
    if code.startswith("0x363d3d373d3d3d363d73") and len(code) >= 62:
        return ("EIP-1167 Minimal Proxy", "0x" + code[22:62], code)
    slot_val = rpc_call(rpc_url, "eth_getStorageAt", [contract, EIP1967_IMPL_SLOT, "latest"]).get("result", "0x0")
    if slot_val and slot_val != "0x" and int(slot_val, 16) != 0:
        return ("EIP-1967 Proxy", "0x" + slot_val[-40:], code)
    return (None, None, code)


def fetch_verified_abi(chain_id, blockscout_api, target_addr):
    apis = [f"https://api.routescan.io/v2/network/mainnet/evm/{chain_id}/etherscan/api?module=contract&action=getsourcecode&address={target_addr}"]
    if blockscout_api:
        apis.append(f"{blockscout_api}?module=contract&action=getsourcecode&address={target_addr}")
    for url in apis:
        data = fetch_json(url, timeout=15)
        res = data.get("result")
        if isinstance(res, list) and res and isinstance(res[0], dict):
            item = res[0]
            cname = item.get("ContractName") or ""
            abi_str = item.get("ABI") or ""
            if cname and abi_str and not abi_str.startswith("Contract source code not verified"):
                try:
                    return cname, json.loads(abi_str)
                except Exception:
                    pass
    return None, None


def decompile_bytecode_selectors(bytecode_hex):
    sels = sorted(list(set(re.findall(r"63([0-9a-f]{8})", (bytecode_hex or "").lower()))))
    sels = [s for s in sels if s not in ("ffffffff", "00000000")]
    if not sels:
        return {}
    resolved = {}
    for start in range(0, len(sels), 25):
        chunk = sels[start : start + 25]
        q = ",".join("0x" + s for s in chunk)
        url = f"https://api.openchain.xyz/signature-database/v1/lookup?function={q}"
        data = fetch_json(url, timeout=12)
        fmap = data.get("result", {}).get("function", {})
        for k, v in fmap.items():
            if v:
                resolved[k] = [item.get("name") for item in v if item.get("name")]
    return resolved


def encode_arg(arg_type, val):
    arg_type = arg_type.strip()
    val = val.strip()
    if arg_type == "address":
        clean = val[2:] if val.startswith("0x") else val
        return clean.lower().rjust(64, "0")
    if arg_type.startswith("uint") or arg_type.startswith("int"):
        n = int(val, 16) if val.startswith("0x") else int(val)
        return hex(n)[2:].rjust(64, "0")
    if arg_type == "bool":
        b = 1 if val.lower() in ("true", "1", "yes") else 0
        return hex(b)[2:].rjust(64, "0")
    if arg_type == "bytes32":
        clean = val[2:] if val.startswith("0x") else val
        return clean.lower().ljust(64, "0")
    if arg_type.startswith("bytes") and not arg_type.endswith("]"):
        if arg_type != "bytes":
            # fixed bytesN (e.g. bytes5)
            clean = val[2:] if val.startswith("0x") else val
            return clean.lower().ljust(64, "0")
        clean = val[2:] if val.startswith("0x") else val
        raw = bytes.fromhex(clean)
        length_hex = hex(len(raw))[2:].rjust(64, "0")
        padded_data = clean.ljust(((len(raw) + 31) // 32) * 64, "0")
        return (32).to_bytes(32, "big").hex() + length_hex + padded_data
    raise ValueError(f"Unsupported ABI type in simple encoder: {arg_type}")


def inspect_contract(chain_id, rpc_url, explorer, blockscout_api, contract, user):
    bal = int(rpc_call(rpc_url, "eth_getBalance", [contract, "latest"]).get("result") or "0x0", 16) / 1e18
    ptype, impl, code = detect_proxy(rpc_url, contract)
    print(f"=== Contract Inspection: {contract} ===")
    print(f"Live Native Balance: {bal:.6f}")
    if ptype:
        print(f"Proxy Detected:      {ptype} -> Implementation: {impl}")
        print(f"Proxy Checker URL:   {explorer}/proxyContractChecker?a={contract}")
    else:
        print("Proxy Detected:      None (Standalone Contract)")

    abi_target = impl if impl else contract
    cname, abi = fetch_verified_abi(chain_id, blockscout_api, abi_target)
    if cname and abi:
        print(f"Verified Name:       {cname} (on {abi_target})")
        views, writes = [], []
        for item in abi:
            if item.get("type") == "function":
                fn = item.get("name", "")
                inps = ",".join(i.get("type", "") for i in item.get("inputs", []))
                sig = f"{fn}({inps})"
                if item.get("stateMutability") in ("view", "pure") or item.get("constant"):
                    views.append(sig)
                else:
                    writes.append(sig)
        print(f"Verified View Funcs: {views[:15]}")
        recovery_writes = [w for w in writes if any(k in w.lower() for k in ["withdraw", "claim", "cancel", "exit", "refund", "release", "expire", "finalize", "unstake", "redeem"])]
        print(f"Recovery Write Funcs:{recovery_writes if recovery_writes else writes[:12]}")
    else:
        target_code = rpc_call(rpc_url, "eth_getCode", [abi_target, "latest"]).get("result", "0x") if impl else code
        decompiled = decompile_bytecode_selectors(target_code)
        print(f"Verified Source:     Unverified (Decompiled {len(decompiled)} selectors via OpenChain)")
        for sel, names in list(decompiled.items())[:20]:
            print(f"  {sel}: {names}")

    padded_user = user[2:].lower().rjust(64, "0")
    probes = [
        ("balanceOf(address)", "0x70a08231" + padded_user),
        ("balances(address)", "0x27e235e3" + padded_user),
        ("commitments(address)", "0x839df945" + padded_user),
        ("claimed(address)", "0xc884ef83" + padded_user),
        ("tokensClaimable(address)", "0x58b9031a" + padded_user),
        ("pendingWithdrawals(address)", "0xf3f43703" + padded_user),
        ("pendingWithdrawals_alt(address)", "0xe4fed517" + padded_user),
        ("deposits(address)", "0xfc7e286d" + padded_user),
        ("checkDepositorBalance()", "0x0f42c61d"),
        ("getETHBalance(address)", "0x4ff61f38" + padded_user),
        ("auctionSuccessful()", "0x321c97b2"),
        ("finalized()", "0xb390c0ab"),
        ("paused()", "0x5c975abb"),
    ]
    for pid in range(4):
        pid_hex = hex(pid)[2:].rjust(64, "0")
        probes.append((f"userInfo({pid},user)", "0x93f1a40b" + pid_hex + padded_user))

    print("\n--- Common State Probes ---")
    for label, data in probes:
        res = rpc_call(rpc_url, "eth_call", [{"from": user, "to": contract, "data": data}, "latest"])
        if "result" in res and res["result"] and res["result"] != "0x" and len(res["result"]) >= 66:
            raw_int = int(res["result"][:66], 16)
            if raw_int > 0 or label in ("auctionSuccessful()", "finalized()", "paused()"):
                print(f"  {label:32s} -> raw={raw_int} ({raw_int / 1e18:.6f} if 18-dec)")


def simulate_call(rpc_url, explorer, contract, user, sig, raw_args, raw_calldata=None):
    ptype, impl, _ = detect_proxy(rpc_url, contract)
    if raw_calldata:
        calldata = raw_calldata if raw_calldata.startswith("0x") else "0x" + raw_calldata
        sel = calldata[:10]
        arg_types, arg_vals = [], []
    else:
        sel = sha3_selector(rpc_url, sig)
        inside = sig[sig.find("(") + 1 : sig.rfind(")")]
        arg_types = [x.strip() for x in inside.split(",") if x.strip()]
        arg_vals = [x.strip() for x in (raw_args or "").split(",") if x.strip()]

        if len(arg_types) != len(arg_vals):
            raise ValueError(f"Signature {sig} expects {len(arg_types)} args, got {len(arg_vals)}")

        encoded_args = "".join(encode_arg(t, v) for t, v in zip(arg_types, arg_vals))
        calldata = sel + encoded_args

    print(f"=== Dry-Run Simulation on {contract} ===")
    if sig:
        print(f"Function Signature: {sig}")
    print(f"4-Byte Selector:    {sel}")
    print(f"Full Hex Calldata:  {calldata[:138]}{'...' if len(calldata) > 138 else ''} ({len(calldata)//2 - 1} bytes)")

    call_res = rpc_call(rpc_url, "eth_call", [{"from": user, "to": contract, "data": calldata}, "latest"])
    if "error" in call_res:
        print(f"\n[!] SIMULATION REVERTED: {call_res['error']}")
        return

    gas_res = rpc_call(rpc_url, "eth_estimateGas", [{"from": user, "to": contract, "data": calldata}])
    gas_used = int(gas_res.get("result", "0x0"), 16) if "result" in gas_res else None
    al_res = rpc_call(rpc_url, "eth_createAccessList", [{"from": user, "to": contract, "data": calldata}, "latest"])
    touched = [x.get("address") for x in al_res.get("result", {}).get("accessList", [])]

    print(f"\n[OK] Simulation Succeeded!")
    print(f"Return Data:        {call_res.get('result')}")
    print(f"Estimated Gas:      {gas_used}")
    print(f"Touched Contracts:  {touched}")

    tab = "#writeProxyContract" if ptype else "#writeContract"
    print("\n--- Ready-to-Share User Recovery Instructions ---")
    if ptype:
        print(f"1. Link Proxy ABI (if needed): {explorer}/proxyContractChecker?a={contract}")
    print(f"2. Open Explorer Write Tab:    {explorer}/address/{contract}{tab}")
    print(f"3. Connect Wallet:             {user}")
    if sig:
        print(f"4. Function to Call:           {sig}")
        for idx, (t, v) in enumerate(zip(arg_types, arg_vals), 1):
            print(f"   - Param {idx} ({t}): {v}")
    print(f"5. Raw Calldata Fallback:      To={contract} | Value=0 ETH | Data={calldata}")


def verify_polygon_exit(burn_tx_hash, user):
    print(f"=== Polygon PoS Bridge Exit Proof Generator & L1 Simulator ===")
    print(f"Child Burn Tx Hash: {burn_tx_hash}")
    transfer_sig = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    url = f"https://proof-generator.polygon.technology/api/v1/matic/exit-payload/{burn_tx_hash}?eventSignature={transfer_sig}"
    data = fetch_json(url, timeout=30)
    proof_hex = data.get("result")
    if not proof_hex:
        print(f"[!] Could not generate exit payload: {data}")
        return
    print(f"[OK] Generated 10-field RLP exit proof ({len(proof_hex)//2 - 1} bytes): {proof_hex[:80]}...")
    root_chain_mgr = "0xA0c68C638235ee32657e8f720a23ceC1bFc77C77"
    eth_rpc = RPC_BY_CHAIN["Ethereum"][1]
    eth_explorer = RPC_BY_CHAIN["Ethereum"][2]
    simulate_call(eth_rpc, eth_explorer, root_chain_mgr, user, "exit(bytes)", proof_hex)


def verify_gnosis_amb(gnosis_tx_hash, user):
    print(f"=== Gnosis -> Ethereum AMB Cross-Chain Relay Verifier ===")
    gnosis_rpc = RPC_BY_CHAIN["Gnosis"][1]
    eth_rpc = RPC_BY_CHAIN["Ethereum"][1]
    receipt = rpc_call(gnosis_rpc, "eth_getTransactionReceipt", [gnosis_tx_hash]).get("result")
    if not receipt:
        print(f"[!] Could not fetch Gnosis receipt for {gnosis_tx_hash}")
        return
    amb_topic = "0x520d2afde79cbd5db58755ac9480f81bc658e5c517fcae7365a3d832590b0183"
    msg_ids = []
    for l in receipt.get("logs", []):
        topics = l.get("topics") or []
        if len(topics) >= 2 and topics[0].lower() == amb_topic:
            msg_ids.append(topics[1])
    if not msg_ids:
        print("[!] No UserRequestForSignature AMB event found in Gnosis transaction.")
        return

    foreign_amb = "0x4C36d2919e407f0Cc2Ee3c993ccF8ac26d9CE64e"
    for mid in msg_ids:
        res = rpc_call(eth_rpc, "eth_call", [{"to": foreign_amb, "data": "0x21d800ec" + mid[2:].zfill(64)}, "latest"]).get("result", "0x0")
        relayed = int(res, 16) == 1
        print(f"AMB Message ID:     {mid}")
        print(f"Relayed on Eth L1:  {relayed}")
        if relayed:
            log_url = f"https://api.routescan.io/v2/network/mainnet/evm/1/etherscan/api?module=logs&action=getLogs&fromBlock=10000000&toBlock=latest&address={foreign_amb}&topic3={mid}"
            logs = fetch_json(log_url, timeout=15).get("result", [])
            if isinstance(logs, list) and logs:
                l1_tx = logs[0].get("transactionHash")
                print(f"L1 Execution Tx:    https://etherscan.io/tx/{l1_tx}")
                rec_url = f"https://api.routescan.io/v2/network/mainnet/evm/1/etherscan/api?module=proxy&action=eth_getTransactionReceipt&txhash={l1_tx}"
                l1_rec = fetch_json(rec_url, timeout=15).get("result") or {}
                for l in l1_rec.get("logs", []):
                    t_list = l.get("topics") or []
                    if len(t_list) >= 4 and t_list[0].lower() == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef":
                        nft_c = l.get("address")
                        tid = int(t_list[3], 16)
                        own_res = rpc_call(eth_rpc, "eth_call", [{"to": nft_c, "data": "0x6352211e" + t_list[3][2:]}, "latest"]).get("result", "0x")
                        cur_owner = "0x" + own_res[-40:] if len(own_res) >= 42 else "unknown"
                        print(f"L1 Bridged NFT:     Contract {nft_c} | Token #{tid} | Current L1 Owner: {cur_owner}")


def main():
    parser = argparse.ArgumentParser(description="Inspect and simulate EVM recovery transactions")
    parser.add_argument("--chain", default="Ethereum", help="Chain name (e.g. ethereum, arbitrum, optimism, base, polygon, gnosis)")
    parser.add_argument("--contract", help="Target contract address")
    parser.add_argument("--user", "--wallet", dest="user", required=True, help="User wallet address")
    parser.add_argument("--inspect", action="store_true", help="Inspect proxy status, verified ABI / bytecode selectors, and state getters")
    parser.add_argument("--sig", help="Function signature, e.g. 'withdrawTokens(address)'")
    parser.add_argument("--args", default="", help="Comma-separated arguments matching --sig")
    parser.add_argument("--calldata", "--raw-calldata", dest="calldata", help="Raw hex calldata to simulate directly")
    parser.add_argument("--polygon-burn-tx", help="Polygon child burn tx hash to generate RLP proof and simulate RootChainManager.exit(bytes) on Ethereum L1")
    parser.add_argument("--amb-tx", help="Gnosis Chain AMB bridge tx hash to check Ethereum Foreign AMB execution status")
    parser.add_argument("--guide", action="store_true", help="Output step-by-step Etherscan recovery guide")
    args = parser.parse_args()

    if args.polygon_burn_tx:
        verify_polygon_exit(args.polygon_burn_tx, args.user)
        return
    if args.amb_tx:
        verify_gnosis_amb(args.amb_tx, args.user)
        return
    if not args.contract:
        parser.error("--contract is required unless using --polygon-burn-tx or --amb-tx")

    chain_lookup = {k.lower(): (k, v) for k, v in RPC_BY_CHAIN.items()}
    key = args.chain.lower()
    if key not in chain_lookup:
        parser.error(f"Unsupported --chain '{args.chain}'. Choose from: {', '.join(RPC_BY_CHAIN.keys())}")
    _, (chain_id, rpc_url, explorer, blockscout_api) = chain_lookup[key]

    if args.inspect or (not args.sig and not args.calldata):
        inspect_contract(chain_id, rpc_url, explorer, blockscout_api, args.contract, args.user)
    if args.sig or args.calldata:
        simulate_call(rpc_url, explorer, args.contract, args.user, args.sig, args.args, args.calldata)


if __name__ == "__main__":
    main()
