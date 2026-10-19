#!/usr/bin/env python3
"""
EVM Recovery Verifier & Simulator
Zero-dependency Python 3 script (stdlib only).
Verifies contract state, unwraps proxies, and simulates recovery transactions via eth_call + eth_estimateGas.
"""

import argparse
import json
import sys
import urllib.request

RPC_BY_CHAIN = {
    "Ethereum": ("https://ethereum-rpc.publicnode.com", "https://etherscan.io"),
    "Arbitrum": ("https://arbitrum-one-rpc.publicnode.com", "https://arbiscan.io"),
    "Optimism": ("https://optimism-rpc.publicnode.com", "https://optimistic.etherscan.io"),
    "Base": ("https://base-rpc.publicnode.com", "https://basescan.org"),
    "Polygon": ("https://polygon-bor-rpc.publicnode.com", "https://polygonscan.com"),
    "BSC": ("https://bsc-rpc.publicnode.com", "https://bscscan.com"),
    "Avalanche": ("https://api.avax.network/ext/bc/C/rpc", "https://snowtrace.io"),
    "Fantom": ("https://rpcapi.fantom.network", "https://ftmscan.com"),
    "Gnosis": ("https://gnosis-rpc.publicnode.com", "https://gnosisscan.io"),
    "Zora": ("https://rpc.zora.energy", "https://explorer.zora.energy"),
    "Blast": ("https://rpc.blast.io", "https://blastscan.io"),
}

EIP1967_IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"


def rpc_call(rpc_url, method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sha3_selector(rpc_url, sig):
    hex_sig = "0x" + sig.encode("utf-8").hex()
    res = rpc_call(rpc_url, "web3_sha3", [hex_sig]).get("result", "")
    return res[:10]


def detect_proxy(rpc_url, contract):
    code = rpc_call(rpc_url, "eth_getCode", [contract, "latest"]).get("result", "0x").lower()
    if code.startswith("0x363d3d373d3d3d363d73") and len(code) >= 62:
        return ("EIP-1167 Minimal Proxy", "0x" + code[22:62])
    slot_val = rpc_call(rpc_url, "eth_getStorageAt", [contract, EIP1967_IMPL_SLOT, "latest"]).get("result", "0x0")
    if slot_val and int(slot_val, 16) != 0:
        return ("EIP-1967 Proxy", "0x" + slot_val[-40:])
    return (None, None)


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
        clean = val[2:] if val.startswith("0x") else val
        raw = bytes.fromhex(clean)
        length_hex = hex(len(raw))[2:].rjust(64, "0")
        padded_data = clean.ljust(((len(raw) + 31) // 32) * 64, "0")
        return (32).to_bytes(32, "big").hex() + length_hex + padded_data
    raise ValueError(f"Unsupported ABI type in simple encoder: {arg_type}")


def inspect_contract(rpc_url, explorer, contract, user):
    bal = int(rpc_call(rpc_url, "eth_getBalance", [contract, "latest"]).get("result", "0x0"), 16) / 1e18
    ptype, impl = detect_proxy(rpc_url, contract)
    print(f"=== Contract Inspection: {contract} ===")
    print(f"Live Native Balance: {bal:.6f}")
    if ptype:
        print(f"Proxy Detected:      {ptype} -> Implementation: {impl}")
        print(f"Proxy Checker URL:   {explorer}/proxyContractChecker?a={contract}")
    else:
        print("Proxy Detected:      None (Standalone Contract)")

    padded_user = user[2:].lower().rjust(64, "0")
    probes = [
        ("balanceOf(address)", True),
        ("balances(address)", True),
        ("commitments(address)", True),
        ("claimed(address)", True),
        ("tokensClaimable(address)", True),
        ("pendingWithdrawals(address)", True),
        ("deposits(address)", True),
        ("stakedBalance(address)", True),
        ("auctionSuccessful()", False),
        ("finalized()", False),
    ]
    print("\n--- Common State Probes ---")
    for sig, takes_user in probes:
        sel = sha3_selector(rpc_url, sig)
        data = sel + (padded_user if takes_user else "")
        res = rpc_call(rpc_url, "eth_call", [{"from": user, "to": contract, "data": data}, "latest"])
        if "result" in res and res["result"] and res["result"] != "0x":
            raw_int = int(res["result"][:66], 16)
            print(f"  {sig:30s} ({sel}) -> raw={raw_int} ({raw_int / 1e18:.6f} if 18-dec)")


def simulate_call(rpc_url, explorer, contract, user, sig, raw_args, raw_calldata=None):
    ptype, impl = detect_proxy(rpc_url, contract)
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
    print(f"Full Hex Calldata:  {calldata}")

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


def main():
    parser = argparse.ArgumentParser(description="Inspect and simulate EVM recovery transactions")
    parser.add_argument("--chain", default="Ethereum", help="Chain name (e.g. ethereum, arbitrum, optimism, base)")
    parser.add_argument("--contract", required=True, help="Target contract address")
    parser.add_argument("--user", "--wallet", dest="user", required=True, help="User wallet address")
    parser.add_argument("--inspect", action="store_true", help="Inspect proxy status and probe common getters")
    parser.add_argument("--sig", help="Function signature, e.g. 'withdrawTokens(address)'")
    parser.add_argument("--args", default="", help="Comma-separated arguments matching --sig")
    parser.add_argument("--calldata", "--raw-calldata", dest="calldata", help="Raw hex calldata to simulate directly")
    parser.add_argument("--guide", action="store_true", help="Output step-by-step Etherscan recovery guide")
    args = parser.parse_args()

    chain_lookup = {k.lower(): (k, v) for k, v in RPC_BY_CHAIN.items()}
    key = args.chain.lower()
    if key not in chain_lookup:
        parser.error(f"Unsupported --chain '{args.chain}'. Choose from: {', '.join(RPC_BY_CHAIN.keys())}")
    _, (rpc_url, explorer) = chain_lookup[key]

    if args.inspect or (not args.sig and not args.calldata):
        inspect_contract(rpc_url, explorer, args.contract, args.user)
    if args.sig or args.calldata:
        simulate_call(rpc_url, explorer, args.contract, args.user, args.sig, args.args, args.calldata)


if __name__ == "__main__":
    main()
